"""Backlog acceptance tests against the isolated MySQL runner."""
import csv
import io
import secrets
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.extensions import db
from app.models import (AuditLog, BlogComment, BlogPost, Customer, Favorite, OrderEvent, Product,
                        ProductReview, SalesOrder, SalesOrderItem, StockMovement, SupportConversation,
                        SupportMessage, User, WarrantyCoverage)
from app.models.base import utc_now
from app.services.client_order_service import cancel_client_order, place_client_order
from app.services.inventory_service import InventoryError
from app.services.transaction_service import transition
from test_auth import auth_client, csrf, login, TestAccount


@pytest.fixture
def people(catalog):
    suffix = secrets.token_hex(6)
    result = dict(catalog=catalog)
    for index, role in enumerate(['admin', 'client', 'other', 'staff', 'unassigned']):
        password = secrets.token_urlsafe(20)
        user = User(username=f'backlog-{role}-{suffix}', full_name=role, role='client' if role == 'other' else 'staff' if role == 'unassigned' else role,
                    task_groups='orders,inventory,content,warranty,support,reports' if role == 'staff' else '')
        user.set_password(password)
        db.session.add(user)
        db.session.flush()
        if user.role == 'client':
            db.session.add(Customer(name=role, phone='0' + str(secrets.randbelow(10**9)).zfill(9),
                                    user_id=user.id, created_by=user.id, address='Địa chỉ kiểm thử'))
        result[role] = TestAccount(id=user.id, username=user.username, password=password)
    product = db.session.get(Product, catalog['product_id'])
    product.stock_quantity, product.warranty_enabled, product.warranty_months = 100, True, 12
    db.session.commit()
    return result


def as_user(client, account):
    with client.session_transaction() as state:
        state.clear()
    assert login(client, account).status_code == 302


def post(client, path, source='/shop', **data):
    return client.post(path, data={'csrf_token': csrf(client, source), **data})


def order_for(people, complete=False):
    identifier = place_client_order(people['client']['id'], {str(people['catalog']['product_id']): 2})
    if complete:
        for action in ['confirm', 'ship', 'complete']:
            transition('sales', people['admin']['id'], identifier, action)
    db.session.rollback()
    return identifier


def test_tracking_atomic_stock_and_history(auth_client, people):
    identifier = order_for(people)
    product_id = people['catalog']['product_id']
    with pytest.raises(InventoryError):
        transition('sales', people['admin']['id'], identifier, 'ship')
    with pytest.raises(InventoryError):
        transition('sales', people['admin']['id'], identifier, 'complete')
    transition('sales', people['staff']['id'], identifier, 'confirm', 'Đã gọi xác nhận')
    with pytest.raises(InventoryError):
        cancel_client_order(people['client']['id'], identifier)
    transition('sales', people['staff']['id'], identifier, 'ship')
    db.session.rollback()
    assert db.session.get(Product, product_id).stock_quantity == 100
    transition('sales', people['staff']['id'], identifier, 'complete')
    with pytest.raises(InventoryError):
        transition('sales', people['staff']['id'], identifier, 'complete')
    db.session.rollback()
    assert db.session.get(Product, product_id).stock_quantity == 98
    assert db.session.scalars(select(OrderEvent.status).where(OrderEvent.order_id == identifier).order_by(OrderEvent.id)).all() == ['waiting', 'confirmed', 'shipping', 'completed']
    transition('sales', people['admin']['id'], identifier, 'cancel', 'Hủy và hoàn kho')
    with pytest.raises(InventoryError):
        transition('sales', people['admin']['id'], identifier, 'cancel')
    db.session.rollback()
    assert db.session.get(Product, product_id).stock_quantity == 100
    assert db.session.scalar(select(func.count()).select_from(StockMovement).where(StockMovement.product_id == product_id)) == 2
    as_user(auth_client, people['client'])
    page = auth_client.get(f'/account/orders/{identifier}')
    assert page.status_code == 200 and 'Đã gọi xác nhận' in page.text
    as_user(auth_client, people['other'])
    assert auth_client.get(f'/account/orders/{identifier}').status_code == 404


def test_rejected_and_cancelled_drafts_never_change_stock(auth_client, people):
    identifier = order_for(people)
    transition('sales', people['admin']['id'], identifier, 'reject', 'Không thể cung cấp')
    db.session.expire_all()
    assert db.session.get(SalesOrder, identifier).fulfillment_status == 'rejected'
    assert db.session.get(Product, people['catalog']['product_id']).stock_quantity == 100
    identifier = order_for(people)
    cancel_client_order(people['client']['id'], identifier)
    db.session.rollback()
    assert db.session.get(SalesOrder, identifier).events[-1].status == 'cancelled'


