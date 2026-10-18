from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user
from itsdangerous import URLSafeTimedSerializer, BadSignature
from sqlalchemy import select, or_, case

from app.auth.permissions import business_required, admin_required
from app.extensions import db
from app.models import SalesOrderItem, WarrantyCoverage, WarrantyDevice, WarrantyTicket, WarrantyEvent, User
from app.services.inventory_service import InventoryError
from app.services.warranty_service import (STATES,NEXT,coverage_state,ticket_scope,lookup_query,
    new_ticket_code,create_ticket,handle_ticket,verify_legacy)
from app.warranties.forms import IntakeForm, HandlingForm, AssignmentForm, LegacyForm

blueprint=Blueprint('warranties',__name__,url_prefix='/business/warranties')


def context(**values):
    return dict(active_page='warranties',workspace_home=url_for('dashboard.staff'),states=STATES,coverage_state=coverage_state,**values)


def page_number():
    try:
        page=int(request.args.get('page',1))
        if not 1<=page<=2147483647: raise ValueError
        return page
    except ValueError: abort(400)


def term():
    value=request.args.get('q','').strip()
    if len(value)>120: abort(400)
    return value


def item_for_intake(item_id):
    item=db.session.get(SalesOrderItem,item_id)
    if not item or item.order.status!='completed': abort(404)
    return item


def record_for_actor(ticket_id):
    record=db.session.scalar(ticket_scope(current_user).where(WarrantyTicket.id==ticket_id))
    if not record: abort(404)
    return record


def detail_context(record, form=None, assignment=None, message=None):
    form=form or HandlingForm()
    assignment=assignment or AssignmentForm()
    allowed=NEXT[record.status]
    form.target.choices=[(key,label) for key,label in HandlingForm.target.kwargs['choices'] if key in allowed]
    if request.method=='GET':
        form.expected_status.data=record.status;assignment.expected_status.data=record.status
    assignment.assignee.choices=[(0,'Chọn người phụ trách')]+[(u.id,u.full_name+' · '+u.role) for u in db.session.scalars(
        select(User).where(User.is_active.is_(True)).order_by(User.full_name)) if u.has_permission('warranty')] if current_user.role=='admin' else []
    if request.method=='GET':
        assignment.assignee.data=record.assigned_to if record.assigned_to in dict(assignment.assignee.choices) else 0
    events=db.session.scalars(select(WarrantyEvent).where(WarrantyEvent.ticket_id==record.id).order_by(WarrantyEvent.id.desc()).limit(50)).all()
    return context(record=record,form=form,assignment=assignment,events=events,message=message)


@blueprint.get('')
@business_required
def index():
    q=term(); status=request.args.get('status','')
    if status and status not in STATES: abort(400)
    query=ticket_scope(current_user).join(WarrantyDevice).join(WarrantyCoverage).join(SalesOrderItem)
    if q:
        from app.models import SalesOrder
        query=query.join(SalesOrder).where(or_(*(f.contains(q,autoescape=True) for f in (
            WarrantyTicket.ticket_code,WarrantyTicket.customer_name,WarrantyTicket.customer_phone,
            WarrantyTicket.product_sku,WarrantyDevice.serial,SalesOrder.order_code))))
    if status: query=query.where(WarrantyTicket.status==status)
    results=db.paginate(query.order_by(WarrantyTicket.id.desc()),page=page_number(),per_page=10,error_out=False)
    return render_template('warranties/index.html',**context(results=results,q=q,status=status))


@blueprint.get('/lookup')
@business_required
def lookup():
    q=term();page=page_number();rows=[];has_next=False;devices={}
    if q:
        rows=db.session.execute(lookup_query(q).offset((page-1)*10).limit(11)).all()
        has_next=len(rows)>10;rows=rows[:10]
        for item,coverage in rows:
            devices[item.id]=db.session.scalars(select(WarrantyDevice).where(WarrantyDevice.coverage_id==coverage.id)
                .order_by(case((WarrantyDevice.serial.contains(q.upper(),autoescape=True),0),else_=1),WarrantyDevice.unit_index).limit(10)).all() if coverage else []
    return render_template('warranties/lookup.html',**context(rows=rows,devices=devices,q=q,page=page,has_next=has_next,active_lookup=True))


