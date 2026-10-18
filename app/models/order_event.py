from app.extensions import db
from app.models.base import Record, TABLE_OPTIONS, foreign_id


class OrderEvent(Record, db.Model):
    __tablename__ = 'order_events'
    __table_args__ = (TABLE_OPTIONS,)
    order_id = foreign_id('sales_orders.id')
    actor_id = foreign_id('users.id', nullable=True)
    status = db.Column(db.String(20), nullable=False)
    note = db.Column(db.String(1000))
    actor = db.relationship('User')
