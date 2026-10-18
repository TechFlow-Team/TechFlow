"""Shared receipt/order state machine. One fresh Session owns each atomic write."""
import secrets

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError, IntegrityError
from sqlalchemy.orm import Session

from app.extensions import db
from app.models import Business, PurchaseReceipt, PurchaseReceiptItem, SalesOrder, SalesOrderItem
from app.models.base import utc_now
from app.services.inventory_service import (InventoryError, actor_for, audit, change_stock,
    lock_products, money, quantity)
from app.models import Customer
from app.services.customer_service import insert_customer, DuplicateCustomer

MODELS = {'purchases': (PurchaseReceipt, PurchaseReceiptItem, 'receipt_code', 'receipt_id'),
          'sales': (SalesOrder, SalesOrderItem, 'order_code', 'order_id')}


def new_code(kind):
    return ('PN' if kind == 'purchases' else 'SO') + '-' + utc_now().strftime('%Y%m%d') + '-' + secrets.token_hex(8).upper()


def permitted(actor, kind, document=None, action='view'):
    if actor.role == 'admin':
        return True
    if actor.role == 'staff':
        if not actor.has_permission('orders'):
            return False
        if kind != 'sales':
            return False
        if document is None:
            return True
        creator_role = document.creator.role if document.creator else None
        return (document.created_by == actor.id or creator_role == 'client') and not (
            action == 'cancel' and document is not None and document.status == 'completed')
    return (kind == 'sales' and (document is None or document.created_by == actor.id)
            and not (action == 'cancel' and document is not None and document.status == 'completed'))


def checked_kind(kind):
    if kind not in MODELS:
        raise InventoryError('Loại giao dịch không hợp lệ.', 404)
    return MODELS[kind]