@blueprint.route('/new/<int:item_id>',methods=['GET','POST'])
@business_required
def create(item_id):
    item=item_for_intake(item_id)
    coverage=db.session.scalar(select(WarrantyCoverage).where(WarrantyCoverage.sale_item_id==item_id))
    form=IntakeForm();message=None;status=200
    serializer=URLSafeTimedSerializer(current_app.secret_key,salt='warranty-intake')
    if request.method=='GET':
        form.ticket.data=serializer.dumps(dict(code=new_ticket_code(),actor=current_user.id,item=item_id))
        if request.args.get('unit_index'):
            try:
                unit=int(request.args['unit_index'])
                if not 1<=unit<=item.quantity:raise ValueError
            except ValueError:abort(400)
            form.unit_index.data=unit
            device=db.session.scalar(select(WarrantyDevice).where(WarrantyDevice.coverage_id==coverage.id,WarrantyDevice.unit_index==unit)) if coverage else None
            if device:form.serial.data=device.serial
    if form.validate_on_submit():
        try:
            payload=serializer.loads(form.ticket.data,max_age=7200)
            if payload.get('actor')!=current_user.id or payload.get('item')!=item_id: raise BadSignature('scope')
            identifier=create_ticket(current_user.id,item_id,form.unit_index.data,form.serial.data,
                form.issue.data,form.promised_on.data,code=payload['code'])
            db.session.rollback();flash('Đã tiếp nhận yêu cầu. Cần kiểm tra trước khi chấp nhận bảo hành.','success')
            return redirect(url_for('warranties.detail',ticket_id=identifier),code=303)
        except BadSignature:message,status='Form hết hạn hoặc không hợp lệ. Mở form mới để tiếp tục.',422
        except InventoryError as error:message,status=error.message,error.status
    elif request.method=='POST':message,status='Thông tin chưa hợp lệ. Kiểm tra các trường bên dưới.',422
    return render_template('warranties/form.html',**context(item=item,coverage=coverage,form=form,message=message)),status


@blueprint.route('/legacy/<int:item_id>',methods=['GET','POST'])
@admin_required
def legacy(item_id):
    item=item_for_intake(item_id);form=LegacyForm();message=None;status=200
    if form.validate_on_submit():
        try:
            verify_legacy(current_user.id,item_id,form.starts_on.data,form.months.data,form.reason.data,form.notes.data)
            db.session.rollback();flash('Đã lưu căn cứ và chính sách đơn cũ; snapshot đơn bán giữ nguyên.','success')
            return redirect(url_for('warranties.create',item_id=item_id),code=303)
        except InventoryError as error:message,status=error.message,error.status
    elif request.method=='POST':message,status='Thông tin chưa hợp lệ.',422
    return render_template('warranties/legacy.html',**context(item=item,form=form,message=message)),status


@blueprint.get('/<int:ticket_id>')
@business_required
def detail(ticket_id):
    return render_template('warranties/detail.html',**detail_context(record_for_actor(ticket_id)))


@blueprint.post('/<int:ticket_id>/handle')
@business_required
def handle(ticket_id):
    record=record_for_actor(ticket_id);form=HandlingForm()
    # Validate against all known actions; the service checks the current state under lock.
    message='Thông tin chưa hợp lệ.';status=422
    if form.validate_on_submit() and form.confirmed.data=='yes':
        try:
            handle_ticket(current_user.id,ticket_id,form.target.data,form.expected_status.data,
                result=form.inspection_result.data,reason=form.rejection_reason.data,note=form.note.data)
            db.session.rollback();flash('Đã cập nhật phiếu và lịch sử xử lý.','success')
            return redirect(url_for('warranties.detail',ticket_id=ticket_id),code=303)
        except InventoryError as error:message,status=error.message,error.status
    db.session.rollback();record=record_for_actor(ticket_id)
    return render_template('warranties/detail.html',**detail_context(record,form=form,message=message)),status


@blueprint.post('/<int:ticket_id>/assign')
@admin_required
def assign(ticket_id):
    record=record_for_actor(ticket_id);form=AssignmentForm()
    form.assignee.choices=[(u.id,u.full_name) for u in db.session.scalars(select(User).where(User.is_active.is_(True))) if u.has_permission('warranty')]
    message='Người phụ trách chưa hợp lệ.';status=422
    if form.validate_on_submit():
        try:
            handle_ticket(current_user.id,ticket_id,'assign',form.expected_status.data,assignee=form.assignee.data)
            db.session.rollback();flash('Đã phân công xử lý.','success')
            return redirect(url_for('warranties.detail',ticket_id=ticket_id),code=303)
        except InventoryError as error:message,status=error.message,error.status
    db.session.rollback();record=record_for_actor(ticket_id)
    return render_template('warranties/detail.html',**detail_context(record,assignment=form,message=message)),status
