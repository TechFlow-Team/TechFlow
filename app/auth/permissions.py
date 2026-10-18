from functools import wraps

from flask import abort, request
from flask_login import current_user, login_required


def role_required(*roles):
    def decorate(view):
        @wraps(view)
        @login_required
        def protected(*args, **kwargs):
            if current_user.role not in roles:
                abort(403)
            if current_user.role == 'staff':
                group = {'sales': 'orders', 'customers': 'orders', 'products': 'inventory',
                         'categories': 'inventory', 'businesses': 'inventory', 'inventory': 'inventory',
                         'purchases': 'inventory', 'warranties': 'warranty', 'content': 'content',
                         'support': 'support'}.get(request.blueprint)
                if request.endpoint == 'operations.reports':
                    group = 'reports'
                elif request.blueprint == 'operations':
                    group = 'inventory'
                if group and not current_user.has_permission(group):
                    abort(403)
            return view(*args, **kwargs)
        return protected
    return decorate


admin_required = role_required("admin")
business_required = role_required("admin", "staff")
client_required = role_required("client")

TASK_GROUPS = {'orders': 'Xử lý đơn hàng', 'inventory': 'Quản lý kho và catalog',
               'content': 'Soạn bài và kiểm duyệt', 'warranty': 'Xử lý bảo hành',
               'support': 'Hỗ trợ khách hàng', 'reports': 'Xem báo cáo kinh doanh'}