def test_inventory_threshold_is_admin_only_and_stock_unchanged(auth_client, people):
    product_id = people['catalog']['product_id']
    as_user(auth_client, people['staff'])
    assert post(auth_client, f'/business/low-stock/{product_id}', threshold='101').status_code == 403
    as_user(auth_client, people['admin'])
    assert post(auth_client, f'/business/low-stock/{product_id}', threshold='-1').status_code == 422
    assert post(auth_client, f'/business/low-stock/{product_id}', threshold='101').status_code == 303
    page = auth_client.get('/business/low-stock?q=' + people['catalog']['sku'])
    assert page.status_code == 200 and people['catalog']['sku'] in page.text
    db.session.expire_all()
    assert db.session.get(Product, product_id).stock_quantity == 100
    assert db.session.get(Product, product_id).reorder_level == 101


def test_reports_vietnam_dates_csv_and_permissions(auth_client, people):
    identifier = order_for(people, complete=True)
    order = db.session.get(SalesOrder, identifier)
    order.completed_at = datetime(2001, 1, 1, 18, 0)
    order.order_date = datetime(2001, 1, 1, 18, 0)
    amount = order.total_amount
    db.session.commit()
    as_user(auth_client, people['admin'])
    path = '/business/reports?from=2001-01-02&to=2001-01-02'
    page = auth_client.get(path)
    assert page.status_code == 200 and '2001-01-02' in page.text
    report = auth_client.get(path + '&format=csv')
    rows = list(csv.reader(io.StringIO(report.data.decode('utf-8-sig'))))
    cancelled_before = next(row for row in rows if row[0] == 'Đơn hủy theo ngày đặt')
    assert ['2001-01-02', '1', str(amount)] in rows
    assert [people['catalog']['sku'], 'SSD kiểm thử', '2', str(amount)] in rows
    assert '2001-01' in auth_client.get(path + '&group=month').text
    assert auth_client.get('/business/reports?from=2000-01-01&to=2002-01-01').status_code == 400
    assert auth_client.get(path + '&group=invalid').status_code == 400
    transition('sales', people['admin']['id'], identifier, 'cancel')
    db.session.rollback()
    after = list(csv.reader(io.StringIO(auth_client.get(path + '&format=csv').data.decode('utf-8-sig'))))
    assert ['2001-01-02', '1', str(amount)] not in after
    assert ['Đơn hủy theo ngày đặt', str(int(cancelled_before[1]) + 1), str(Decimal(cancelled_before[2]) + amount)] in after
    as_user(auth_client, people['unassigned'])
    assert auth_client.get(path).status_code == 403
    as_user(auth_client, people['client'])
    assert auth_client.get(path).status_code == 403


def test_staff_grants_apply_to_existing_session(auth_client, people):
    as_user(auth_client, people['unassigned'])
    assert auth_client.get('/business/sales').status_code == 403
    assert auth_client.get('/business/products').status_code == 403
    assert auth_client.get('/support').status_code == 403
    assert post(auth_client, f"/admin/staff/{people['unassigned']['id']}/permissions", groups=['orders']).status_code == 403
    as_user(auth_client, people['admin'])
    endpoint = f"/admin/staff/{people['unassigned']['id']}/permissions"
    assert post(auth_client, endpoint, groups=['admin']).status_code == 422
    assert post(auth_client, endpoint, groups=['orders']).status_code == 303
    as_user(auth_client, people['unassigned'])
    assert auth_client.get('/business/sales').status_code == 200
    assert auth_client.get('/business/products').status_code == 403
    user = db.session.get(User, people['unassigned']['id'])
    user.task_groups = ''
    db.session.commit()
    assert auth_client.get('/business/sales').status_code == 403
    user.is_active = False
    db.session.commit()
    assert auth_client.get('/staff/dashboard').status_code == 302
    assert db.session.scalar(select(AuditLog.id).where(AuditLog.entity_id == user.id, AuditLog.action == 'staff_permissions'))


