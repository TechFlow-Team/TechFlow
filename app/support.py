"""Private, reload-based customer support with explicit staff assignment."""
import re
from datetime import timedelta

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy import func, select

from app.auth.permissions import business_required, client_required, role_required
from app.content import text, invalid
from app.extensions import db
from app.models import AuditLog, SalesOrder, SupportConversation, SupportMessage, User
from app.models.base import utc_now
from app.services.inventory_service import InventoryError

blueprint = Blueprint('support', __name__)
blueprint.register_error_handler(InventoryError, invalid)


def scope():
    query = select(SupportConversation)
    if current_user.role == 'client':
        query = query.where(SupportConversation.user_id == current_user.id)
    elif current_user.role == 'staff':
        query = query.where((SupportConversation.assigned_to == current_user.id) | SupportConversation.assigned_to.is_(None))
    return query


def load(identifier, lock=False):
    query = scope().where(SupportConversation.id == identifier)
    thread = db.session.scalar(query.with_for_update() if lock else query)
    if not thread:
        abort(404)
    return thread


def audit(thread, action):
    db.session.add(AuditLog(user_id=current_user.id, action=action, entity_type='support_conversations', entity_id=thread.id))


@blueprint.get('/support')
@role_required('admin', 'staff', 'client')
def inbox():
    state = request.args.get('status', '')
    if state not in {'', 'new', 'processing', 'closed'}:
        abort(400)
    query = scope()
    if state:
        query = query.where(SupportConversation.status == state)
    results = db.paginate(query.order_by(SupportConversation.updated_at.desc(), SupportConversation.id.desc()),
                          per_page=20, max_per_page=20, error_out=False)
    return render_template('features/support_inbox.html', results=results, active_page='support')


@blueprint.route('/support/new', methods=['GET', 'POST'])
@client_required
def create():
    if request.method == 'POST':
        subject, body = text(request.form.get('subject'), 150), text(request.form.get('body'), 2000)
        db.session.scalar(select(User).where(User.id == current_user.id).with_for_update())
        latest = db.session.scalar(select(func.max(SupportConversation.created_at)).where(SupportConversation.user_id == current_user.id))
        if latest and latest > utc_now() - timedelta(seconds=30):
            raise InventoryError('Vui lòng chờ 30 giây trước khi tạo hội thoại tiếp.', 429)
        raw = request.form.get('order_id', '').strip()
        order = None
        if raw:
            if not re.fullmatch(r'[0-9]{1,19}', raw):
                abort(422)
            order = db.session.scalar(select(SalesOrder).where(SalesOrder.id == int(raw),
                (SalesOrder.created_by == current_user.id) | SalesOrder.customer.has(user_id=current_user.id)))
            if not order:
                abort(404)
        thread = SupportConversation(user_id=current_user.id, subject=subject, order_id=order.id if order else None)
        db.session.add(thread)
        db.session.flush()
        db.session.add(SupportMessage(conversation_id=thread.id, user_id=current_user.id, body=body))
        audit(thread, 'support_open')
        db.session.commit()
        return redirect(url_for('support.detail', identifier=thread.id), code=303)
    orders = db.session.scalars(select(SalesOrder).where((SalesOrder.created_by == current_user.id) |
        SalesOrder.customer.has(user_id=current_user.id)).order_by(SalesOrder.id.desc()).limit(100)).all()
    return render_template('features/support_new.html', orders=orders)


@blueprint.route('/support/<int:identifier>', methods=['GET', 'POST'])
@role_required('admin', 'staff', 'client')
def detail(identifier):
    if request.method == 'POST':
        body = text(request.form.get('body'), 2000)
        # Lock sender first, then thread, consistent across all support writes.
        db.session.scalar(select(User).where(User.id == current_user.id).with_for_update())
        thread = load(identifier, lock=True)
        if thread.status == 'closed':
            raise InventoryError('Hội thoại đã đóng. Tạo yêu cầu mới nếu cần hỗ trợ thêm.', 409)
        if current_user.role == 'staff' and thread.assigned_to != current_user.id:
            abort(403)
        latest = db.session.scalar(select(func.max(SupportMessage.created_at)).where(SupportMessage.user_id == current_user.id))
        if latest and latest > utc_now() - timedelta(seconds=10):
            raise InventoryError('Vui lòng chờ 10 giây trước khi gửi tiếp.', 429)
        db.session.add(SupportMessage(conversation_id=thread.id, user_id=current_user.id, body=body))
        thread.updated_at = utc_now()
        audit(thread, 'support_reply')
        db.session.commit()
        return redirect(url_for('support.detail', identifier=thread.id), code=303)
    thread = load(identifier)
    messages = db.paginate(select(SupportMessage).where(SupportMessage.conversation_id == thread.id)
        .order_by(SupportMessage.id.desc()), per_page=50, max_per_page=50, error_out=False)
    staff = db.session.scalars(select(User).where(User.role == 'staff', User.is_active.is_(True)).order_by(User.full_name)).all() if current_user.role == 'admin' else []
    staff = [user for user in staff if user.has_permission('support')]
    return render_template('features/support_detail.html', thread=thread, messages=messages, staff=staff, active_page='support')


@blueprint.post('/support/<int:identifier>/manage')
@business_required
def manage(identifier):
    thread = load(identifier, lock=True)
    action = request.form.get('action')
    if action == 'take':
        if thread.assigned_to is not None or thread.status == 'closed':
            raise InventoryError('Hội thoại đã được nhận hoặc đã đóng.', 409)
        thread.assigned_to, thread.status = current_user.id, 'processing'
    elif action == 'assign' and current_user.role == 'admin':
        raw = request.form.get('assigned_to', '')
        if not re.fullmatch(r'[0-9]{1,19}', raw):
            abort(422)
        user = db.session.get(User, int(raw))
        if not user or user.role != 'staff' or not user.has_permission('support'):
            abort(422)
        thread.assigned_to = user.id
        if thread.status == 'new':
            thread.status = 'processing'
    elif action in {'close', 'reopen'}:
        if current_user.role != 'admin' and thread.assigned_to != current_user.id:
            abort(403)
        if action == 'reopen' and current_user.role != 'admin':
            abort(403)
        thread.status = 'closed' if action == 'close' else 'processing'
    else:
        abort(422)
    audit(thread, 'support_' + action)
    db.session.commit()
    flash('Đã cập nhật hội thoại.', 'success')
    return redirect(url_for('support.detail', identifier=thread.id), code=303)
