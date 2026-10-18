"""Shared server-rendered transaction screens, scoped before pagination/detail."""
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from flask import Blueprint, abort, current_app, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from sqlalchemy import or_, select, func, case
from sqlalchemy.orm import selectinload

from app.auth.permissions import business_required
from app.extensions import db
from app.models import Business, Product, Customer, AuditLog, User
from app.purchases.forms import TransactionForm, ActionForm
from app.services.inventory_service import InventoryError
from app.services.customer_service import DuplicateCustomer
from app.services.transaction_service import MODELS, new_code, permitted, create_document, transition


def build_transaction_blueprint(kind):
    blueprint = Blueprint(kind, __name__, url_prefix='/business/' + kind)
    model, _, code_field, _ = MODELS[kind]
    title = 'Phiếu nhập kho' if kind == 'purchases' else 'Đơn bán hàng'

    def scope():
        if kind == 'purchases' and current_user.role != 'admin':
            abort(403)
        query = select(model)
        if current_user.role != 'admin':
            if kind == 'sales' and current_user.role == 'staff':
                client_ids = select(User.id).where(User.role == 'client')
                query = query.where((model.created_by == current_user.id) | model.created_by.in_(client_ids))
            else:
                query = query.where(model.created_by == current_user.id)
        return query

    def context(**values):
        return dict(kind=kind, label=title, active_page=kind, workspace_home=url_for('dashboard.staff'),
                    code_field=code_field, status_labels={'draft':'Bản nháp','completed':'Hoàn thành','cancelled':'Đã hủy'}, **values)

    def document_or_404(identifier):
        record = db.session.scalar(scope().where(model.id == identifier).options(selectinload(model.items)))
        if not record:
            abort(404)
        return record

    def progress_dates(record):
        # Called only after document_or_404 has enforced the existing scope.
        # Return operation timestamps, never audit descriptions or actor details.
        completed, cancelled = db.session.execute(select(
            func.min(case((AuditLog.action == 'complete', AuditLog.created_at))),
            func.min(case((AuditLog.action == 'cancel', AuditLog.created_at))),
        ).where(AuditLog.entity_type == model.__tablename__, AuditLog.entity_id == record.id)).one()
        return dict(completed_at=record.completed_at if kind == 'sales' and record.completed_at else completed,
                    cancelled_at=cancelled)

    @blueprint.get('')
    @business_required
    def index():
        query = scope()
        q = request.args.get('q', '').strip()
        status = request.args.get('status', '')
        if len(q) > 120 or status not in {'','draft','completed','cancelled'}:
            abort(400)
        if q:
            fields = [getattr(model, code_field)]
            if kind == 'sales':
                fields.append(model.customer_name)
            query = query.where(or_(*(field.contains(q, autoescape=True) for field in fields)))
        if status:
            query = query.where(model.status == status)
        if request.args.get('business_id'):
            try:
                identifier = int(request.args['business_id'])
                if kind != 'purchases' or identifier < 1:
                    raise ValueError
            except ValueError:
                abort(400)
            query = query.where(model.business_id == identifier)
        date_field = model.receipt_date if kind == 'purchases' else model.order_date
        for key in ['from','to']:
            if request.args.get(key):
                try:
                    day = datetime.strptime(request.args[key], '%Y-%m-%d').date()
                    boundary = datetime.combine(day, time.min, ZoneInfo('Asia/Ho_Chi_Minh'))
                    if key == 'to':
                        boundary += timedelta(days=1)
                    boundary = boundary.astimezone(ZoneInfo('UTC')).replace(tzinfo=None)
                except (ValueError, OverflowError):
                    abort(400)
                query = query.where(date_field >= boundary if key == 'from' else date_field < boundary)
        try:
            page = int(request.args.get('page', 1))
            if not 1 <= page <= 2147483647:
                raise ValueError
        except ValueError:
            abort(400)
        results = db.paginate(query.order_by(model.id.desc()), page=page, per_page=10, error_out=False)
        return render_template('transactions/index.html', **context(results=results,
            suppliers=db.session.scalars(select(Business).order_by(Business.name)).all() if kind == 'purchases' else []))

    @blueprint.get('/products')
    @business_required
    def options():
        scope()
        q = request.args.get('q','').strip()
        if len(q) > 120:
            abort(400)
        query = select(Product).where(Product.is_active.is_(True))
        if q:
            query = query.where(or_(Product.sku.contains(q, autoescape=True), Product.name.contains(q, autoescape=True)))
        rows = db.session.scalars(query.order_by(Product.name,Product.id).limit(50)).all()
        return jsonify([dict(id=p.id, label=p.sku+' · '+p.name, stock=p.stock_quantity,
            price=str(p.purchase_price if kind == 'purchases' else p.selling_price)) for p in rows])

    @blueprint.route('/new', methods=['GET','POST'])
    @business_required
    def create():
        scope()
        form = TransactionForm()
        customers = []
        if kind == 'sales':
            customers = db.session.scalars(select(Customer).where(Customer.is_active.is_(True)).order_by(Customer.name).limit(20)).all()
            if request.method == 'GET' and request.args.get('customer_id'):
                try:
                    chosen_id = int(request.args['customer_id'])
                    if not 1 <= chosen_id <= 2147483647: raise ValueError
                except ValueError:
                    abort(400)
                chosen = db.session.get(Customer,chosen_id)
                if not chosen or not chosen.is_active: abort(404)
                form.customer_mode.data = 'existing'
                form.customer_id.data = chosen.id
            if form.customer_id.data and 0 < form.customer_id.data <= 2147483647:
                chosen = db.session.get(Customer,form.customer_id.data)
                if chosen and chosen.is_active:
                    customers = list({c.id:c for c in customers+[chosen]}.values())
                    if request.method == 'GET':
                        form.customer_name.data,form.customer_phone.data = chosen.name,chosen.phone
                        form.customer_email.data,form.customer_address.data = chosen.email,chosen.address
            form.customer_id.choices = [(0,'Chưa chọn hồ sơ')] + [(c.id,c.name+' · '+c.phone) for c in customers]
        else:
            form.customer_id.choices = [(0,'')]
        serializer = URLSafeTimedSerializer(current_app.secret_key, salt='inventory-create')
        if request.method == 'GET':
            form.ticket.data = serializer.dumps(dict(code=new_code(kind), actor=current_user.id, kind=kind))
            form.lines[0].quantity.data = 1
        # Populate selected rows too, so validation preserves choices beyond the first page.
        selected = [line.product_id.data for line in form.lines if line.product_id.data and 0 < line.product_id.data <= 18446744073709551615]
        products = db.session.scalars(select(Product).where(Product.is_active.is_(True)).order_by(Product.name).limit(50)).all()
        if selected:
            extra = db.session.scalars(select(Product).where(Product.id.in_(selected))).all()
            products = list({p.id:p for p in products+extra}.values())
        for line in form.lines:
            line.product_id.choices = [(0,'Chọn sản phẩm')] + [(p.id,p.sku+' · '+p.name) for p in products]
        suppliers = db.session.scalars(select(Business).where(Business.is_active.is_(True)).order_by(Business.name)).all() if kind == 'purchases' else []
        form.business_id.choices = [(0,'Chọn nhà cung cấp')] + [(b.id,b.name) for b in suppliers]
        message, status_code, duplicate_customer_id = None, 200, None
        if form.validate_on_submit():
            try:
                payload = serializer.loads(form.ticket.data, max_age=7200)
                if payload.get('actor') != current_user.id or payload.get('kind') != kind:
                    raise BadSignature('Invalid scope')
                # FieldList max_entries must not silently truncate malicious extra rows.
                if len({key.split('-')[1] for key in request.form if key.startswith('lines-') and len(key.split('-')) >= 3}) > 50:
                    raise InventoryError('Tối đa 50 dòng sản phẩm.',422)
                identifier = create_document(kind, current_user.id, form.data,
                    [line.data for line in form.lines], code=payload['code'])
                db.session.rollback()
                flash('Đã tạo bản nháp. Tồn kho chưa thay đổi.', 'success')
                return redirect(url_for(kind+'.detail', record_id=identifier), code=303)
            except (BadSignature, SignatureExpired):
                message, status_code = 'Form đã hết hạn hoặc không hợp lệ. Mở form mới để tiếp tục.', 422
            except InventoryError as error:
                message, status_code = error.message, error.status
                if isinstance(error,DuplicateCustomer):
                    duplicate_customer_id = error.customer_id
        elif request.method == 'POST':
            message, status_code = 'Thông tin chưa hợp lệ. Vui lòng kiểm tra các trường.', 422
        prices = {str(p.id):dict(price=str(p.purchase_price if kind == 'purchases' else p.selling_price),stock=p.stock_quantity) for p in products}
        customer_options = {str(c.id):dict(id=c.id,name=c.name,phone=c.phone,email=c.email or '',address=c.address or '',
            history_url=url_for('customers.detail',customer_id=c.id)) for c in customers}
        return render_template('transactions/form.html', **context(form=form, message=message, prices=prices,customer_options=customer_options,duplicate_customer_id=duplicate_customer_id)), status_code

    @blueprint.get('/<int:record_id>')
    @business_required
    def detail(record_id):
        record = document_or_404(record_id)
        return render_template('transactions/detail.html', **context(record=record, form=ActionForm(),
            progress_dates=progress_dates(record),
            can_cancel=record.status in {'draft','completed'} and permitted(current_user,kind,record,'cancel')))

    @blueprint.post('/<int:record_id>/<action>')
    @business_required
    def act(record_id, action):
        document_or_404(record_id)
        if action not in ({'complete','cancel','confirm','ship','reject','note'} if kind == 'sales' else {'complete','cancel'}):
            abort(404)
        form = ActionForm()
        if not form.validate_on_submit():
            abort(400)
        try:
            transition(kind, current_user.id, record_id, action, request.form.get('note'))
            db.session.rollback()
            flash({'complete': 'Đã hoàn tất và cập nhật tồn kho.', 'cancel': 'Đã hủy giao dịch theo quy tắc đảo kho.',
                   'confirm': 'Đã xác nhận đơn.', 'ship': 'Đã chuyển sang đang giao.',
                   'reject': 'Đã từ chối đơn.', 'note': 'Đã thêm ghi chú vào lịch sử.'}[action], 'success')
        except InventoryError as error:
            if error.status == 403:
                abort(403)
            db.session.rollback()
            record = document_or_404(record_id)
            return render_template('transactions/detail.html', **context(record=record,form=form,
                progress_dates=progress_dates(record),
                can_cancel=record.status in {'draft','completed'} and permitted(current_user,kind,record,'cancel'), message=error.message)), error.status
        return redirect(url_for(kind+'.detail',record_id=record_id),code=303)

    return blueprint