def test_blog_draft_publication_permissions_and_safe_content(auth_client, people):
    as_user(auth_client, people['staff'])
    slug = 'bai-' + secrets.token_hex(6)
    data = dict(title='Bài kiểm thử', slug=slug, body='<script>alert(1)</script>\nGiới thiệu SSD', products=str(people['catalog']['product_id']))
    assert post(auth_client, '/business/content/new', status='published', **data).status_code == 403
    assert post(auth_client, '/business/content/new', status='draft', **data).status_code == 303
    entry = db.session.scalar(select(BlogPost).where(BlogPost.slug == slug))
    assert auth_client.get('/blog/' + slug).status_code == 404
    as_user(auth_client, people['admin'])
    assert post(auth_client, f'/business/content/{entry.id}/edit', status='published', **data).status_code == 303
    page = auth_client.get('/blog/' + slug)
    assert page.status_code == 200 and '&lt;script&gt;' in page.text and '<script>alert(1)</script>' not in page.text
    assert f'/shop/product/{people["catalog"]["product_id"]}' in page.text
    as_user(auth_client, people['staff'])
    assert auth_client.get(f'/business/content/{entry.id}/edit').status_code == 403
    as_user(auth_client, people['admin'])
    assert post(auth_client, f'/business/content/{entry.id}/edit', status='hidden', **data).status_code == 303
    assert auth_client.get('/blog/' + slug).status_code == 404


def test_comments_moderation_ownership_spam_and_audit(auth_client, people):
    entry = BlogPost(title='Bình luận', slug='comments-' + secrets.token_hex(6), body='Nội dung', author_id=people['admin']['id'], status='published', published_at=utc_now())
    db.session.add(entry)
    db.session.commit()
    path = f'/blog/{entry.id}/comments'
    as_user(auth_client, people['client'])
    assert post(auth_client, path, body='').status_code == 422
    assert post(auth_client, path, body='<img src=x onerror=alert(1)>').status_code == 303
    assert post(auth_client, path, body='Lặp lại').status_code == 429
    comment = db.session.scalar(select(BlogComment).where(BlogComment.post_id == entry.id))
    assert '&lt;img src=x' not in auth_client.get('/blog/' + entry.slug).text.split('Bình luận đã gửi của bạn')[0]
    as_user(auth_client, people['other'])
    assert post(auth_client, f'/account/contributions/comment/{comment.id}/delete').status_code == 404
    as_user(auth_client, people['staff'])
    assert post(auth_client, '/business/moderation', kind='comment', id=str(comment.id), status='visible', reason='Hợp lệ').status_code == 303
    page = auth_client.get('/blog/' + entry.slug)
    assert '&lt;img src=x' in page.text and '<img src=x' not in page.text
    assert post(auth_client, '/business/moderation', kind='comment', id=str(comment.id), status='hidden', reason='Ẩn kiểm thử').status_code == 303
    assert '&lt;img src=x' not in auth_client.get('/blog/' + entry.slug).text
    assert db.session.scalar(select(AuditLog.id).where(AuditLog.entity_type == 'blog_comments', AuditLog.entity_id == comment.id, AuditLog.description == 'Ẩn kiểm thử'))
    comment.updated_at = utc_now() - timedelta(minutes=1)
    db.session.commit()
    as_user(auth_client, people['client'])
    assert post(auth_client, f'/account/contributions/comment/{comment.id}/edit', body='Bản sửa').status_code == 303
    db.session.expire_all()
    assert db.session.get(BlogComment, comment.id).status == 'pending'


def test_reviews_require_completed_purchase_and_reapproval(auth_client, people):
    product_id = people['catalog']['product_id']
    path = f'/shop/product/{product_id}/review'
    as_user(auth_client, people['client'])
    assert post(auth_client, path, rating='5', body='Tốt').status_code == 403
    identifier = order_for(people)
    assert post(auth_client, path, rating='5', body='Tốt').status_code == 403
    for action in ['confirm', 'ship', 'complete']:
        transition('sales', people['admin']['id'], identifier, action)
    assert post(auth_client, path, rating='6', body='Tốt').status_code == 422
    assert post(auth_client, path, rating='5', body='Sản phẩm rất tốt').status_code == 303
    review = db.session.scalar(select(ProductReview).where(ProductReview.product_id == product_id))
    assert 'Sản phẩm rất tốt' not in auth_client.get(f'/shop/product/{product_id}').text
    as_user(auth_client, people['admin'])
    assert post(auth_client, '/business/moderation', kind='review', id=str(review.id), status='visible').status_code == 303
    assert 'Sản phẩm rất tốt' in auth_client.get(f'/shop/product/{product_id}').text
    review.updated_at = utc_now() - timedelta(minutes=1)
    db.session.commit()
    as_user(auth_client, people['client'])
    assert post(auth_client, path, rating='4', body='Đã sửa đánh giá').status_code == 303
    db.session.expire_all()
    assert db.session.scalar(select(func.count()).select_from(ProductReview).where(ProductReview.product_id == product_id)) == 1
    assert db.session.get(ProductReview, review.id).status == 'pending'
    assert 'Đã sửa đánh giá' not in auth_client.get(f'/shop/product/{product_id}').text