def create_document(kind, actor_id, header, lines, code=None):
    model, item_model, code_field, parent_field = checked_kind(kind)
    # Repeated product rows are rejected rather than silently changing quantity.
    if not 1 <= len(lines) <= 50:
        raise InventoryError('Phiếu cần từ 1 đến 50 dòng sản phẩm.', 422)
    try:
        ids = [quantity(line['product_id']) for line in lines]
    except (KeyError, TypeError):
        raise InventoryError('Dòng sản phẩm không hợp lệ.', 422) from None
    if len(set(ids)) != len(ids):
        raise InventoryError('Mỗi sản phẩm chỉ được xuất hiện một lần. Hãy gộp số lượng.', 422)
    try:
        with Session(db.engine) as session, session.begin():
            actor = actor_for(session, actor_id)
            if not permitted(actor, kind):
                raise InventoryError('Bạn không có quyền tạo phiếu nhập.', 403)
            values = {code_field: code or new_code(kind), 'created_by': actor_id, 'status': 'draft',
                      'notes': (header.get('notes') or '').strip() or None}
            if values['notes'] and len(values['notes']) > 2000:
                raise InventoryError('Ghi chú tối đa 2000 ký tự.', 422)
            if kind == 'purchases':
                supplier_id = quantity(header.get('business_id', ''))
                supplier = session.scalar(select(Business).where(Business.id == supplier_id).with_for_update())
                if not supplier or not supplier.is_active:
                    raise InventoryError('Nhà cung cấp phải đang hoạt động.', 422)
                values.update(business_id=supplier_id, receipt_date=utc_now())
            else:
                mode = header.get('customer_mode') or 'walkin'
                customer = None
                if mode == 'existing':
                    customer_id = quantity(header.get('customer_id',''))
                    customer = session.scalar(select(Customer).where(Customer.id == customer_id).with_for_update())
                    if not customer or not customer.is_active:
                        raise InventoryError('Hồ sơ khách không tồn tại hoặc đã ngừng hoạt động. Vui lòng chọn lại.',422)
                elif mode == 'new':
                    customer = insert_customer(session,actor,dict(name=header.get('customer_name'),
                        phone=header.get('customer_phone'),email=header.get('customer_email'),address=header.get('customer_address')))
                elif mode != 'walkin':
                    raise InventoryError('Lựa chọn khách hàng không hợp lệ.',422)
                # Explicit walk-in never attaches a matching phone automatically.
                if customer:
                    header = dict(header,customer_name=customer.name,customer_phone=customer.phone,
                                  customer_email=customer.email,customer_address=customer.address)
                    values['customer_id'] = customer.id
                for field, limit in [('customer_name',150),('customer_phone',30),('customer_email',190),('customer_address',255)]:
                    value = (header.get(field) or '').strip()
                    if len(value) > limit or (field == 'customer_name' and not value):
                        raise InventoryError('Thông tin khách hàng không hợp lệ.', 422)
                    values[field] = value or None
                values['order_date'] = utc_now()
            products = lock_products(session, ids)
            document = model(**values)
            session.add(document)
            session.flush()
            total = money('0')
            for line, product_id in zip(lines, ids):
                product = products[product_id]
                if not product.is_active:
                    raise InventoryError('Không thể tạo giao dịch với sản phẩm ngừng hoạt động.', 422)
                qty = quantity(line.get('quantity', ''))
                unit = money(line.get('unit_cost', '')) if kind == 'purchases' else money(product.selling_price)
                if kind == 'sales' and qty > product.stock_quantity:
                    raise InventoryError(f'Sản phẩm {product.sku} không đủ tồn kho.')
                line_total = money(unit * qty)
                total = money(total + line_total)
                item = item_model(**{parent_field: document.id, 'product_id': product_id,
                    'quantity': qty, 'unit_cost' if kind == 'purchases' else 'unit_price': unit, 'line_total': line_total})
                session.add(item)
                if kind == 'sales':
                    from app.models import WarrantyCoverage
                    session.flush()
                    session.add(WarrantyCoverage(sale_item_id=item.id, enabled=product.warranty_enabled,
                        months=product.warranty_months, notes=product.warranty_notes, source='sale'))
            document.total_amount = total
            if kind == 'sales':
                from app.models import OrderEvent
                session.add(OrderEvent(order_id=document.id, actor_id=actor_id, status='waiting', note='Tạo đơn hàng'))
            audit(session, actor_id, 'create_draft', model.__tablename__, document.id)
            identifier = document.id
        return identifier
    except InventoryError:
        raise
    except IntegrityError as error:
        if 'uq_customers_phone' in str(error.orig):
            raise DuplicateCustomer() from None
        raise InventoryError('Phiếu đã được gửi hoặc dữ liệu đã thay đổi. Kiểm tra danh sách trước khi tạo lại.') from None
    except SQLAlchemyError:
        raise InventoryError('Chưa thể xác nhận kết quả lưu. Kiểm tra danh sách trước khi thử lại.', 503) from None


