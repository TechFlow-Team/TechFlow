"""Warranty invariants against isolated, migrated MySQL 8 (no reset/drop)."""
import re
import secrets
from datetime import date, timedelta
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from sqlalchemy import select, func
from sqlalchemy.exc import SQLAlchemyError, IntegrityError, DBAPIError

from app.extensions import db
from app.models import (Product,User,SalesOrder,SalesOrderItem,StockMovement,AuditLog,
    WarrantyCoverage,WarrantyDevice,WarrantyTicket,WarrantyEvent)
from app.services import warranty_service as service
from app.services.inventory_service import InventoryError
from test_auth import account,auth_client,csrf,login
from test_inventory import receipt,lines,create_document,transition,stock


@pytest.fixture
def sold(account,catalog):
    product=db.session.get(Product,catalog['product_id'])
    product.warranty_enabled=True;product.warranty_months=12;product.warranty_notes='Chính sách lúc bán'
    db.session.commit();receipt(account,catalog,10,True)
    oid=create_document('sales',account['id'],dict(customer_name='Khách bảo hành',customer_phone='0901234567'),lines(catalog,3))
    transition('sales',account['id'],oid,'complete')
    db.session.rollback();item=db.session.scalar(select(SalesOrderItem).where(SalesOrderItem.order_id==oid))
    coverage=db.session.scalar(select(WarrantyCoverage).where(WarrantyCoverage.sale_item_id==item.id))
    return dict(order=oid,item=item.id,coverage=coverage.id,actor=account['id'],product=catalog['product_id'])


def intake(sold,unit=1,serial=None,**kwargs):
    db.session.rollback()
    return service.create_ticket(sold['actor'],sold['item'],unit,serial,'Máy không khởi động',**kwargs)


def action(sold,tid,target,expected,**kwargs):
    db.session.rollback()
    return service.handle_ticket(sold['actor'],tid,target,expected,result='Đã kiểm tra thiết bị',**kwargs)


@pytest.mark.parametrize('start,months,end',[
    (date(2024,1,31),1,date(2024,2,29)),(date(2025,1,31),1,date(2025,2,28)),
    (date(2024,2,29),12,date(2025,2,28)),(date(2025,12,31),2,date(2026,2,28)),
    (date(2025,10,10),12,date(2026,10,10))])
def test_calendar_expiry(start,months,end):
    assert service.expiry(start,months)==end


@pytest.mark.parametrize('months',[0,-1,121,True,1.5,'12'])
def test_invalid_months(months):
    with pytest.raises(InventoryError):service.expiry(date.today(),months)


def test_snapshot_draft_completion_and_policy_change(account,catalog):
    p=db.session.get(Product,catalog['product_id']);p.warranty_enabled=True;p.warranty_months=6;p.warranty_notes='Snapshot'
    db.session.commit();receipt(account,catalog,5,True)
    oid=create_document('sales',account['id'],dict(customer_name='Snapshot customer'),lines(catalog,1))
    db.session.rollback();item=db.session.scalar(select(SalesOrderItem).where(SalesOrderItem.order_id==oid))
    cov=db.session.scalar(select(WarrantyCoverage).where(WarrantyCoverage.sale_item_id==item.id))
    assert cov.months==6 and cov.starts_on is None and db.session.get(SalesOrder,oid).completed_at is None
    p=db.session.get(Product,catalog['product_id']);p.warranty_months=24;p.warranty_notes='Changed';db.session.commit()
    transition('sales',account['id'],oid,'complete');db.session.rollback()
    cov=db.session.get(WarrantyCoverage,cov.id)
    assert cov.months==6 and cov.notes=='Snapshot'
    assert cov.starts_on==service.local_day(db.session.get(SalesOrder,oid).completed_at)
    assert cov.expires_on==service.expiry(cov.starts_on,6)
    with pytest.raises(InventoryError):transition('sales',account['id'],oid,'complete')


