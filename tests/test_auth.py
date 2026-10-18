import re
import secrets
from concurrent.futures import ThreadPoolExecutor

import pytest
from flask import g
from sqlalchemy import func, select

from app import create_app
from app.extensions import db
from app.models import AuditLog, User


class TestAccount(dict):
    __test__ = False

    def __repr__(self):
        return "<test account credentials redacted>"


@pytest.fixture
def account(mysql_app):
    suffix = secrets.token_hex(7)
    password = secrets.token_urlsafe(24)
    user = User(username=f"auth-{suffix}", email=f"auth-{suffix}@example.invalid",
                full_name="Quản trị kiểm thử", role="admin", is_active=True, task_groups='inventory,orders,warranty')
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    return TestAccount(username=user.username, email=user.email, password=password, id=user.id)


@pytest.fixture
def auth_client(mysql_app):
    # mysql_app keeps an outer context for DB assertions. Each request must still
    # reload current_user as it does in a real server with per-request contexts.
    @mysql_app.before_request
    def reset_test_user_cache():
        g.pop("_login_user", None)
        g.pop("csrf_token", None)
        g.pop("csrf_valid", None)
    return mysql_app.test_client()


def csrf(client, path="/login"):
    response = client.get(path, follow_redirects=True)
    assert response.status_code == 200
    return re.search(r'name="csrf_token"[^>]*value="([^"]+)"', response.text).group(1)


def login(client, account, **overrides):
    data = dict(identity=account["username"], password=account["password"], csrf_token=csrf(client))
    data.update(overrides)
    return client.post("/login", data=data)


@pytest.mark.parametrize("identity", ["username", "email"])
def test_login_success_and_dashboard(auth_client, account, identity):
    response = login(auth_client, account, identity=account[identity].upper())
    assert response.status_code == 302 and response.location == "/admin/dashboard"
    page = auth_client.get(response.location)
    assert page.status_code == 200
    assert "Quản trị kiểm thử" in page.text
    assert "Tổng quan quản trị" in page.text
    assert 'href="/admin/dashboard"' in page.text
    assert account["password"] not in page.text
    assert "password_hash" not in page.text
    user = db.session.get(User, account["id"])
    assert user.last_login_at is not None
    assert db.session.scalar(select(AuditLog.id).where(AuditLog.user_id == user.id, AuditLog.action == "login_success"))


def test_wrong_password_generic_error(auth_client, account, caplog):
    response = login(auth_client, account, password="wrong-password")
    assert response.status_code == 401
    assert "Thông tin đăng nhập không đúng" in response.text
    assert "wrong-password" not in response.text + caplog.text
    assert auth_client.get("/dashboard").status_code == 302


def test_unknown_user_same_error(auth_client, account):
    response = login(auth_client, account, identity=f"missing-{secrets.token_hex(8)}")
    assert response.status_code == 401
    assert "Thông tin đăng nhập không đúng" in response.text


def test_inactive_user_cannot_login(auth_client, account):
    user = db.session.get(User, account["id"])
    user.is_active = False
    db.session.commit()
    assert login(auth_client, account).status_code == 401
    assert auth_client.get("/dashboard").status_code == 302


def test_staff_backend_denies_admin(auth_client, account):
    user = db.session.get(User, account["id"])
    user.role = "staff"
    db.session.commit()
    assert login(auth_client, account).status_code == 302
    page = auth_client.get("/dashboard", follow_redirects=True)
    assert page.status_code == 200 and "Tổng quan dành cho nhân viên" in page.text
    assert 'href="/admin"' not in page.text
    denied = auth_client.get("/admin")
    assert denied.status_code == 403 and "Bạn không có quyền truy cập" in denied.text


def test_admin_can_access_admin_space(auth_client, account):
    login(auth_client, account)
    legacy = auth_client.get("/admin")
    assert legacy.status_code == 302 and legacy.location == "/admin/dashboard"
    response = auth_client.get(legacy.location)
    assert response.status_code == 200
    assert "Vai trò và phân quyền" in response.text


@pytest.mark.parametrize("path", ["/dashboard", "/admin", "/admin/dashboard", "/staff/dashboard"])
def test_anonymous_protected_routes(auth_client, path):
    response = auth_client.get(path)
    assert response.status_code == 302 and response.location.startswith("/login?")


def test_logout_post_csrf_and_session_removed(auth_client, account):
    login(auth_client, account)
    assert auth_client.get("/logout").status_code == 405
    assert auth_client.post("/logout").status_code == 400
    token = csrf(auth_client, "/dashboard")
    response = auth_client.post("/logout", data={"csrf_token": token})
    assert response.status_code == 302 and response.location == "/login"
    assert auth_client.get("/dashboard").status_code == 302
    with auth_client.session_transaction() as session:
        assert "_user_id" not in session


def test_login_csrf_required(auth_client, account):
    response = auth_client.post("/login", data={"identity": account["username"], "password": account["password"]})
    assert response.status_code == 400
    assert auth_client.get("/dashboard").status_code == 302


@pytest.mark.parametrize("destination", ["https://evil.example", "//evil.example", "/\\evil.example", "javascript:alert(1)", "/%2f%2fevil.example"])
def test_external_redirect_rejected(auth_client, account, destination):
    response = login(auth_client, account, next=destination)
    assert response.location == "/admin/dashboard"


def test_allowed_internal_redirect(auth_client, account):
    assert login(auth_client, account, next="/admin").location == "/admin/dashboard"


