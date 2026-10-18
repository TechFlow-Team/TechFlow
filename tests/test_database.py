"""Integration tests against migrated MySQL 8; never create_all/drop_all."""
from datetime import datetime
from decimal import Decimal
import secrets

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
import pytest
from sqlalchemy import func, inspect, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.extensions import db
from app.migration_policy import include_object
from app.models import (
    AuditLog, Business, Category, Product, PurchaseReceipt, PurchaseReceiptItem,
    SalesOrder, SalesOrderItem, StockMovement, User,
)


def test_migrated_schema_matches_models(mysql_app):
    inspector = inspect(db.engine)
    assert set(db.metadata.tables).issubset(inspector.get_table_names())
    assert len(db.metadata.tables) == 23
    for name, table in db.metadata.tables.items():
        assert len(inspector.get_foreign_keys(name)) == len(table.foreign_key_constraints)
    with db.engine.connect() as connection:
        context = MigrationContext.configure(connection, opts={"include_object": include_object})
        assert compare_metadata(context, db.metadata) == []
        options = connection.execute(text(
            "SELECT ENGINE, TABLE_COLLATION FROM information_schema.TABLES "
            "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='products'"
        )).one()
        assert tuple(options) == ("InnoDB", "utf8mb4_unicode_ci")
    columns = {column["name"]: column for column in inspector.get_columns("products")}
    assert columns["id"]["type"].unsigned
    assert columns["stock_quantity"]["type"].unsigned
    assert columns["purchase_price"]["type"].precision == 14
    assert columns["purchase_price"]["type"].scale == 2
    indexes = {index["column_names"][0] for index in inspector.get_indexes("products")}
    assert {"name", "category_id", "business_id", "is_active"} <= indexes
    uniques = {tuple(item["column_names"]) for item in inspector.get_unique_constraints("products")}
    assert ("sku",) in uniques
    assert inspector.get_check_constraints("purchase_receipt_items")


def test_probe_policy_excludes_unmanaged_tables():
    assert not include_object(None, "stage1_probe", "table", True, None)
    assert not include_object(None, "unrelated", "table", True, None)
    assert include_object(None, "products", "table", False, None)


def test_decimal_defaults_unicode_and_relationships(mysql_app, catalog):
    product = db.session.get(Product, catalog["product_id"])
    assert product.purchase_price == Decimal("1234.56")
    assert product.stock_quantity == 0 and product.reorder_level == 5
    assert product.category.name.startswith("Danh mục test")
    assert product in product.business.products
    assert product.created_at is not None and product.updated_at is not None
    product.name = "Ổ cứng tiếng Việt 🎓"
    db.session.commit()
    db.session.expire_all()
    assert db.session.get(Product, catalog["product_id"]).name == "Ổ cứng tiếng Việt 🎓"


@pytest.mark.parametrize("field,value", [
    ("purchase_price", -1), ("selling_price", -1),
    ("stock_quantity", -1), ("reorder_level", -1), ("category_id", 999999999999),
])
def test_product_constraints_enforced_by_mysql(mysql_app, catalog, field, value):
    values = dict(sku=f"NEG-{secrets.token_hex(6)}", name="Invalid product",
                  category_id=catalog["category_id"], purchase_price=1, selling_price=2)
    values[field] = value
    db.session.add(Product(**values))
    with pytest.raises(DBAPIError):
        db.session.commit()
    db.session.rollback()
    assert db.session.scalar(select(Product.id).where(Product.sku == values["sku"])) is None


def test_duplicate_sku_rejected_case_insensitively(mysql_app, catalog):
    db.session.add(Product(sku=catalog["sku"].lower(), name="Duplicate",
                           category_id=catalog["category_id"], purchase_price=0, selling_price=0))
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


@pytest.mark.parametrize("model,field", [(Category, "category_id"), (Business, "business_id")])
def test_referenced_catalog_cannot_be_deleted(mysql_app, catalog, model, field):
    parent = db.session.get(model, catalog[field])
    list(parent.products)  # Loaded relations must not be nulled/cascaded by ORM.
    db.session.delete(parent)
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()
    assert db.session.get(model, catalog[field]) is not None