def test_boundary_and_inactive_product(sold):
    cov=db.session.get(WarrantyCoverage,sold['coverage'])
    assert service.coverage_state(cov,cov.expires_on)=='Còn hạn'
    assert service.coverage_state(cov,cov.expires_on+timedelta(days=1))=='Hết hạn'
    assert service.coverage_state(cov,cov.starts_on-timedelta(days=1))=='Chưa đến hạn'
    db.session.get(Product,sold['product']).is_active=False;db.session.commit()
    tid=intake(sold);action(sold,tid,'processing','received')


def test_complete_lifecycle_does_not_touch_stock(sold,catalog):
    original_stock=stock(catalog)
    count=db.session.scalar(select(func.count()).select_from(StockMovement).where(StockMovement.product_id==sold['product']))
    tid=intake(sold,serial='sn-'+secrets.token_hex(6))
    action(sold,tid,'processing','received');action(sold,tid,'completed','processing');action(sold,tid,'returned','completed')
    with pytest.raises(InventoryError):action(sold,tid,'returned','completed')
    db.session.rollback();ticket=db.session.get(WarrantyTicket,tid)
    assert ticket.status=='returned' and ticket.assessment=='accepted' and ticket.completed_at and ticket.returned_at
    assert ticket.open_device_key is None and ticket.customer_id is None
    assert stock(catalog)==original_stock
    assert db.session.scalar(select(func.count()).select_from(StockMovement).where(StockMovement.product_id==sold['product']))==count
    assert db.session.scalars(select(WarrantyEvent.action).where(WarrantyEvent.ticket_id==tid).order_by(WarrantyEvent.id)).all()==['receive','processing','completed','returned']
    audits=db.session.scalars(select(AuditLog).where(AuditLog.entity_type=='warranty_tickets',AuditLog.entity_id==tid)).all()
    assert len(audits)==4 and all('Máy không' not in (a.description or '') for a in audits)
    again=intake(sold);assert again!=tid


def test_disabled_requires_reasoned_rejection(account,catalog):
    receipt(account,catalog,5,True)
    oid=create_document('sales',account['id'],dict(customer_name='No warranty'),lines(catalog,1));transition('sales',account['id'],oid,'complete')
    db.session.rollback();item=db.session.scalar(select(SalesOrderItem).where(SalesOrderItem.order_id==oid))
    fixture=dict(actor=account['id'],item=item.id)
    tid=intake(fixture)
    with pytest.raises(InventoryError):action(fixture,tid,'processing','received')
    with pytest.raises(InventoryError):action(fixture,tid,'rejected','received')
    action(fixture,tid,'rejected','received',reason='Sản phẩm không có chính sách bảo hành')
    action(fixture,tid,'returned','rejected')
    db.session.rollback();assert db.session.get(WarrantyTicket,tid).rejection_reason


def test_expired_received_cannot_be_accepted(sold):
    cov=db.session.get(WarrantyCoverage,sold['coverage']);cov.starts_on=date(2020,1,1);cov.expires_on=date(2021,1,1);db.session.commit()
    tid=intake(sold)
    with pytest.raises(InventoryError):action(sold,tid,'processing','received')
    action(sold,tid,'rejected','received',reason='Đã hết hạn')


def test_units_serial_and_open_ticket(sold):
    serial='IMEI'+secrets.token_hex(6)
    first=intake(sold,1,serial)
    with pytest.raises(InventoryError):intake(sold,1)
    with pytest.raises(InventoryError):intake(sold,1,'WRONG-SERIAL')
    with pytest.raises(InventoryError):intake(sold,2,serial.lower())
    second=intake(sold,2);assert second!=first
    with pytest.raises(InventoryError):intake(sold,4)
    with pytest.raises(InventoryError):intake(sold,0)


@pytest.mark.parametrize('value',['a b','<script>','IMEI:123','x'*101,'中文'])
def test_invalid_serial(value):
    with pytest.raises(InventoryError):service.serial_number(value)


