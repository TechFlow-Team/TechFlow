"""Create a customer order as a draft; staff confirmation remains responsible for stock movement."""
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.extensions import db
from app.models import AuditLog, Customer, Product, SalesOrder, SalesOrderItem, User, WarrantyCoverage, OrderEvent
from app.models.base import utc_now
from app.services.inventory_service import InventoryError, lock_products, money, quantity
from app.services.transaction_service import new_code

MAX_PRODUCT_ID = 18446744073709551615


def _product_id(value):
    raw = str(value)
    if not raw.isascii() or not raw.isdigit() or len(raw) > 20 or not 1 <= int(raw) <= MAX_PRODUCT_ID:
        raise InventoryError("Giỏ hàng không hợp lệ.", 422)
    return int(raw)


def place_client_order(user_id: int, cart: dict) -> int:
    if not cart or len(cart) > 20:
        raise InventoryError("Giỏ hàng trống hoặc có quá nhiều mặt hàng.", 422)
    try:
        ids = [_product_id(key) for key in cart]
        if len(set(ids)) != len(ids):
            raise InventoryError("Giỏ hàng không hợp lệ.", 422)
        quantities = {_product_id(key): quantity(value) for key, value in cart.items()}
        with Session(db.engine) as session, session.begin():
            user = session.scalar(select(User).where(User.id == user_id).with_for_update())
            customer = session.scalar(select(Customer).where(Customer.user_id == user_id, Customer.is_active.is_(True)).with_for_update())
            if not user or not user.is_active or user.role != "client" or not customer:
                raise InventoryError("Tài khoản khách hàng không còn hoạt động.", 403)
            products = lock_products(session, ids)
            order = SalesOrder(order_code=new_code("sales"), customer_name=customer.name,
                customer_phone=customer.phone, customer_email=customer.email, customer_address=customer.address,
                customer_id=customer.id, created_by=user.id, order_date=utc_now(), status="draft", total_amount=0,
                notes="Đơn đặt qua cửa hàng trực tuyến")
            session.add(order)
            session.flush()
            total = money("0")
            for product_id in ids:
                product = products.get(product_id)
                if not product or not product.is_active:
                    raise InventoryError("Một sản phẩm trong giỏ không còn được bán.", 422)
                qty = quantities[product_id]
                if qty > product.stock_quantity:
                    raise InventoryError(f"Sản phẩm {product.name} không đủ tồn kho.", 422)
                unit = money(product.selling_price)
                line_total = money(unit * qty)
                total = money(total + line_total)
                item = SalesOrderItem(order_id=order.id, product_id=product.id, quantity=qty,
                    unit_price=unit, line_total=line_total)
                session.add(item)
                session.flush()
                session.add(WarrantyCoverage(sale_item_id=item.id, enabled=product.warranty_enabled,
                    months=product.warranty_months, notes=product.warranty_notes, source="sale"))
            order.total_amount = total
            session.add(OrderEvent(order_id=order.id, actor_id=user.id, status='waiting', note='Đã nhận yêu cầu đặt hàng'))
            session.add(AuditLog(user_id=user.id, action="client_order", entity_type="sales_orders",
                entity_id=order.id, description="Đơn hàng được gửi từ storefront"))
            identifier = order.id
        return identifier
    except InventoryError:
        raise
    except IntegrityError:
        raise InventoryError("Không thể lưu đơn hàng do dữ liệu vừa thay đổi. Vui lòng tải lại giỏ hàng.", 409) from None
    except SQLAlchemyError:
        raise InventoryError("Chưa thể xác nhận kết quả đặt hàng. Kiểm tra đơn hàng trước khi thử lại.", 503) from None


def cancel_client_order(user_id: int, order_id: int) -> None:
    try:
        with Session(db.engine) as session, session.begin():
            user = session.scalar(select(User).where(User.id == user_id).with_for_update())
            order = session.scalar(select(SalesOrder).where(SalesOrder.id == order_id).with_for_update())
            if not order or order.created_by != user_id:
                raise InventoryError("Không tìm thấy đơn hàng.", 404)
            if not user or not user.is_active or user.role != "client":
                raise InventoryError("Bạn không có quyền hủy đơn này.", 403)
            if order.status != "draft" or order.fulfillment_status != 'waiting':
                raise InventoryError("Chỉ đơn đang chờ xử lý mới được hủy.", 409)
            order.status = "cancelled"
            order.fulfillment_status = 'cancelled'
            session.add(OrderEvent(order_id=order.id, actor_id=user.id, status='cancelled', note='Khách hàng hủy đơn'))
            session.add(AuditLog(user_id=user.id, action="client_cancel", entity_type="sales_orders",
                entity_id=order.id, description="Khách hủy đơn trước khi xử lý"))
    except InventoryError:
        raise
    except SQLAlchemyError:
        raise InventoryError("Chưa thể hủy đơn. Tải lại trạng thái rồi thử lại.", 503) from None