def test_session_replaced_and_cookie_flags(auth_client, account):
    token = csrf(auth_client)
    with auth_client.session_transaction() as session:
        session["pre_login_marker"] = "discard-me"
    response = auth_client.post("/login", data={"identity": account["username"], "password": account["password"], "csrf_token": token})
    cookie = response.headers["Set-Cookie"]
    assert "HttpOnly" in cookie and "SameSite=Lax" in cookie
    with auth_client.session_transaction() as session:
        assert "pre_login_marker" not in session
        assert "csrf_token" not in session
        assert session["_fresh"]


def test_inactive_existing_session_revoked(auth_client, account):
    login(auth_client, account)
    user = db.session.get(User, account["id"])
    user.is_active = False
    db.session.commit()
    assert auth_client.get("/dashboard").status_code == 302


def test_role_change_applies_next_request(auth_client, account):
    login(auth_client, account)
    user = db.session.get(User, account["id"])
    user.role = "staff"
    db.session.commit()
    assert auth_client.get("/admin").status_code == 403


def test_failure_limit_shared_between_username_email(auth_client, account):
    for number in range(5):
        response = login(auth_client, account, identity=account["username"] if number % 2 == 0 else account["email"], password="incorrect")
        assert response.status_code == 401
    limited = login(auth_client, account)
    assert limited.status_code == 429 and limited.headers["Retry-After"] == "900"
    assert db.session.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.action == "login_failed", AuditLog.description.contains(account["username"]))) == 0


def test_concurrent_failures_serialized(mysql_app, account):
    # Real independent app contexts/connections emulate different Gunicorn workers.
    from app.services.auth_service import authenticate
    def attempt(_):
        application = create_app()
        with application.app_context():
            try:
                user, limited = authenticate(account["username"], "wrong", "127.0.0.1")
                return limited
            finally:
                db.session.remove()
                db.engine.dispose()
    results = list(ThreadPoolExecutor(max_workers=3).map(attempt, range(6)))
    assert results.count(False) == 5 and results.count(True) == 1


def test_login_form_errors_and_no_password_echo(auth_client):
    token = csrf(auth_client)
    response = auth_client.post("/login", data={"csrf_token": token})
    assert response.status_code == 200 and "Vui lòng nhập" in response.text


def test_authenticated_login_redirects(auth_client, account):
    login(auth_client, account)
    assert auth_client.get("/login").location == "/admin/dashboard"


@pytest.mark.parametrize("role, home, other", [
    ("admin", "/admin/dashboard", "/staff/dashboard"),
    ("staff", "/staff/dashboard", "/admin/dashboard"),
])
def test_separate_workspaces_and_legacy_redirects(auth_client, account, role, home, other):
    user = db.session.get(User, account["id"])
    user.role = role
    db.session.commit()
    response = login(auth_client, account, next=other)
    assert response.status_code == 302 and response.location == home
    assert auth_client.get("/dashboard").location == home
    assert auth_client.get("/login").location == home
    page = auth_client.get(home)
    assert page.status_code == 200 and f'{role}-workspace' in page.text
    assert auth_client.get(other).status_code == (200 if role == "admin" else 403)
    missing = auth_client.get("/missing-workspace")
    assert missing.status_code == 404 and f'{role}-workspace' in missing.text
    if role == "staff":
        assert "/admin/dashboard" not in page.text
        assert "Báo cáo doanh thu nâng cao chưa triển khai" in page.text
        assert 'href="/business/sales"' in page.text
        assert "Phiên bản giữa kỳ" not in page.text
        assert 'href="/business/purchases"' not in page.text
        assert 'href="/business/inventory"' in page.text
    else:
        assert "business-shortcuts" not in page.text
        assert "Kết nối thành công" in page.text
        assert 'href="/staff/dashboard"' in page.text
    token = csrf(auth_client, home)
    assert auth_client.post("/logout", data={"csrf_token": token}).location == "/login"
    assert auth_client.get(home).location.startswith("/login?")


def test_admin_switches_workspaces_without_session_or_role_change(auth_client, account):
    login(auth_client, account)
    token = csrf(auth_client, "/admin/dashboard")
    with auth_client.session_transaction() as session:
        original_user = session["_user_id"]
        original_csrf = session["csrf_token"]
        original_identifier = session["_id"]
    audit_before = db.session.scalar(select(func.count()).select_from(AuditLog))
    business = auth_client.get("/staff/dashboard")
    assert business.status_code == 200 and 'staff-workspace' in business.text
    assert "Quay về quản trị" in business.text
    assert "Quản trị viên" in business.text
    assert 'href="/staff/dashboard"' in business.text
    assert 'data-kpi="products"' in business.text
    assert auth_client.get("/admin/dashboard").status_code == 200
    assert db.session.get(User, account["id"]).role == "admin"
    assert db.session.scalar(select(func.count()).select_from(AuditLog)) == audit_before
    with auth_client.session_transaction() as session:
        assert session["_user_id"] == original_user
        assert session["csrf_token"] == original_csrf
        assert session["_id"] == original_identifier and session["_fresh"]
    assert auth_client.post("/logout", data={"csrf_token": token}).location == "/login"


def test_admin_dashboard_database_error_state(auth_client, account):
    from unittest.mock import patch
    login(auth_client, account)
    with patch("app.users.routes.database_available", return_value=False):
        page = auth_client.get("/admin/dashboard")
    assert page.status_code == 200 and "Chưa kết nối được" in page.text


def test_database_check_handles_connection_failure(mysql_app):
    from unittest.mock import patch
    from sqlalchemy.exc import OperationalError
    from app.services.workspace_service import database_available
    with patch("app.services.workspace_service.db.engine.connect", side_effect=OperationalError("SELECT 1", {}, Exception("private-error"))):
        assert database_available() is False


def test_missing_or_corrupt_user_session_rejected(auth_client):
    with auth_client.session_transaction() as session:
        session["_user_id"] = "not-an-id"
    assert auth_client.get("/dashboard").status_code == 302
