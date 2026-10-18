"""Plain text publishing and moderated customer contributions."""
import re
from datetime import timedelta

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.auth.permissions import business_required, client_required
from app.extensions import db
from app.models import AuditLog, BlogComment, BlogPost, Product, ProductReview, SalesOrder, SalesOrderItem, User
from app.models.base import utc_now
from app.services.image_storage import save_product_image, ImageStorageError
from app.services.inventory_service import InventoryError

blueprint = Blueprint('content', __name__)


def text(value, maximum, required=True):
    value = (value or '').strip()
    if len(value) > maximum or required and not value:
        raise InventoryError(f'Nội dung cần từ 1 đến {maximum} ký tự.', 422)
    return value


def audit(action, model, identifier, description=None):
    db.session.add(AuditLog(user_id=current_user.id, action=action, entity_type=model.__tablename__, entity_id=identifier,
                           description=description))


def throttle(model, seconds=30):
    # Per-user row lock serializes sends across processes, without storing IPs.
    db.session.scalar(select(User).where(User.id == current_user.id).with_for_update())
    latest = db.session.scalar(select(func.max(model.updated_at)).where(model.user_id == current_user.id))
    if latest and latest > utc_now() - timedelta(seconds=seconds):
        raise InventoryError('Vui lòng chờ 30 giây trước khi gửi tiếp.', 429)


@blueprint.errorhandler(InventoryError)
def invalid(error):
    db.session.rollback()
    return render_template('features/message.html', message=error.message), error.status


@blueprint.errorhandler(IntegrityError)
def conflict(error):
    db.session.rollback()
    return render_template('features/message.html', message='Dữ liệu đã tồn tại hoặc vừa thay đổi. Vui lòng tải lại.'), 409


@blueprint.get('/blog')
def blog():
    results = db.paginate(select(BlogPost).where(BlogPost.status == 'published')
                          .order_by(BlogPost.published_at.desc(), BlogPost.id.desc()), per_page=12, max_per_page=12, error_out=False)
    return render_template('features/blog.html', results=results)


@blueprint.get('/blog/<slug>')
def article(slug):
    post = db.session.scalar(select(BlogPost).where(BlogPost.slug == slug, BlogPost.status == 'published'))
    if not post:
        abort(404)
    comments = db.paginate(select(BlogComment).where(BlogComment.post_id == post.id, BlogComment.status == 'visible')
                          .order_by(BlogComment.id.desc()), per_page=20, max_per_page=20, error_out=False)
    own = db.session.scalars(select(BlogComment).where(BlogComment.post_id == post.id,
          BlogComment.user_id == current_user.id, BlogComment.status != 'deleted').order_by(BlogComment.id.desc()).limit(50)).all() if current_user.is_authenticated and current_user.role == 'client' else []
    return render_template('features/article.html', post=post, comments=comments, own=own)


@blueprint.get('/business/content')
@business_required
def manage():
    results = db.paginate(select(BlogPost).order_by(BlogPost.id.desc()), per_page=20, max_per_page=20, error_out=False)
    return render_template('features/content_list.html', results=results, active_page='content')