def test_favorites_persist_and_compare_bounds(auth_client, people):
    product_id = people['catalog']['product_id']
    as_user(auth_client, people['client'])
    assert post(auth_client, f'/account/favorites/{product_id}').status_code == 303
    as_user(auth_client, people['other'])
    assert people['catalog']['sku'] not in auth_client.get('/account/favorites').text
    as_user(auth_client, people['client'])
    assert people['catalog']['sku'] in auth_client.get('/account/favorites').text
    product = db.session.get(Product, product_id)
    product.is_active = False
    db.session.commit()
    assert 'Ngừng bán' in auth_client.get('/account/favorites').text
    assert post(auth_client, f'/compare/{product_id}').status_code == 303
    assert 'Ngừng bán' in auth_client.get('/compare').text
    ids = [product_id]
    for index in range(4):
        extra = Product(sku='CMP-' + secrets.token_hex(6), name=f'So sánh {index}', category_id=product.category_id, purchase_price=1, selling_price=2)
        db.session.add(extra)
        db.session.commit()
        ids.append(extra.id)
        assert post(auth_client, f'/compare/{extra.id}').status_code == (422 if index == 3 else 303)
    assert len(auth_client.get('/compare').text) > 100
    assert post(auth_client, f'/compare/{product_id}').status_code == 303


def test_client_warranties_use_owned_snapshot(auth_client, people):
    identifier = order_for(people, complete=True)
    item = db.session.scalar(select(SalesOrderItem).where(SalesOrderItem.order_id == identifier))
    coverage = db.session.scalar(select(WarrantyCoverage).where(WarrantyCoverage.sale_item_id == item.id))
    start, end = coverage.starts_on, coverage.expires_on
    product = db.session.get(Product, item.product_id)
    product.warranty_months = 24
    db.session.commit()
    as_user(auth_client, people['client'])
    page = auth_client.get('/account/warranties')
    assert page.status_code == 200 and str(start) in page.text and str(end) in page.text
    as_user(auth_client, people['other'])
    assert db.session.get(SalesOrder, identifier).order_code not in auth_client.get('/account/warranties').text


def test_support_order_ownership_assignment_and_close(auth_client, people):
    identifier = order_for(people)
    as_user(auth_client, people['other'])
    assert post(auth_client, '/support/new', subject='Hỏi', body='Nội dung', order_id=str(identifier)).status_code == 404
    as_user(auth_client, people['client'])
    response = post(auth_client, '/support/new', subject='Hỏi bảo hành', body='<script>nội dung riêng</script>', order_id=str(identifier))
    assert response.status_code == 303
    path = response.location
    thread = db.session.scalar(select(SupportConversation).where(SupportConversation.user_id == people['client']['id']))
    assert post(auth_client, '/support/new', subject='Lặp', body='Nội dung').status_code == 429
    as_user(auth_client, people['other'])
    assert auth_client.get(path).status_code == 404
    as_user(auth_client, people['staff'])
    assert post(auth_client, path, body='Chưa nhận').status_code == 403
    assert post(auth_client, path + '/manage', action='take').status_code == 303
    assert post(auth_client, path, body='Cửa hàng đã nhận yêu cầu').status_code == 303
    assert post(auth_client, path, body='Gửi nhanh').status_code == 429
    page = auth_client.get(path)
    assert '&lt;script&gt;nội dung riêng' in page.text and '<script>nội dung riêng' not in page.text
    assert post(auth_client, path + '/manage', action='close').status_code == 303
    as_user(auth_client, people['client'])
    assert post(auth_client, path, body='Đã đóng').status_code == 409
    as_user(auth_client, people['admin'])
    assert post(auth_client, path + '/manage', action='reopen').status_code == 303
    assert post(auth_client, path + '/manage', action='assign', assigned_to=str(people['unassigned']['id'])).status_code == 422
    assert auth_client.get('/support').status_code == 200


@pytest.mark.parametrize('path', ['/business/content/new', '/business/moderation', '/support/new', '/compare/1', '/account/favorites/1'])
def test_new_writes_require_csrf(auth_client, people, path):
    as_user(auth_client, people['client'])
    assert auth_client.post(path, data={'body': 'test'}).status_code == 400