def test_mysql_enforces_open_unit_uniqueness(sold):
    tid=intake(sold);db.session.rollback();ticket=db.session.get(WarrantyTicket,tid)
    db.session.add(WarrantyTicket(ticket_code=service.new_ticket_code(),device_id=ticket.device_id,
        customer_name='Duplicate',product_name='Duplicate',product_sku='Duplicate',created_by=sold['actor'],
        received_on=ticket.received_on,issue='Duplicate'))
    with pytest.raises(IntegrityError):db.session.commit()
    db.session.rollback()


def test_cancel_sale_blocked_until_return(sold):
    tid=intake(sold)
    with pytest.raises(InventoryError):transition('sales',sold['actor'],sold['order'],'cancel')
    action(sold,tid,'rejected','received',reason='Không đáp ứng điều kiện')
    with pytest.raises(InventoryError):transition('sales',sold['actor'],sold['order'],'cancel')
    action(sold,tid,'returned','rejected');transition('sales',sold['actor'],sold['order'],'cancel')
    with pytest.raises(InventoryError):intake(sold)


def test_rollback_receive_and_transition(sold,monkeypatch):
    original=service.record_event
    def fail(session,*args,**kwargs):session.flush();raise SQLAlchemyError('injected')
    monkeypatch.setattr(service,'record_event',fail)
    with pytest.raises(InventoryError):intake(sold)
    db.session.rollback();assert not db.session.scalar(select(WarrantyDevice.id).where(WarrantyDevice.coverage_id==sold['coverage']))
    monkeypatch.setattr(service,'record_event',original);tid=intake(sold)
    monkeypatch.setattr(service,'record_event',fail)
    with pytest.raises(InventoryError):action(sold,tid,'processing','received')
    db.session.rollback();assert db.session.get(WarrantyTicket,tid).status=='received'
    assert db.session.scalar(select(func.count()).select_from(WarrantyEvent).where(WarrantyEvent.ticket_id==tid))==1


def test_concurrent_same_unit_only_once(mysql_app,sold):
    barrier=Barrier(2);db.session.rollback()
    def receive():
        with mysql_app.app_context():
            barrier.wait()
            try:service.create_ticket(sold['actor'],sold['item'],1,None,'Concurrent');return True
            except InventoryError:return False
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(lambda _:receive(),range(2)))
    assert sorted(results)==[False,True]


def test_concurrent_serial_across_units(mysql_app,sold):
    barrier=Barrier(2);serial='RACE-'+secrets.token_hex(6);db.session.rollback()
    def receive(unit):
        with mysql_app.app_context():
            barrier.wait()
            try:service.create_ticket(sold['actor'],sold['item'],unit,serial,'Concurrent serial');return True
            except InventoryError:return False
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(receive,[1,2]))
    assert sorted(results)==[False,True]


def test_concurrent_receive_vs_cancel(mysql_app,sold,catalog):
    barrier=Barrier(2);db.session.rollback()
    def run(action):
        with mysql_app.app_context():
            barrier.wait()
            try:
                if action=='receive':service.create_ticket(sold['actor'],sold['item'],1,None,'Cancel race')
                else:transition('sales',sold['actor'],sold['order'],'cancel')
                return action
            except InventoryError:return 'blocked'
    with ThreadPoolExecutor(max_workers=2) as pool:result=list(pool.map(run,['receive','cancel']))
    assert result.count('blocked')==1
    db.session.rollback();order=db.session.get(SalesOrder,sold['order'])
    assert stock(catalog)==(10 if order.status=='cancelled' else 7)


