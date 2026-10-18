"""Warranty writes share the sales-order lock; no warranty operation changes stock."""
import calendar
import re
import secrets
from datetime import date, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select, or_
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.extensions import db
from app.models import (SalesOrder, SalesOrderItem, Product, Customer, User,
    WarrantyCoverage, WarrantyDevice, WarrantyTicket, WarrantyEvent)
from app.models.base import utc_now
from app.services.inventory_service import InventoryError, actor_for, audit, quantity

STATES = {'received':'Tiếp nhận', 'processing':'Đang xử lý', 'completed':'Hoàn thành',
          'rejected':'Từ chối', 'returned':'Đã trả khách'}
NEXT = {'received':{'processing','rejected'}, 'processing':{'completed','rejected'},
        'completed':{'returned'}, 'rejected':{'returned'}, 'returned':set()}


def local_day(value=None):
    return (value or utc_now()).replace(tzinfo=timezone.utc).astimezone(ZoneInfo('Asia/Ho_Chi_Minh')).date()


def expiry(start, months):
    if not isinstance(months, int) or isinstance(months, bool) or not 1 <= months <= 120:
        raise InventoryError('Thời hạn bảo hành phải từ 1 đến 120 tháng.',422)
    year, month = divmod(start.year * 12 + start.month - 1 + months, 12)
    try:
        return date(year, month+1, min(start.day, calendar.monthrange(year,month+1)[1]))
    except (ValueError, OverflowError):
        raise InventoryError('Ngày bảo hành vượt giới hạn.',422) from None


def coverage_state(coverage, on=None):
    if coverage is None: return 'Chưa xác định chính sách'
    if not coverage.enabled: return 'Không bảo hành'
    if not coverage.starts_on or not coverage.expires_on: return 'Chưa kích hoạt'
    day = on or local_day()
    if day < coverage.starts_on: return 'Chưa đến hạn'
    return 'Còn hạn' if day <= coverage.expires_on else 'Hết hạn'


def eligible(coverage, day):
    return coverage_state(coverage,day) == 'Còn hạn'


def serial_number(value):
    value = (value or '').strip().upper()
    if value and not re.fullmatch(r'[A-Z0-9][A-Z0-9._/-]{0,99}',value):
        raise InventoryError('Serial/IMEI tối đa 100 ký tự: chữ không dấu, số, . _ / -.',422)
    return value or None


def text_value(value, maximum, required=False):
    value = (value or '').strip()
    if (required and not value) or len(value)>maximum:
        raise InventoryError(f'Vui lòng nhập nội dung hợp lệ, tối đa {maximum} ký tự.',422)
    return value or None


def new_ticket_code():
    return 'BH-'+utc_now().strftime('%Y%m%d')+'-'+secrets.token_hex(8).upper()


def can_handle(actor, ticket):
    return actor.role == 'admin' or actor.has_permission('warranty') and actor.id in (ticket.created_by,ticket.assigned_to)


def ticket_scope(actor):
    query = select(WarrantyTicket)
    return query if actor.role=='admin' else query.where(or_(WarrantyTicket.created_by==actor.id,WarrantyTicket.assigned_to==actor.id))


def lock_sale(session, item_id):
    # Read only the immutable parent FK, then acquire the shared first lock.
    order_id = session.scalar(select(SalesOrderItem.order_id).where(SalesOrderItem.id==item_id))
    order = session.scalar(select(SalesOrder).where(SalesOrder.id==order_id).with_for_update()) if order_id else None
    if not order or order.status!='completed':
        raise InventoryError('Chỉ tiếp nhận từ đơn bán đã hoàn thành và chưa bị hủy.',422)
    item = session.get(SalesOrderItem,item_id)
    return order,item


def record_event(session,actor,ticket,action,previous=None,note=None):
    session.add(WarrantyEvent(ticket_id=ticket.id,actor_id=actor.id,action=action,
        from_status=previous,to_status=ticket.status,note=note))
    audit(session,actor.id,action,'warranty_tickets',ticket.id)


