from app.extensions import db
from app.models.base import Record, Timestamps, TABLE_OPTIONS, foreign_id


class Favorite(Record, db.Model):
    __tablename__ = 'favorites'
    __table_args__ = (db.UniqueConstraint('user_id', 'product_id'), TABLE_OPTIONS)
    user_id = foreign_id('users.id')
    product_id = foreign_id('products.id')
    product = db.relationship('Product')


class SupportConversation(Record, Timestamps, db.Model):
    __tablename__ = 'support_conversations'
    __table_args__ = (db.CheckConstraint("status IN ('new','processing','closed')", name='valid_status'), TABLE_OPTIONS)
    user_id = foreign_id('users.id')
    order_id = foreign_id('sales_orders.id', nullable=True)
    assigned_to = foreign_id('users.id', nullable=True)
    subject = db.Column(db.String(150), nullable=False)
    status = db.Column(db.String(20), nullable=False, default='new', server_default='new', index=True)
    user = db.relationship('User', foreign_keys=[user_id])
    assignee = db.relationship('User', foreign_keys=[assigned_to])
    order = db.relationship('SalesOrder')


class SupportMessage(Record, db.Model):
    __tablename__ = 'support_messages'
    __table_args__ = (TABLE_OPTIONS,)
    conversation_id = foreign_id('support_conversations.id')
    user_id = foreign_id('users.id')
    body = db.Column(db.String(2000), nullable=False)
    user = db.relationship('User')
