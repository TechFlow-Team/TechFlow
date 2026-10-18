from flask import Blueprint, current_app, redirect, render_template, url_for
from flask_login import current_user, login_required
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from app.auth.permissions import business_required
from app.services.dashboard_service import load_dashboard
from sqlalchemy.exc import SQLAlchemyError

blueprint = Blueprint("dashboard", __name__)


@blueprint.app_template_filter("vietnam_time")
def vietnam_time(value):
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(ZoneInfo("Asia/Ho_Chi_Minh")).strftime("%H:%M · %d/%m/%Y")


@blueprint.get("/dashboard")
@login_required
def index():
    endpoint = "admin.dashboard" if current_user.role == "admin" else "dashboard.staff" if current_user.role == "staff" else "shop.index"
    return redirect(url_for(endpoint))


@blueprint.get("/staff/dashboard")
@business_required
def staff():
    if current_user.role == 'staff' and not current_user.has_permission('inventory'):
        return render_template('features/staff_home.html', active_page='dashboard')
    status = 200
    try:
        stats = load_dashboard(current_user.role)
    except SQLAlchemyError:
        current_app.logger.error("Dashboard statistics unavailable")
        stats, status = None, 503
    return render_template("staff/dashboard.html", active_page="dashboard",
                           stats=stats,
                           workspace_home=url_for("dashboard.staff"),
                           today=datetime.now(ZoneInfo("Asia/Ho_Chi_Minh"))), status
