from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.auth.permissions import admin_required, TASK_GROUPS
from app.extensions import db
from app.models import AuditLog, User
from app.services.account_service import create_staff
from app.services.workspace_service import database_available
from app.users.forms import StaffCreateForm, StaffStateForm

blueprint = Blueprint("admin", __name__)


@blueprint.get("/admin")
@admin_required
def index():
    return redirect(url_for("admin.dashboard"))


@blueprint.get("/admin/dashboard")
@admin_required
def dashboard():
    return render_template("admin/dashboard.html", active_page="dashboard",
                           database_ok=database_available())


@blueprint.route("/admin/staff", methods=["GET", "POST"])
@admin_required
def staff_accounts():
    form = StaffCreateForm()
    message = None
    if form.validate_on_submit():
        try:
            user = create_staff(form.username.data, form.full_name.data, form.password.data, form.email.data,
                                created_by_id=current_user.id)
            db.session.commit()
            flash(f"Đã tạo tài khoản Staff {user.username}.", "success")
            return redirect(url_for("admin.staff_accounts"), code=303)
        except IntegrityError:
            db.session.rollback()
            message = "Username hoặc email đã được sử dụng."
        except ValueError as error:
            db.session.rollback()
            message = str(error)
    elif form.is_submitted():
        message = "Thông tin chưa hợp lệ. Vui lòng kiểm tra lại."
    staff = db.session.scalars(select(User).where(User.role == "staff").order_by(User.full_name, User.id)).all()
    return render_template("admin/staff.html", active_page="staff", form=form, state_form=StaffStateForm(),
                           staff_accounts=staff, message=message, task_groups=TASK_GROUPS)


@blueprint.post("/admin/staff/<int:user_id>/toggle")
@admin_required
def toggle_staff(user_id):
    form = StaffStateForm()
    if not form.validate_on_submit():
        return "Yêu cầu chưa hợp lệ.", 400
    user = db.get_or_404(User, user_id)
    if user.role != "staff" or user.id == current_user.id:
        return "Không thể thay đổi tài khoản này.", 403
    user.is_active = not user.is_active
    db.session.add(AuditLog(user_id=current_user.id, action="activate_staff" if user.is_active else "deactivate_staff",
                            entity_type="user", entity_id=user.id, description="Admin thay đổi trạng thái tài khoản Staff."))
    db.session.commit()
    flash(f"Đã {'kích hoạt' if user.is_active else 'vô hiệu hóa'} tài khoản {user.username}.", "success")
    return redirect(url_for("admin.staff_accounts"), code=303)


@blueprint.post('/admin/staff/<int:user_id>/permissions')
@admin_required
def staff_permissions(user_id):
    groups = request.form.getlist('groups')
    if set(groups) - TASK_GROUPS.keys():
        abort(422)
    user = db.get_or_404(User, user_id)
    if user.role != 'staff':
        abort(403)
    user.task_groups = ','.join(sorted(set(groups)))
    db.session.add(AuditLog(user_id=current_user.id, action='staff_permissions', entity_type='users',
                           entity_id=user.id, description='Nhóm quyền: ' + user.task_groups))
    db.session.commit()
    flash('Đã cập nhật quyền; áp dụng từ yêu cầu tiếp theo của nhân viên.', 'success')
    return redirect(url_for('admin.staff_accounts'), code=303)