def transition(kind, actor_id, identifier, action, note=None):
    model, item_model, _, parent_field = checked_kind(kind)
    if action not in ({'complete', 'cancel', 'confirm', 'ship', 'reject', 'note'} if kind == 'sales' else {'complete', 'cancel'}):
        raise InventoryError('Thao tác không hợp lệ.', 400)
    note = (note or '').strip()
    if len(note) > 1000:
        raise InventoryError('Ghi chú tối đa 1000 ký tự.', 422)
    try:
        with Session(db.engine) as session, session.begin():
            actor = actor_for(session, actor_id)
            document = session.scalar(select(model).where(model.id == identifier).with_for_update())
            if not document:
                raise InventoryError('Không tìm thấy giao dịch.', 404)
            if not permitted(actor, kind, document, action):
                raise InventoryError('Bạn không có quyền thực hiện thao tác này.', 403)
            if kind == 'sales' and action == 'note':
                from app.models import OrderEvent
                if not note:
                    raise InventoryError('Vui lòng nhập ghi chú.', 422)
                session.add(OrderEvent(order_id=document.id, actor_id=actor.id, status=document.fulfillment_status, note=note))
                audit(session, actor.id, 'order_note', model.__tablename__, identifier)
                return
            if kind == 'sales' and action in {'confirm', 'ship', 'reject'}:
                from app.models import OrderEvent
                allowed = {'confirm': {'waiting'}, 'ship': {'confirmed'}, 'reject': {'waiting', 'confirmed'}}
                if document.status != 'draft' or document.fulfillment_status not in allowed[action]:
                    raise InventoryError('Trạng thái đơn đã thay đổi; hãy tải lại.')
                document.fulfillment_status = {'confirm': 'confirmed', 'ship': 'shipping', 'reject': 'rejected'}[action]
                if action == 'reject':
                    document.status = 'cancelled'
                session.add(OrderEvent(order_id=document.id, actor_id=actor.id, status=document.fulfillment_status, note=note or None))
                audit(session, actor.id, action, model.__tablename__, identifier)
                return
            if document.status not in {'draft', 'completed'} or (action == 'complete' and document.status != 'draft'):
                raise InventoryError('Trạng thái giao dịch đã thay đổi; không thể xử lý lại.')
            if kind == 'sales' and action == 'complete' and document.creator.role == 'client' and document.fulfillment_status != 'shipping':
                raise InventoryError('Đơn trực tuyến cần được xác nhận và giao trước khi hoàn tất.')
            items = session.scalars(select(item_model).where(getattr(item_model, parent_field) == identifier).order_by(item_model.product_id)).all()
            if not items:
                raise InventoryError('Giao dịch không có dòng sản phẩm hợp lệ.')
            if kind == 'sales':
                from app.models import WarrantyCoverage, WarrantyDevice, WarrantyTicket
                from app.services.warranty_service import expiry, local_day
                if action == 'cancel' and document.status == 'completed':
                    opened = session.scalar(select(WarrantyTicket.id).join(WarrantyDevice).join(WarrantyCoverage)
                        .where(WarrantyCoverage.sale_item_id.in_([i.id for i in items]),
                               WarrantyTicket.status != 'returned').limit(1).with_for_update())
                    if opened:
                        raise InventoryError('Đơn còn phiếu bảo hành chưa trả khách. Kết thúc bảo hành trước khi hủy đơn.')
                if action == 'complete':
                    document.completed_at = utc_now()
                    for coverage in session.scalars(select(WarrantyCoverage).where(
                            WarrantyCoverage.sale_item_id.in_([i.id for i in items])).with_for_update()):
                        if coverage.enabled:
                            coverage.starts_on = local_day(document.completed_at)
                            coverage.expires_on = expiry(coverage.starts_on, coverage.months)
            if action == 'complete' or document.status == 'completed':
                products = lock_products(session, [item.product_id for item in items])
                if action == 'complete' and kind == 'purchases':
                    supplier = session.get(Business, document.business_id)
                    if not supplier or not supplier.is_active:
                        raise InventoryError('Nhà cung cấp đã ngừng hoạt động.')
                for item in items:
                    product = products[item.product_id]
                    if action == 'complete' and not product.is_active:
                        raise InventoryError('Sản phẩm đã ngừng hoạt động; hãy hủy phiếu draft.')
                    qty = quantity(item.quantity)
                    if kind == 'purchases':
                        delta, movement = (qty, 'purchase_in') if action == 'complete' else (-qty, 'adjustment')
                    else:
                        delta, movement = (-qty, 'sale_out') if action == 'complete' else (qty, 'sale_return')
                    change_stock(session, product, delta, movement,
                        'purchase_receipt' if kind == 'purchases' else 'sales_order', identifier, actor_id,
                        'Đảo kho do hủy phiếu nhập' if kind == 'purchases' and action == 'cancel' else None)
            document.status = 'completed' if action == 'complete' else 'cancelled'
            if kind == 'sales':
                from app.models import OrderEvent
                document.fulfillment_status = document.status
                session.add(OrderEvent(order_id=document.id, actor_id=actor.id, status=document.status, note=note or None))
            audit(session, actor_id, action, model.__tablename__, identifier)
    except InventoryError:
        raise
    except SQLAlchemyError:
        raise InventoryError('Chưa thể xác nhận kết quả xử lý. Vui lòng tải lại trạng thái trước khi thử lại.', 503) from None