def verify_legacy(actor_id,item_id,start,months,reason,notes=None):
    try:
        with Session(db.engine) as session, session.begin():
            actor=actor_for(session,actor_id,'warranty')
            if actor.role!='admin': raise InventoryError('Chỉ Admin được xác minh chính sách đơn cũ.',403)
            order,item=lock_sale(session,item_id)
            if session.scalar(select(WarrantyCoverage.id).where(WarrantyCoverage.sale_item_id==item_id).with_for_update()):
                raise InventoryError('Dòng đơn đã có chính sách snapshot; không được ghi đè.')
            if not isinstance(start,date) or start>local_day(): raise InventoryError('Ngày bắt đầu phải hợp lệ và không ở tương lai.',422)
            coverage=WarrantyCoverage(sale_item_id=item.id,enabled=True,months=months,starts_on=start,
                expires_on=expiry(start,months),source='legacy_verified',verified_by=actor.id,
                verification_reason=text_value(reason,1000,True),notes=text_value(notes,2000))
            session.add(coverage);session.flush()
            audit(session,actor.id,'verify_legacy_warranty','warranty_coverages',coverage.id)
            return coverage.id
    except InventoryError: raise
    except SQLAlchemyError:
        raise InventoryError('Chưa thể lưu xác minh; tải lại trạng thái trước khi thử lại.',503) from None


def create_ticket(actor_id,item_id,unit_index,serial,issue,promised_on=None,code=None):
    unit_index=quantity(unit_index); serial=serial_number(serial)
    issue=text_value(issue,2000,True); today=local_day()
    if promised_on and (not isinstance(promised_on,date) or promised_on<today):
        raise InventoryError('Ngày hẹn trả không được trước ngày nhận.',422)
    try:
        with Session(db.engine) as session, session.begin():
            actor=actor_for(session,actor_id,'warranty')
            order,item=lock_sale(session,item_id)
            if unit_index>item.quantity: raise InventoryError('Vị trí thiết bị vượt số lượng đã mua.',422)
            coverage=session.scalar(select(WarrantyCoverage).where(WarrantyCoverage.sale_item_id==item_id).with_for_update())
            if not coverage: raise InventoryError('Đơn cũ chưa xác định chính sách. Cần Admin xác minh trước khi lập phiếu.',422)
            device=session.scalar(select(WarrantyDevice).where(WarrantyDevice.coverage_id==coverage.id,
                WarrantyDevice.unit_index==unit_index).with_for_update())
            if not device:
                device=WarrantyDevice(coverage_id=coverage.id,unit_index=unit_index,serial=serial)
                session.add(device);session.flush()
            elif serial and device.serial and serial!=device.serial:
                raise InventoryError('Thiết bị đã gắn serial khác. Kiểm tra đúng máy trước khi tiếp nhận.',422)
            elif serial and not device.serial:
                device.serial=serial
            if session.scalar(select(WarrantyTicket.id).where(WarrantyTicket.device_id==device.id,
                    WarrantyTicket.status!='returned').with_for_update()):
                raise InventoryError('Thiết bị đang có phiếu chưa trả khách. Không thể mở phiếu đồng thời.')
            product=session.get(Product,item.product_id)
            ticket=WarrantyTicket(ticket_code=code or new_ticket_code(),device_id=device.id,
                customer_id=order.customer_id,customer_name=order.customer_name,customer_phone=order.customer_phone,
                product_name=product.name,product_sku=product.sku,created_by=actor.id,assigned_to=actor.id,
                issue=issue,received_on=today,promised_on=promised_on,status='received',assessment='pending')
            session.add(ticket);session.flush()
            record_event(session,actor,ticket,'receive')
            return ticket.id
    except InventoryError: raise
    except IntegrityError:
        raise InventoryError('Serial/IMEI đã gắn thiết bị khác hoặc phiếu đã được gửi. Hãy kiểm tra trước khi thử lại.') from None
    except SQLAlchemyError:
        raise InventoryError('Chưa thể xác nhận lưu phiếu; tải lại danh sách trước khi thử lại.',503) from None


