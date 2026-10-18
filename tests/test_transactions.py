"""HTTP/CSRF/ownership and dashboard regressions on the isolated MySQL DB."""
import re
from decimal import Decimal

import pytest
from sqlalchemy import select, func

from app.extensions import db
from app.models import Product, SalesOrder, PurchaseReceipt, StockMovement, User
from app.services.dashboard_service import load_dashboard
from app.services.inventory_service import InventoryError
from test_auth import account, auth_client, csrf, login
from test_inventory import receipt, order, transition, stock, lines, create_document


def create_form(client,kind,catalog,**changes):
    page=client.get('/business/'+kind+'/new')
    assert page.status_code==200
    ticket=re.search(r'name="ticket"[^>]*value="([^"]+)"',page.text).group(1)
    data={'csrf_token':csrf(client),'ticket':ticket,'business_id':str(catalog['business_id']),
          'customer_name':'Khách kiểm thử','lines-0-product_id':str(catalog['product_id']),
          'lines-0-quantity':'2','lines-0-unit_cost':'1000.25'}
    data.update(changes)
    return data


def post_action(client,path):
    return client.post(path,data={'csrf_token':csrf(client)})


@pytest.mark.parametrize('kind',['purchases','sales'])
def test_http_create_complete_cancel(auth_client,account,catalog,kind):
    if kind=='sales':receipt(account,catalog,5,True)
    assert login(auth_client,account).status_code==302
    path='/business/'+kind
    before=stock(catalog)
    data=create_form(auth_client,kind,catalog)
    response=auth_client.post(path+'/new',data=data)
    assert response.status_code==303
    detail=response.location
    assert stock(catalog)==before
    page=auth_client.get(detail)
    assert page.status_code==200 and 'Bản nháp' in page.text and 'Xác nhận hoàn thành' in page.text
    assert post_action(auth_client,detail+'/complete').status_code==303
    assert stock(catalog)==before+(2 if kind=='purchases' else -2)
    assert post_action(auth_client,detail+'/complete').status_code==409
    assert post_action(auth_client,detail+'/cancel').status_code==303
    assert stock(catalog)==before
    assert post_action(auth_client,detail+'/cancel').status_code==409
    assert auth_client.get(path+'?status=cancelled').status_code==200
    assert auth_client.get('/business/inventory?q='+catalog['sku']).status_code==200
    assert auth_client.post(detail+'/delete',data={'csrf_token':csrf(auth_client)}).status_code==404


@pytest.mark.parametrize('path',['/business/purchases','/business/sales','/business/inventory','/business/sales/new','/business/purchases/new','/business/sales/products'])
def test_anonymous_protected(auth_client,path):
    assert auth_client.get(path).status_code==302


def test_csrf_ticket_duplicate_and_ignored_total(auth_client,account,catalog):
    login(auth_client,account)
    data=create_form(auth_client,'purchases',catalog,total_amount='0',stock_quantity='99999')
    assert auth_client.post('/business/purchases/new',data={**data,'csrf_token':''}).status_code==400
    assert auth_client.post('/business/purchases/new',data={**data,'ticket':'tampered'}).status_code==422
    response=auth_client.post('/business/purchases/new',data=data)
    assert response.status_code==303
    assert auth_client.post('/business/purchases/new',data=data).status_code==409
    db.session.rollback()
    identifier=int(response.location.rsplit('/',1)[1])
    assert db.session.get(PurchaseReceipt,identifier).total_amount==Decimal('2000.50')
    assert auth_client.post(response.location+'/complete').status_code==400
    assert stock(catalog)==0


def test_staff_route_scope_and_no_system_admin(auth_client,account,catalog):
    receipt(account,catalog,5,True)
    others=order(account,catalog)
    staff=db.session.get(User,account['id']);staff.role='staff';db.session.commit()
    # Existing order ownership stays this account; another user's order must be hidden.
    another=order(dict(id=catalog['user_id']),catalog)
    login(auth_client,account)
    assert auth_client.get('/business/purchases').status_code==403
    assert auth_client.get('/business/purchases/new').status_code==403
    assert auth_client.get('/business/purchases/products').status_code==403
    assert auth_client.get('/admin/dashboard').status_code==403
    assert auth_client.get(f'/business/sales/{another}').status_code==404
    assert post_action(auth_client,f'/business/sales/{another}/complete').status_code==404
    assert auth_client.get(f'/business/sales/{others}').status_code==200
    assert post_action(auth_client,f'/business/sales/{others}/complete').status_code==303
    assert post_action(auth_client,f'/business/sales/{others}/cancel').status_code==403
    listing=auth_client.get('/business/sales')
    db.session.rollback()
    assert db.session.get(SalesOrder,another).order_code not in listing.text
    movements_page=auth_client.get('/business/inventory')
    assert movements_page.status_code==200 and 'Phiếu nhập #' not in movements_page.text