def test_legacy_verification_preserves_snapshots(sold,catalog):
    # Simulate a pre-5.2 completed line with no policy, without deleting any history.
    order=SalesOrder(order_code='OLD-'+secrets.token_hex(6),created_by=sold['actor'],customer_name='Legacy snapshot',
        customer_phone='0901234567',order_date=service.utc_now(),status='completed',total_amount=1)
    db.session.add(order);db.session.flush()
    item=SalesOrderItem(order_id=order.id,product_id=sold['product'],quantity=1,unit_price=1,line_total=1)
    db.session.add(item);db.session.commit();oid,iid=order.id,item.id;db.session.rollback()
    with pytest.raises(InventoryError):service.create_ticket(sold['actor'],iid,1,None,'Old issue')
    service.verify_legacy(sold['actor'],iid,service.local_day(),12,'Chứng từ đã đối chiếu')
    with pytest.raises(InventoryError):service.verify_legacy(sold['actor'],iid,service.local_day(),24,'Overwrite')
    db.session.rollback();old=db.session.get(SalesOrder,oid)
    assert old.customer_name=='Legacy snapshot' and old.customer_id is None and old.completed_at is None
    assert service.create_ticket(sold['actor'],iid,1,None,'Old issue')


def test_staff_scope_lookup_assign_and_http(auth_client,account,sold,catalog):
    tid=intake(sold)
    other=User(username='wstaff-'+secrets.token_hex(6),full_name='Staff bảo hành',role='staff',task_groups='warranty');other.set_password(secrets.token_urlsafe(24))
    db.session.add(other);db.session.commit();other_id=other.id
    with pytest.raises(InventoryError) as error:
        service.handle_ticket(other_id,tid,'processing','received',result='Private')
    assert error.value.status==404
    db.session.rollback();user=db.session.get(User,account['id']);user.role='staff';db.session.commit()
    login(auth_client,account)
    # Staff can handle own warranty even when the sale belongs to another staff.
    db.session.get(SalesOrder,sold['order']).created_by=other_id;db.session.commit()
    assert auth_client.get(f'/business/sales/{sold["order"]}').status_code==404
    lookup=auth_client.get('/business/warranties/lookup',query_string={'q':catalog['sku']})
    assert lookup.status_code==200 and 'Khách bảo hành' in lookup.text
    assert f'href="/business/sales/{sold["order"]}"' not in lookup.text
    assert auth_client.get(f'/business/warranties/{tid}').status_code==200
    assert auth_client.get(f'/business/warranties/legacy/{sold["item"]}').status_code==403
    assert auth_client.post(f'/business/warranties/{tid}/assign',data={'csrf_token':csrf(auth_client)}).status_code==403
    assert auth_client.post(f'/business/warranties/{tid}/handle').status_code==400
    db.session.rollback();db.session.get(User,account['id']).role='admin';db.session.commit()
    service.handle_ticket(account['id'],tid,'assign','received',assignee=other_id)
    service.handle_ticket(other_id,tid,'processing','received',result='Đã đối chiếu điều kiện')
    db.session.rollback();assert db.session.get(WarrantyTicket,tid).assessment=='accepted'


def test_http_intake_double_submit_validation_and_search(auth_client,account,sold,catalog):
    login(auth_client,account);path=f'/business/warranties/new/{sold["item"]}'
    page=auth_client.get(path)
    assert page.status_code==200
    ticket=re.search(r'name="ticket"[^>]*value="([^"]+)"',page.text).group(1)
    data=dict(csrf_token=csrf(auth_client),ticket=ticket,unit_index='1',issue='Lỗi máy',serial='UI-'+secrets.token_hex(5))
    response=auth_client.post(path,data=data);assert response.status_code==303
    assert auth_client.post(path,data=data).status_code==409
    assert auth_client.post(path,data=dict(data,ticket='forged',unit_index='2')).status_code==422
    detail=auth_client.get(response.location);assert detail.status_code==200 and 'Lỗi máy' in detail.text
    for q in [data['serial'],'Khách bảo hành','0901234567',catalog['sku']]:
        assert auth_client.get('/business/warranties/lookup',query_string={'q':q}).status_code==200
    assert auth_client.get('/business/warranties?q='+data['serial']).status_code==200
    assert auth_client.get('/business/warranties?status=bogus').status_code==400
    assert auth_client.get('/business/warranties/lookup?page=0').status_code==400


