from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from app.extensions import db
from app.models.base import Record, TABLE_OPTIONS, Timestamps


class User(UserMixin, Record, Timestamps, db.Model):
    __tablename__ = "users"
    __table_args__ = (
        db.CheckConstraint("role IN ('admin', 'staff', 'client')", name="valid_role"),
        TABLE_OPTIONS,
    )
    full_name = db.Column(db.String(120), nullable=False)
    username = db.Column(db.String(80), nullable=False, unique=True)
    email = db.Column(db.String(190), unique=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True, server_default=db.true(), index=True)
    last_login_at = db.Column(db.DateTime)
    task_groups = db.Column(db.String(200), nullable=False, default='', server_default='')
    purchase_receipts = db.relationship("PurchaseReceipt", back_populates="creator", passive_deletes="all")
    sales_orders = db.relationship("SalesOrder", back_populates="creator", passive_deletes="all")
    stock_movements = db.relationship("StockMovement", back_populates="creator", passive_deletes="all")
    audit_logs = db.relationship("AuditLog", back_populates="user", passive_deletes="all")
    customer_profile = db.relationship("Customer", back_populates="user", uselist=False, foreign_keys="Customer.user_id")

    def has_permission(self, group):
        return self.is_active and (self.role == 'admin' or self.role == 'staff' and group in (self.task_groups or '').split(','))

    def set_password(self, password: str) -> None:
        if len(password) < 12 or len(password) > 128:
            raise ValueError("Mật khẩu phải có từ 12 đến 128 ký tự.")
        self.password_hash = generate_password_hash(password, method="scrypt")

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)