def handle_ticket(actor_id,ticket_id,target,expected_status,result=None,reason=None,note=None,assignee=None):
    result=text_value(result,2000);reason=text_value(reason,1000);note=text_value(note,2000)
    try:
        with Session(db.engine) as session, session.begin():
            actor=actor_for(session,actor_id,'warranty')
            # Order -> coverage -> device -> ticket, consistent with receive/cancel.
            parent=session.execute(select(WarrantyTicket.device_id,WarrantyDevice.coverage_id,WarrantyCoverage.sale_item_id)
                .join(WarrantyDevice,WarrantyDevice.id==WarrantyTicket.device_id)
                .join(WarrantyCoverage,WarrantyCoverage.id==WarrantyDevice.coverage_id).where(WarrantyTicket.id==ticket_id)).first()
            if not parent: raise InventoryError('Không tìm thấy phiếu.',404)
            order_id=session.scalar(select(SalesOrderItem.order_id).where(SalesOrderItem.id==parent.sale_item_id))
            order=session.scalar(select(SalesOrder).where(SalesOrder.id==order_id).with_for_update())
            coverage=session.scalar(select(WarrantyCoverage).where(WarrantyCoverage.id==parent.coverage_id).with_for_update())
            session.scalar(select(WarrantyDevice).where(WarrantyDevice.id==parent.device_id).with_for_update())
            ticket=session.scalar(select(WarrantyTicket).where(WarrantyTicket.id==ticket_id).with_for_update())
            if not can_handle(actor,ticket): raise InventoryError('Không tìm thấy phiếu trong phạm vi được phép.',404)
            if ticket.status!=expected_status: raise InventoryError('Phiếu đã thay đổi. Tải lại trước khi thao tác.')
            previous=ticket.status
            if target=='assign':
                if actor.role!='admin': raise InventoryError('Chỉ Admin được phân công xử lý.',403)
                if ticket.status=='returned': raise InventoryError('Phiếu đã trả khách không thể phân công lại.')
                user=session.get(User,quantity(assignee))
                if not user or not user.has_permission('warranty'): raise InventoryError('Người phụ trách chưa có quyền bảo hành.',422)
                if user.id==ticket.assigned_to: raise InventoryError('Phiếu đã được phân công cho tài khoản này.')
                ticket.assigned_to=user.id
                note=f'Phân công xử lý cho tài khoản #{user.id}.'
            else:
                if target not in NEXT.get(previous,set()): raise InventoryError('Không được chuyển trạng thái này hoặc xử lý lặp.')
                if target in {'processing','completed','rejected'} and not result:
                    raise InventoryError('Cần ghi kết quả kiểm tra trước khi quyết định.',422)
                if target=='processing':
                    if order.status!='completed' or not eligible(coverage,ticket.received_on):
                        raise InventoryError('Không đủ điều kiện thời hạn/chính sách để chấp nhận. Ghi lý do từ chối.',422)
                    ticket.assessment='accepted'
                if target=='rejected':
                    if not reason: raise InventoryError('Vui lòng ghi rõ lý do từ chối.',422)
                    ticket.assessment='rejected';ticket.rejection_reason=reason
                if result: ticket.inspection_result=result
                if target in {'completed','rejected'}: ticket.completed_at=utc_now()
                if target=='returned': ticket.returned_at=utc_now()
                ticket.status=target
            record_event(session,actor,ticket,target,previous,note or result)
    except InventoryError: raise
    except SQLAlchemyError:
        raise InventoryError('Chưa thể xác nhận xử lý; tải lại phiếu trước khi thử lại.',503) from None


def lookup_query(term):
    # Consulting projection deliberately excludes order notes, audit, address and totals.
    query=select(SalesOrderItem,WarrantyCoverage).join(SalesOrder).join(Product,Product.id==SalesOrderItem.product_id)
    query=query.outerjoin(Customer,Customer.id==SalesOrder.customer_id).outerjoin(WarrantyCoverage,WarrantyCoverage.sale_item_id==SalesOrderItem.id)
    serial_match=select(WarrantyDevice.id).where(WarrantyDevice.coverage_id==WarrantyCoverage.id,
        WarrantyDevice.serial.contains(term.upper(),autoescape=True)).exists()
    fields=[SalesOrder.customer_name,SalesOrder.customer_phone,SalesOrder.order_code,Product.sku,Product.name,Customer.name,Customer.phone]
    conditions=[f.contains(term,autoescape=True) for f in fields]
    # Normalize a plausible phone query, but never infer customer linkage.
    from app.services.customer_service import normalize_phone
    try:
        phone=normalize_phone(term)
        variants=[phone,phone[1:],'0'+phone[3:]]
        conditions.extend([SalesOrder.customer_phone.in_(variants),Customer.phone==phone])
    except InventoryError: pass
    return query.where(SalesOrder.status=='completed',or_(*conditions,serial_match)).order_by(SalesOrderItem.id.desc())