def test_all_transaction_relationships_without_stock_business_logic(mysql_app, catalog):
    product = db.session.get(Product, catalog["product_id"])
    purchase = PurchaseReceipt(receipt_code=f"PN-{catalog['suffix']}", business_id=catalog["business_id"],
                               created_by=catalog["user_id"], receipt_date=datetime(2026, 10, 9), total_amount=20)
    purchase.items.append(PurchaseReceiptItem(product=product, quantity=2, unit_cost=10, line_total=20))
    sale = SalesOrder(order_code=f"SO-{catalog['suffix']}", customer_name="Khách kiểm thử",
                      created_by=catalog["user_id"], order_date=datetime(2026, 10, 9), total_amount=30)
    sale.items.append(SalesOrderItem(product=product, quantity=2, unit_price=15, line_total=30))
    movement = StockMovement(product=product, created_by=catalog["user_id"], movement_type="adjustment",
                             quantity_delta=0, reference_type="adjustment", reason="Fixture schema test")
    audit = AuditLog(user_id=catalog["user_id"], action="schema_test", entity_type="product", entity_id=product.id)
    db.session.add_all([purchase, sale, movement, audit])
    db.session.commit()
    assert purchase.creator.id == catalog["user_id"]
    assert purchase.business.id == catalog["business_id"]
    assert sale.creator.id == catalog["user_id"]
    assert sale.items[0].product == product
    assert movement.creator.id == audit.user.id
    assert product.stock_quantity == 0  # Models never trigger stock updates.
    assert purchase.status == sale.status == "draft"
    list(product.purchase_items)
    db.session.delete(product)
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()
    assert db.session.get(Product, catalog["product_id"]) is not None


@pytest.mark.parametrize("kind", ["purchase_quantity", "sale_quantity", "line_total", "role", "status", "movement"])
def test_other_constraints(mysql_app, catalog, kind):
    if kind in {"purchase_quantity", "line_total"}:
        parent = PurchaseReceipt(receipt_code=f"BAD-{catalog['suffix']}", business_id=catalog["business_id"],
                                 created_by=catalog["user_id"], receipt_date=datetime(2026, 10, 9))
        parent.items.append(PurchaseReceiptItem(product_id=catalog["product_id"],
                                                quantity=0 if kind == "purchase_quantity" else 2,
                                                unit_cost=10, line_total=0 if kind == "purchase_quantity" else 99))
    elif kind == "sale_quantity":
        parent = SalesOrder(order_code=f"BAD-{catalog['suffix']}", customer_name="Test",
                            created_by=catalog["user_id"], order_date=datetime(2026, 10, 9))
        parent.items.append(SalesOrderItem(product_id=catalog["product_id"], quantity=0, unit_price=1, line_total=0))
    elif kind == "role":
        parent = User(username=f"bad-{catalog['suffix']}", full_name="Test", role="superadmin", password_hash="invalid-test-only")
    elif kind == "status":
        parent = SalesOrder(order_code=f"BAD-{catalog['suffix']}", customer_name="Test", status="unknown",
                            created_by=catalog["user_id"], order_date=datetime(2026, 10, 9))
    else:
        parent = StockMovement(product_id=catalog["product_id"], created_by=catalog["user_id"],
                                movement_type="unknown", reference_type="adjustment", quantity_delta=0)
    db.session.add(parent)
    # MySQL error 3819 is classified as OperationalError by PyMySQL.
    with pytest.raises(DBAPIError) as error:
        db.session.commit()
    assert error.value.orig.args[0] == 3819
    db.session.rollback()


def test_nullable_unique_tax_codes_and_unique_category_name(mysql_app, catalog):
    db.session.add_all([Business(code=f"NULL-{secrets.token_hex(6)}", name="Null tax"),
                        Business(code=f"NULL-{secrets.token_hex(6)}", name="Null tax")])
    db.session.commit()
    category = db.session.get(Category, catalog["category_id"])
    db.session.add(Category(code=f"DUP-{secrets.token_hex(6)}", name=category.name))
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


def test_seed_repeat_does_not_overwrite(mysql_app):
    runner = mysql_app.test_cli_runner()
    first = runner.invoke(args=["seed-demo"])
    assert first.exit_code == 0, first.output
    product = db.session.scalar(select(Product).where(Product.sku == "DEMO-SP-01-01"))
    product.name = "Tên đã chỉnh sửa cần giữ lại"
    product.selling_price = Decimal("123.45")
    db.session.commit()
    second = runner.invoke(args=["seed-demo"])
    assert second.exit_code == 0, second.output
    assert "categories=0, businesses=0, products=0" in second.output
    db.session.expire_all()
    assert product.name == "Tên đã chỉnh sửa cần giữ lại"
    assert product.selling_price == Decimal("123.45")
    for model, column, pattern, expected in [
        (Category, Category.code, "DEMO-CAT-%", 6),
        (Business, Business.code, "DEMO-NCC-%", 6),
        (Product, Product.sku, "DEMO-SP-%", 36),
    ]:
        assert db.session.scalar(select(func.count()).select_from(model).where(column.like(pattern))) == expected
    assert db.session.scalar(select(func.sum(Product.stock_quantity)).where(Product.sku.like("DEMO-SP-%"))) == 0