@blueprint.route('/business/content/new', methods=['GET', 'POST'])
@blueprint.route('/business/content/<int:post_id>/edit', methods=['GET', 'POST'])
@business_required
def edit(post_id=None):
    post = None
    if post_id:
        query = select(BlogPost).where(BlogPost.id == post_id)
        post = db.session.scalar(query.with_for_update() if request.method == 'POST' else query)
        if not post:
            abort(404)
    if current_user.role == 'staff' and post and (post.author_id != current_user.id or post.status != 'draft'):
        abort(403)
    if request.method == 'POST':
        title = text(request.form.get('title'), 200)
        slug = text(request.form.get('slug'), 200)
        body = text(request.form.get('body'), 50000)
        status = request.form.get('status', 'draft')
        if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', slug) or status not in {'draft', 'published', 'hidden'}:
            raise InventoryError('Slug dùng chữ thường không dấu, số và dấu gạch ngang; kiểm tra trạng thái.', 422)
        if current_user.role != 'admin' and status != 'draft':
            abort(403)
        raw_ids = request.form.getlist('products')
        if len(raw_ids) > 10 or any(not re.fullmatch(r'[0-9]{1,19}', value) for value in raw_ids):
            raise InventoryError('Chọn tối đa 10 sản phẩm hợp lệ.', 422)
        ids = set(map(int, raw_ids))
        products = db.session.scalars(select(Product).where(Product.id.in_(ids), Product.is_active.is_(True))).all()
        if len(products) != len(ids):
            raise InventoryError('Chỉ liên kết sản phẩm đang hoạt động.', 422)
        post = post or BlogPost(author_id=current_user.id)
        post.title, post.slug, post.body, post.status = title, slug, body, status
        post.products = products
        if status == 'published' and not post.published_at:
            post.published_at = utc_now()
        if request.form.get('remove_cover'):
            post.cover_url = None
        if request.files.get('cover') and request.files['cover'].filename:
            try:
                post.cover_url = save_product_image(request.files['cover'])
            except ImageStorageError as error:
                raise InventoryError(str(error), 422) from None
        db.session.add(post)
        db.session.flush()
        audit('save_post', BlogPost, post.id)
        db.session.commit()
        flash('Đã lưu bài viết.', 'success')
        return redirect(url_for('content.manage'), code=303)
    products = db.session.scalars(select(Product).where(Product.is_active.is_(True)).order_by(Product.name).limit(500)).all()
    return render_template('features/post_form.html', post=post, products=products, active_page='content')


@blueprint.post('/blog/<int:post_id>/comments')
@client_required
def comment(post_id):
    post = db.get_or_404(BlogPost, post_id)
    if post.status != 'published':
        abort(404)
    body = text(request.form.get('body'), 2000)
    throttle(BlogComment)
    if db.session.scalar(select(BlogComment.id).where(BlogComment.post_id == post.id,
           BlogComment.user_id == current_user.id, BlogComment.body == body, BlogComment.status != 'deleted')):
        raise InventoryError('Bình luận này đã được gửi.', 409)
    entry = BlogComment(post_id=post.id, user_id=current_user.id, body=body)
    db.session.add(entry)
    db.session.commit()
    flash('Bình luận đã gửi, đang chờ duyệt.', 'success')
    return redirect(url_for('content.article', slug=post.slug), code=303)


@blueprint.post('/shop/product/<int:product_id>/review')
@client_required
def review(product_id):
    product = db.get_or_404(Product, product_id)
    body = text(request.form.get('body'), 2000)
    rating = request.form.get('rating', '')
    if rating not in {'1', '2', '3', '4', '5'} or not product.is_active:
        raise InventoryError('Điểm đánh giá phải từ 1 đến 5 và sản phẩm đang bán.', 422)
    throttle(ProductReview)
    bought = db.session.scalar(select(SalesOrderItem.id).join(SalesOrder).where(
        SalesOrderItem.product_id == product_id, SalesOrder.status == 'completed',
        (SalesOrder.created_by == current_user.id) | SalesOrder.customer.has(user_id=current_user.id)).limit(1))
    if not bought:
        raise InventoryError('Bạn cần có đơn hoàn tất chứa sản phẩm này để đánh giá.', 403)
    entry = db.session.scalar(select(ProductReview).where(ProductReview.user_id == current_user.id,
                                                         ProductReview.product_id == product_id).with_for_update())
    entry = entry or ProductReview(user_id=current_user.id, product_id=product_id)
    entry.body, entry.rating, entry.status = body, int(rating), 'pending'
    entry.moderated_by = entry.moderated_at = entry.moderation_reason = None
    db.session.add(entry)
    db.session.flush()
    audit('submit_review', ProductReview, entry.id)
    db.session.commit()
    flash('Đánh giá đang chờ duyệt.', 'success')
    return redirect(url_for('shop.product_detail', product_id=product_id), code=303)


