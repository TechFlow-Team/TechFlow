import secrets
import os

import pytest

from app import create_app


@pytest.fixture
def configured_env(monkeypatch):
    monkeypatch.setenv("APP_ENV", "testing")
    monkeypatch.setenv("SECRET_KEY", secrets.token_hex(32))
    monkeypatch.setenv("MYSQL_USER", "test_user")
    monkeypatch.setenv("MYSQL_PASSWORD", secrets.token_urlsafe(24))
    monkeypatch.setenv("MYSQL_DATABASE", "techflow_test")
    monkeypatch.setenv("DB_HOST", "127.0.0.1")
    monkeypatch.setenv("DB_PORT", "3306")
    monkeypatch.setenv("SESSION_COOKIE_SECURE", "false")
    monkeypatch.setenv("LOG_LEVEL", "INFO")
    monkeypatch.delenv("DATABASE_URL", raising=False)


@pytest.fixture
def app(configured_env):
    application = create_app()
    yield application
    from app.extensions import db
    with application.app_context():
        db.session.remove()
        db.engine.dispose()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def mysql_app(configured_env, monkeypatch):
    if os.getenv("RUN_MYSQL_TESTS") != "1":
        pytest.skip("MySQL integration tests require the isolated Docker runner.")
    # Hardcoded isolated host/name/user: never accept a development DATABASE_URL.
    monkeypatch.setenv("DB_HOST", "db-test")
    monkeypatch.setenv("MYSQL_DATABASE", "techflow_test")
    monkeypatch.setenv("MYSQL_USER", "techflow_test_user")
    monkeypatch.setenv("MYSQL_PASSWORD", os.environ["TEST_MYSQL_PASSWORD"])
    application = create_app()
    from app.extensions import db
    with application.app_context():
        assert db.engine.url.database == "techflow_test"
        assert db.engine.url.host == "db-test"
        yield application
        db.session.remove()
        db.engine.dispose()


@pytest.fixture
def catalog(mysql_app):
    from decimal import Decimal
    from app.extensions import db
    from app.models import Business, Category, Product, User
    suffix = secrets.token_hex(6)
    user = User(username=f"test-{suffix}", full_name="Người dùng kiểm thử", role="staff", task_groups='inventory,orders,warranty')
    user.set_password(secrets.token_urlsafe(24))
    category = Category(code=f"TEST-{suffix}", name=f"Danh mục test {suffix}")
    business = Business(code=f"TEST-{suffix}", name="Nhà cung cấp kiểm thử")
    db.session.add_all([user, category, business])
    db.session.flush()
    product = Product(sku=f"TEST-{suffix}", name="SSD kiểm thử", category=category,
                      business=business, purchase_price=Decimal("1234.56"),
                      selling_price=Decimal("2345.67"))
    db.session.add(product)
    db.session.commit()
    return {"user_id": user.id, "category_id": category.id, "business_id": business.id,
            "product_id": product.id, "sku": product.sku, "suffix": suffix}