def test_admin_cli_secure_and_duplicate_rejected(mysql_app, monkeypatch):
    username = f"admin-{secrets.token_hex(6)}"
    password = secrets.token_urlsafe(24)
    monkeypatch.setenv("TECHFLOW_ADMIN_PASSWORD", password)
    runner = mysql_app.test_cli_runner()
    args = ["create-admin", "--username", username, "--full-name", "Admin kiểm thử"]
    result = runner.invoke(args=args)
    assert result.exit_code == 0, result.output
    assert password not in result.output
    user = db.session.scalar(select(User).where(User.username == username))
    assert user.role == "admin" and user.is_active
    assert user.password_hash != password and user.check_password(password)
    assert not user.check_password("incorrect")
    assert db.session.scalar(select(AuditLog.id).where(AuditLog.user_id == user.id))
    original_hash = user.password_hash
    db.session.commit()  # End read transaction before invoking another CLI transaction.
    duplicate = runner.invoke(args=args)
    assert duplicate.exit_code == 1
    assert password not in duplicate.output
    db.session.expire_all()
    assert user.password_hash == original_hash


def test_seed_forbidden_in_production(mysql_app):
    mysql_app.config["APP_ENV"] = "production"
    result = mysql_app.test_cli_runner().invoke(args=["seed-demo"])
    assert result.exit_code == 1 and "development/testing" in result.output


def test_failed_transaction_rolls_back_all_rows(mysql_app):
    suffix = secrets.token_hex(6)
    db.session.add(Category(code=f"ROLL-{suffix}", name=f"Rollback {suffix}"))
    db.session.flush()
    db.session.add(Product(sku=f"ROLL-{suffix}", name="Invalid FK", category_id=999999999999,
                           purchase_price=0, selling_price=0))
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()
    assert db.session.scalar(select(Category.id).where(Category.code == f"ROLL-{suffix}")) is None


@pytest.mark.parametrize("field,value", [("username", "bad@name"), ("full-name", " "),
                                        ("email", "invalid"), ("password", "short")])
def test_admin_validation_rejects_invalid_input(mysql_app, monkeypatch, field, value):
    username = f"valid-{secrets.token_hex(6)}"
    fields = {"username": username, "full-name": "Admin kiểm thử", "email": "test@example.invalid"}
    password = secrets.token_urlsafe(24)
    if field == "password":
        password = value
    else:
        fields[field] = value
    monkeypatch.setenv("TECHFLOW_ADMIN_PASSWORD", password)
    args = ["create-admin"]
    for key, item in fields.items():
        args.extend([f"--{key}", item])
    result = mysql_app.test_cli_runner().invoke(args=args)
    assert result.exit_code == 1
    assert password not in result.output
    assert db.session.scalar(select(User.id).where(User.username == fields["username"])) is None


def test_admin_hidden_password_prompt(mysql_app, monkeypatch):
    monkeypatch.delenv("TECHFLOW_ADMIN_PASSWORD", raising=False)
    password = secrets.token_urlsafe(24)
    username = f"prompt-{secrets.token_hex(6)}"
    result = mysql_app.test_cli_runner().invoke(
        args=["create-admin", "--username", username, "--full-name", "Admin prompt"],
        input=f"{password}\n{password}\n",
    )
    assert result.exit_code == 0, result.output
    assert password not in result.output
    assert db.session.scalar(select(User).where(User.username == username)).check_password(password)


def test_probe_survives_repeated_upgrade_and_schema_check(mysql_app):
    from flask_migrate import upgrade
    marker = secrets.token_hex(16)
    probe_id = secrets.randbelow(2_000_000_000) + 1
    with db.engine.begin() as connection:
        connection.execute(text("CREATE TABLE IF NOT EXISTS stage1_probe (id INT PRIMARY KEY, marker VARCHAR(50)) ENGINE=InnoDB"))
        connection.execute(text("INSERT INTO stage1_probe (id, marker) VALUES (:id, :marker)"), {"id": probe_id, "marker": marker})
    upgrade()
    with db.engine.connect() as connection:
        context = MigrationContext.configure(connection, opts={"include_object": include_object})
        assert compare_metadata(context, db.metadata) == []
        assert connection.execute(text("SELECT marker FROM stage1_probe WHERE id=:id"), {"id": probe_id}).scalar_one() == marker
