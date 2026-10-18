import logging

from flask import Flask, request

from app.config import load_config
from app.extensions import csrf, db, login_manager, migrate
from app.services.image_storage import display_product_image, s3_image_origin


def create_app() -> Flask:
    app = Flask(__name__)
    app.config.update(load_config())
    logging.basicConfig(
        level=app.config["LOG_LEVEL"],
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    db.init_app(app)
    from app import models  # noqa: F401 -- register ORM metadata for migrations

    migrate.init_app(app, db)
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message = "Vui lòng đăng nhập để tiếp tục."
    login_manager.login_message_category = "info"
    login_manager.session_protection = "strong"

    @login_manager.user_loader
    def load_user(user_id):
        if not user_id.isascii() or not user_id.isdigit() or len(user_id) > 20:
            return None
        user = db.session.get(models.User, int(user_id))
        return user if user and user.is_active and user.role in {"admin", "staff", "client"} else None
    csrf.init_app(app)

    from app.main.routes import blueprint
    from app.cli import register_commands
    from app.errors import register_error_handlers

    app.register_blueprint(blueprint)
    from app.auth.routes import blueprint as auth_blueprint
    from app.dashboard.routes import blueprint as dashboard_blueprint
    from app.users.routes import blueprint as admin_blueprint
    app.register_blueprint(auth_blueprint)
    from app.shop.routes import blueprint as shop_blueprint
    app.register_blueprint(shop_blueprint)
    app.register_blueprint(dashboard_blueprint)
    app.register_blueprint(admin_blueprint)
    from app.categories.routes import blueprint as categories_blueprint
    from app.businesses.routes import blueprint as businesses_blueprint
    from app.products.routes import blueprint as products_blueprint
    for catalog_blueprint in (categories_blueprint, businesses_blueprint, products_blueprint):
        app.register_blueprint(catalog_blueprint)
    from app.purchases.routes import blueprint as purchases_blueprint
    from app.sales.routes import blueprint as sales_blueprint
    from app.inventory.routes import blueprint as inventory_blueprint
    for transaction_blueprint in (purchases_blueprint, sales_blueprint, inventory_blueprint):
        app.register_blueprint(transaction_blueprint)
    from app.customers.routes import blueprint as customers_blueprint
    app.register_blueprint(customers_blueprint)
    from app.warranties.routes import blueprint as warranties_blueprint
    app.register_blueprint(warranties_blueprint)
    from app.operations import blueprint as operations_blueprint
    app.register_blueprint(operations_blueprint)
    from app.content import blueprint as content_blueprint
    app.register_blueprint(content_blueprint)
    from app.engagement import blueprint as engagement_blueprint
    from app.support import blueprint as support_blueprint
    app.register_blueprint(engagement_blueprint)
    app.register_blueprint(support_blueprint)

    @app.template_filter("vnd")
    def format_vnd(value):
        return format(value, ",.2f").replace(",", "_").replace(".", ",").replace("_", ".") + " ₫"

    app.add_template_filter(display_product_image, "product_image")

    @app.context_processor
    def feature_context():
        return {'support_labels': {'new': 'Mới', 'processing': 'Đang xử lý', 'closed': 'Đã đóng'},
                'post_labels': {'draft': 'Nháp', 'published': 'Đã đăng', 'hidden': 'Ẩn'},
                'contribution_labels': {'pending': 'Chờ duyệt', 'visible': 'Hiển thị', 'hidden': 'Ẩn', 'deleted': 'Đã xóa'},
                'fulfillment_labels': {'waiting': 'Chờ xác nhận', 'confirmed': 'Đã xác nhận',
                'shipping': 'Đang giao', 'completed': 'Hoàn tất', 'cancelled': 'Đã hủy', 'rejected': 'Bị từ chối'}}

    register_commands(app)
    register_error_handlers(app)

    @app.after_request
    def security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        # Permit product URLs and the configured private S3 image origin where needed.
        image_sources = "'self' data:"
        if request.blueprint == "products":
            image_sources += " https: http:"
        elif request.blueprint in {"shop", "content"}:
            image_sources += " https:"
        s3_origin = s3_image_origin(app)
        if s3_origin:
            image_sources += " " + s3_origin
        response.headers["Content-Security-Policy"] = f"default-src 'self'; style-src 'self'; script-src 'self'; font-src 'self'; img-src {image_sources}; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'"
        if response.mimetype == "text/html":
            response.headers["Cache-Control"] = "no-store"
        return response

    return app
