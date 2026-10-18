from sqlalchemy.dialects.mysql import INTEGER

from app.extensions import db
from app.models.base import Record, TABLE_OPTIONS, Timestamps, foreign_id


class SalesOrder(Record, Timestamps, db.Model):
    __tablename__ = "sales_orders"
    __table_args__ = (
        db.CheckConstraint("status IN ('draft', 'completed', 'cancelled')", name="valid_status"),
        db.CheckConstraint("total_amount >= 0", name="total_nonnegative"),
        db.Index('ix_sales_orders_customer_status_date', 'customer_id', 'status', 'order_date'),
        TABLE_OPTIONS,
    )
    order_code = db.Column(db.String(40), nullable=False, unique=True)
    customer_name = db.Column(db.String(150), nullable=False)
    customer_phone = db.Column(db.String(30))
    customer_email = db.Column(db.String(190))
    customer_address = db.Column(db.String(255))
    customer_id = foreign_id('customers.id', nullable=True)
    customer = db.relationship('Customer', back_populates='orders')
    created_by = foreign_id("users.id")
    order_date = db.Column(db.DateTime, nullable=False, index=True)
    completed_at = db.Column(db.DateTime)
    status = db.Column(db.String(20), nullable=False, default="draft", server_default="draft", index=True)
    total_amount = db.Column(db.Numeric(14, 2), nullable=False, default=0, server_default="0")
    notes = db.Column(db.Text)
    fulfillment_status = db.Column(db.String(20), nullable=False, default='waiting', server_default='waiting')
    events = db.relationship('OrderEvent', order_by='OrderEvent.id', passive_deletes='all')
    creator = db.relationship("User", back_populates="sales_orders")
    items = db.relationship("SalesOrderItem", back_populates="order", passive_deletes="all")


class SalesOrderItem(Record, db.Model):
    __tablename__ = "sales_order_items"
    __table_args__ = (
        db.CheckConstraint("quantity > 0", name="quantity_positive"),
        db.CheckConstraint("unit_price >= 0", name="unit_price_nonnegative"),
        db.CheckConstraint("line_total = quantity * unit_price", name="correct_line_total"),
        TABLE_OPTIONS,
    )
    order_id = foreign_id("sales_orders.id")
    product_id = foreign_id("products.id")
    quantity = db.Column(INTEGER(unsigned=True), nullable=False)
    unit_price = db.Column(db.Numeric(14, 2), nullable=False)
    line_total = db.Column(db.Numeric(14, 2), nullable=False)
    order = db.relationship("SalesOrder", back_populates="items")
    product = db.relationship("Product", back_populates="sale_items")