def test_anonymous_and_sidebar(auth_client,account):
    for path in ['/business/warranties','/business/warranties/lookup']:
        assert auth_client.get(path).status_code==302
    login(auth_client,account)
    page=auth_client.get('/business/warranties/lookup').text
    assert 'data-nav-group="aftersales" open' in page
    assert 'Tra cứu bảo hành' in page and 'Quay về quản trị' in page


def test_mysql_rejects_missing_policy_terms(account,catalog):
    product=db.session.get(Product,catalog['product_id']);product.warranty_enabled=True
    with pytest.raises(DBAPIError):db.session.commit()
    db.session.rollback()


def test_concurrent_handling_only_once(mysql_app,sold):
    tid=intake(sold);barrier=Barrier(2);db.session.rollback()
    def process():
        with mysql_app.app_context():
            barrier.wait()
            try:service.handle_ticket(sold['actor'],tid,'processing','received',result='Concurrent decision');return True
            except InventoryError:return False
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(lambda _:process(),range(2)))
    assert sorted(results)==[False,True]


def test_concurrent_serial_across_orders(mysql_app,account,sold,catalog):
    oid=create_document('sales',account['id'],dict(customer_name='Another order'),lines(catalog,1));transition('sales',account['id'],oid,'complete')
    db.session.rollback();iid=db.session.scalar(select(SalesOrderItem.id).where(SalesOrderItem.order_id==oid))
    barrier=Barrier(2);serial='GLOBAL-'+secrets.token_hex(6);db.session.rollback()
    def receive(item):
        with mysql_app.app_context():
            barrier.wait()
            try:service.create_ticket(sold['actor'],item,1,serial,'Global serial');return True
            except InventoryError:return False
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(receive,[sold['item'],iid]))
    assert sorted(results)==[False,True]


def test_staff_cannot_open_others_ticket_http(auth_client,account,sold):
    tid=intake(sold);db.session.rollback()
    other=User(username='wowner-'+secrets.token_hex(6),full_name='Other owner',role='staff')
    other.set_password(secrets.token_urlsafe(24));db.session.add(other);db.session.flush()
    ticket=db.session.get(WarrantyTicket,tid);ticket.created_by=other.id;ticket.assigned_to=other.id
    db.session.get(User,account['id']).role='staff';db.session.commit();login(auth_client,account)
    assert auth_client.get(f'/business/warranties/{tid}').status_code==404
    response=auth_client.get('/business/warranties?q='+ticket.ticket_code)
    assert response.status_code==200 and 'data-warranty-row' not in response.text
    assert auth_client.post(f'/business/warranties/{tid}/handle',data=dict(csrf_token=csrf(auth_client),target='processing',expected_status='received',inspection_result='Forbidden',confirmed='yes')).status_code==404


def test_handling_http_confirm_stale_and_backend_authorization(auth_client,account,sold):
    tid=intake(sold);login(auth_client,account);path=f'/business/warranties/{tid}/handle'
    data=dict(csrf_token=csrf(auth_client),target='processing',expected_status='received',inspection_result='Actual inspection')
    assert auth_client.post(path,data=data).status_code==422
    data['confirmed']='yes';assert auth_client.post(path,data=data).status_code==303
    assert auth_client.post(path,data=data).status_code==409
    assert auth_client.post(path,data=dict(data,target='returned',expected_status='processing')).status_code==409


def test_product_warranty_validation_and_staff_guard(auth_client,account,catalog):
    from test_catalog import data_for
    # Validate model policy independently of existing catalog form helpers.
    from app.catalog.forms import ProductForm
    with auth_client.application.test_request_context('/business/products/new',method='POST',data={'warranty_enabled':'y'}):
        form=ProductForm();form.category_id.choices=[(0,'Chưa chọn')];form.business_id.choices=[(0,'Chưa chọn')]
        assert not form.validate() and form.warranty_months.errors
    db.session.get(User,account['id']).role='staff';db.session.commit();login(auth_client,account)
    data=data_for('products',catalog);data.update(csrf_token=csrf(auth_client),warranty_enabled='y',warranty_months='12')
    assert auth_client.post('/business/products/new',data=data).status_code==403
