"""Transactional stock primitives; callers own the transaction and row locks."""
from decimal import Decimal, InvalidOperation

from sqlalchemy import select

from app.models import AuditLog, Product, StockMovement, User

MAX_MONEY = Decimal('999999999999.99')
MAX_QUANTITY = 2147483647  # signed movement delta
MAX_STOCK = 4294967295


class InventoryError(Exception):
    def __init__(self, message, status=409):
        self.message, self.status = message, status
        super().__init__(message)


def actor_for(session, actor_id, permission=None):
    actor = session.get(User, actor_id)
    if not actor or not actor.is_active or actor.role not in {'admin', 'staff'}:
        raise InventoryError('Bạn không có quyền thực hiện thao tác này.', 403)
    if permission and not actor.has_permission(permission):
        raise InventoryError('Bạn chưa được cấp nhóm quyền này.', 403)
    return actor


def quantity(value):
    raw = str(value)
    if not raw.isascii() or not raw.isdigit() or len(raw) > 10 or not 1 <= int(raw) <= MAX_QUANTITY:
        raise InventoryError('Số lượng phải là số nguyên dương hợp lệ.', 422)
    return int(raw)


def money(value):
    if isinstance(value, (float, bool)):
        raise InventoryError('Đơn giá không hợp lệ.', 422)
    try:
        result = Decimal(value)
        if not result.is_finite() or result < 0 or result > MAX_MONEY or result != result.quantize(Decimal('.01')):
            raise ValueError
        return result.quantize(Decimal('.01'))
    except (InvalidOperation, ValueError, TypeError):
        raise InventoryError('Đơn giá phải không âm, tối đa 2 chữ số thập phân và nằm trong giới hạn.', 422) from None


def lock_products(session, ids):
    # Every inventory operation locks products by ascending PK, after the document.
    records = {}
    for identifier in sorted(set(ids)):
        product = session.scalar(select(Product).where(Product.id == identifier).with_for_update())
        if not product:
            raise InventoryError('Sản phẩm không còn tồn tại.', 422)
        records[identifier] = product
    return records


def change_stock(session, product, delta, kind, reference_type, reference_id, actor_id, reason=None):
    resulting = product.stock_quantity + delta
    if resulting < 0:
        raise InventoryError(f'Sản phẩm {product.sku} không đủ tồn kho để thực hiện thao tác.')
    if resulting > MAX_STOCK:
        raise InventoryError('Tồn kho vượt giới hạn lưu trữ.')
    product.stock_quantity = resulting
    session.add(StockMovement(product_id=product.id, quantity_delta=delta, movement_type=kind,
        reference_type=reference_type, reference_id=reference_id, created_by=actor_id, reason=reason))


def audit(session, actor_id, action, entity_type, entity_id):
    # Deliberately exclude customer details, notes, tokens and credentials.
    session.add(AuditLog(user_id=actor_id, action=action, entity_type=entity_type,
        entity_id=entity_id, description='Giao dịch kho và bán hàng'))
