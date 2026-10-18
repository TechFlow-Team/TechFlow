"""Nghiệm thu bổ sung cho Mục 6 (hỗ trợ) + Mục 8 (polish) của nâng cấp buyer UI.

Các quy tắc §7 còn lại được bổ sung ở đây (các quy tắc khác đã có trong
test_backlog.py: quyền đánh giá 403, giới hạn so sánh >4 → 422, quyền xem ticket).
Chạy trên bộ MySQL cách ly giống các test khác (RUN_MYSQL_TESTS=1 + Docker db-test).
"""
import secrets

from decimal import Decimal

from sqlalchemy import select

from app.extensions import db
from app.models import Product, SupportConversation
from test_auth import auth_client, csrf
from test_backlog import as_user, order_for, people, post  # noqa: F401  (pytest fixtures)


def xhr_post(client, path, source='/shop', **data):
    """POST kèm CSRF + header AJAX để chạm các endpoint JSON."""
    return client.post(
        path,
        data={'csrf_token': csrf(client, source), **data},
        headers={'X-Requested-With': 'XMLHttpRequest'},
    )


def test_cart_quantity_is_capped_to_stock(auth_client, people):
    """Mục 4/§7: số lượng trong giỏ không vượt quá tồn kho hiện có."""
    product_id = people['catalog']['product_id']
    product = db.session.get(Product, product_id)
    product.stock_quantity = 3
    db.session.commit()
    as_user(auth_client, people['client'])

    # add_to_cart: yêu cầu vượt tồn kho (20 > 3) không được thêm vào giỏ.
    assert post(auth_client, f'/shop/cart/{product_id}', quantity='20').status_code == 303
    assert auth_client.get('/cart/count').get_json()['count'] == 0

    # Thêm trong mức tồn kho thì được.
    assert post(auth_client, f'/shop/cart/{product_id}', quantity='2').status_code == 303
    assert auth_client.get('/cart/count').get_json()['count'] == 2

    # set_cart_item: đặt vượt tồn kho (10 > 3) bị kẹp về đúng số còn lại (3).
    response = xhr_post(auth_client, f'/cart/item/{product_id}', quantity='10')
    assert response.status_code == 200
    payload = response.get_json()
    assert payload['quantity'] == 3
    assert auth_client.get('/cart/count').get_json()['count'] == 3


def test_compare_blocks_cross_category(auth_client, people):
    """Mục 2/§7: không cho so sánh các sản phẩm khác danh mục."""
    first = db.session.get(Product, people['catalog']['product_id'])
    # Sản phẩm thứ 2 ở MỘT danh mục khác (tạo category mới để chắc chắn khác).
    from app.models import Category
    other_category = Category(code='M8-' + secrets.token_hex(4), name='Danh mục khác M8')
    db.session.add(other_category)
    db.session.flush()
    other = Product(sku='M8-' + secrets.token_hex(6), name='Sản phẩm khác danh mục',
                    category_id=other_category.id, purchase_price=Decimal('1'),
                    selling_price=Decimal('2'), stock_quantity=5)
    db.session.add(other)
    db.session.commit()

    as_user(auth_client, people['client'])
    # Thêm sản phẩm đầu tiên (cùng danh mục gốc) qua endpoint JSON add.
    assert xhr_post(auth_client, f'/compare/{first.id}/add').status_code == 200
    # Thêm sản phẩm khác danh mục → bị chặn 422.
    blocked = xhr_post(auth_client, f'/compare/{other.id}/add')
    assert blocked.status_code == 422
    assert 'danh mục' in (blocked.get_json().get('error') or '').lower()


def test_support_messages_endpoint_enforces_ownership(auth_client, people):
    """Mục 6/§7: user khác không đọc được tin nhắn ticket qua endpoint polling."""
    as_user(auth_client, people['client'])
    response = post(auth_client, '/support/new', subject='Hỏi đơn hàng', body='Nội dung riêng tư')
    assert response.status_code == 303
    thread = db.session.scalar(
        select(SupportConversation).where(SupportConversation.user_id == people['client']['id']))
    assert thread is not None

    messages_path = f'/support/{thread.id}/messages'

    # Chủ ticket đọc được tin nhắn qua JSON polling.
    owner_view = auth_client.get(messages_path)
    assert owner_view.status_code == 200
    body = owner_view.get_json()
    assert body['status'] in {'new', 'processing', 'closed'}
    assert any('Nội dung riêng tư' in message['body'] for message in body['messages'])

    # User khác (client 'other') bị chặn (ngoài scope → 404).
    as_user(auth_client, people['other'])
    assert auth_client.get(messages_path).status_code == 404