CONTRIBUTIONS = {'comment': BlogComment, 'review': ProductReview}


@blueprint.post('/account/contributions/<kind>/<int:entry_id>/<action>')
@client_required
def own_contribution(kind, entry_id, action):
    model = CONTRIBUTIONS.get(kind)
    if not model or action not in {'edit', 'delete'}:
        abort(404)
    entry = db.session.scalar(select(model).where(model.id == entry_id, model.user_id == current_user.id).with_for_update())
    if not entry or entry.status == 'deleted':
        abort(404)
    if action == 'edit':
        body = text(request.form.get('body'), 2000)
        if entry.updated_at > utc_now() - timedelta(seconds=30):
            raise InventoryError('Vui lòng chờ 30 giây trước khi sửa tiếp.', 429)
        entry.body, entry.status = body, 'pending'
        if kind == 'review':
            bought = db.session.scalar(select(SalesOrderItem.id).join(SalesOrder).where(
                SalesOrderItem.product_id == entry.product_id, SalesOrder.status == 'completed',
                (SalesOrder.created_by == current_user.id) | SalesOrder.customer.has(user_id=current_user.id)).limit(1))
            if not bought:
                abort(403)
            rating = request.form.get('rating', '')
            if rating not in {'1', '2', '3', '4', '5'}:
                abort(422)
            entry.rating = int(rating)
        entry.moderated_by = entry.moderated_at = entry.moderation_reason = None
    else:
        entry.status = 'deleted'
    audit('client_' + action, model, entry.id)
    db.session.commit()
    return redirect(url_for('content.contributions'), code=303)


@blueprint.get('/account/contributions')
@client_required
def contributions():
    reviews = db.session.scalars(select(ProductReview).where(ProductReview.user_id == current_user.id,
                               ProductReview.status != 'deleted').order_by(ProductReview.id.desc()).limit(100)).all()
    comments = db.session.scalars(select(BlogComment).where(BlogComment.user_id == current_user.id,
                                BlogComment.status != 'deleted').order_by(BlogComment.id.desc()).limit(100)).all()
    return render_template('features/contributions.html', reviews=reviews, comments=comments)


@blueprint.route('/business/moderation', methods=['GET', 'POST'])
@business_required
def moderation():
    if request.method == 'POST':
        model = CONTRIBUTIONS.get(request.form.get('kind'))
        raw = request.form.get('id', '')
        status = request.form.get('status')
        if not model or not re.fullmatch(r'[0-9]{1,19}', raw) or status not in {'visible', 'hidden', 'deleted'}:
            abort(422)
        entry = db.session.scalar(select(model).where(model.id == int(raw)).with_for_update())
        if not entry or entry.status == 'deleted':
            abort(404)
        entry.status, entry.moderated_by, entry.moderated_at = status, current_user.id, utc_now()
        entry.moderation_reason = text(request.form.get('reason'), 500, False)
        audit('moderate_' + status, model, entry.id, entry.moderation_reason or None)
        db.session.commit()
        return redirect(url_for('content.moderation'), code=303)
    state = request.args.get('status', 'pending')
    if state not in {'pending', 'visible', 'hidden', 'deleted'}:
        abort(400)
    reviews = db.session.scalars(select(ProductReview).where(ProductReview.status == state).order_by(ProductReview.id.desc()).limit(100)).all()
    comments = db.session.scalars(select(BlogComment).where(BlogComment.status == state).order_by(BlogComment.id.desc()).limit(100)).all()
    summary = db.session.execute(select(ProductReview.status, func.count(), func.avg(ProductReview.rating)).group_by(ProductReview.status)).all() if current_user.role == 'admin' else []
    return render_template('features/moderation.html', reviews=reviews, comments=comments, summary=summary, state=state, active_page='content')