@pytest.mark.parametrize('query',['status=invalid','page=-1','page=abc','q='+'x'*121,'from=invalid','to=9999-12-31','business_id=-1'])
def test_list_invalid_inputs(auth_client,account,query):
    login(auth_client,account)
    assert auth_client.get('/business/purchases?'+query).status_code==400


def test_empty_filter_dates_pagination_and_product_options(auth_client,account,catalog):
    login(auth_client,account)
    identifier=receipt(account,catalog)
    db.session.rollback();code=db.session.get(PurchaseReceipt,identifier).receipt_code
    assert code in auth_client.get('/business/purchases?q='+code).text
    assert 'Chưa có giao dịch phù hợp' in auth_client.get('/business/purchases?q=DOES-NOT-EXIST-XYZ').text
    assert auth_client.get('/business/purchases?from=2020-01-01&to=2030-01-01&page=2').status_code==200
    options=auth_client.get('/business/sales/products?q='+catalog['sku'])
    assert options.status_code==200 and len(options.json)==1
    assert options.json[0]['price']=='2345.67'
    assert 'purchase_price' not in options.text
    assert len(auth_client.get('/business/sales/products').json)<=50


def test_form_invalid_price_and_email(auth_client,account,catalog):
    login(auth_client,account)
    data=create_form(auth_client,'purchases',catalog,**{'lines-0-unit_cost':'1.005'})
    assert auth_client.post('/business/purchases/new',data=data).status_code==422
    data=create_form(auth_client,'sales',catalog,customer_email='not-an-email')
    assert auth_client.post('/business/sales/new',data=data).status_code==422


def test_dashboard_stock_follows_real_transactions(account,catalog):
    product=db.session.get(Product,catalog['product_id']);product.reorder_level=1;db.session.commit()
    before=load_dashboard('admin')['totals']
    incoming=receipt(account,catalog,5,True)
    after=load_dashboard('admin')['totals']
    assert after['low_stock']==before['low_stock']-1
    assert after['inventory_value']==before['inventory_value']+Decimal('6172.80')
    sale=order(account,catalog,4);transition('sales',account['id'],sale,'complete')
    sold=load_dashboard('admin')['totals']
    assert sold['low_stock']==before['low_stock']
    assert sold['inventory_value']==before['inventory_value']+Decimal('1234.56')
    transition('sales',account['id'],sale,'cancel');transition('purchases',account['id'],incoming,'cancel')
    assert load_dashboard('admin')['totals']==before
    assert 'inventory_value' not in load_dashboard('staff')['totals']


def test_two_http_requests_cannot_oversell(mysql_app,auth_client,account,catalog):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    receipt(account,catalog,5,True)
    identifiers=[order(account,catalog,4),order(account,catalog,4)]
    login(auth_client,account)
    token=csrf(auth_client)
    cookie=auth_client.get_cookie('session').value
    db.session.remove()
    barrier=Barrier(2)
    def worker(identifier):
        with mysql_app.test_client() as client:
            client.set_cookie('session',cookie)
            barrier.wait(timeout=10)
            return client.post(f'/business/sales/{identifier}/complete',data={'csrf_token':token}).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses=list(pool.map(worker,identifiers))
    assert sorted(statuses)==[303,409]
    assert stock(catalog)==1


def test_staff_pagination_and_status_filter_are_scoped(auth_client,account,catalog):
    receipt(account,catalog,5,True)
    user=db.session.get(User,account['id']);user.role='staff';db.session.commit()
    ids=[order(account,catalog,1) for _ in range(11)]
    # Online client orders are also in the staff queue; isolate these fixture orders.
    for identifier in ids:
        db.session.get(SalesOrder, identifier).customer_name = 'Pagination-' + catalog['suffix']
    db.session.commit()
    login(auth_client,account)
    first=auth_client.get('/business/sales?status=draft&page=1&q=Pagination-' + catalog['suffix'])
    second=auth_client.get('/business/sales?status=draft&page=2&q=Pagination-' + catalog['suffix'])
    def shown(page):
        return {int(value) for value in re.findall(r'href="/business/sales/(\d+)"',page.text)}
    assert first.status_code==second.status_code==200
    assert len(shown(first))==10 and len(shown(second))==1
    assert shown(first).isdisjoint(shown(second))
    assert shown(first)|shown(second)==set(ids)
    assert not shown(auth_client.get('/business/sales?status=cancelled&q=Pagination-' + catalog['suffix']))
