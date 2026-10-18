from app.extensions import db
from app.models.base import Record, TABLE_OPTIONS, Timestamps, foreign_id


post_products = db.Table('post_products',
    db.Column('post_id', db.ForeignKey('blog_posts.id', ondelete='RESTRICT'), primary_key=True),
    db.Column('product_id', db.ForeignKey('products.id', ondelete='RESTRICT'), primary_key=True),
    **TABLE_OPTIONS)


class BlogPost(Record, Timestamps, db.Model):
    __tablename__ = 'blog_posts'
    __table_args__ = (db.CheckConstraint("status IN ('draft','published','hidden')", name='valid_status'), TABLE_OPTIONS)
    title = db.Column(db.String(200), nullable=False)
    slug = db.Column(db.String(200), nullable=False, unique=True)
    body = db.Column(db.Text, nullable=False)
    cover_url = db.Column(db.String(500))
    author_id = foreign_id('users.id')
    status = db.Column(db.String(20), nullable=False, default='draft', server_default='draft', index=True)
    published_at = db.Column(db.DateTime)
    author = db.relationship('User')
    products = db.relationship('Product', secondary=post_products)


class BlogComment(Record, Timestamps, db.Model):
    __tablename__ = 'blog_comments'
    __table_args__ = (db.CheckConstraint("status IN ('pending','visible','hidden','deleted')", name='valid_status'), TABLE_OPTIONS)
    post_id = foreign_id('blog_posts.id')
    user_id = foreign_id('users.id')
    body = db.Column(db.String(2000), nullable=False)
    status = db.Column(db.String(20), nullable=False, default='pending', server_default='pending', index=True)
    moderated_by = foreign_id('users.id', nullable=True)
    moderated_at = db.Column(db.DateTime)
    moderation_reason = db.Column(db.String(500))
    user = db.relationship('User', foreign_keys=[user_id])
    post = db.relationship('BlogPost')


class ProductReview(Record, Timestamps, db.Model):
    __tablename__ = 'product_reviews'
    __table_args__ = (db.UniqueConstraint('user_id', 'product_id'),
        db.CheckConstraint('rating BETWEEN 1 AND 5', name='rating_range'),
        db.CheckConstraint("status IN ('pending','visible','hidden','deleted')", name='valid_status'), TABLE_OPTIONS)
    product_id = foreign_id('products.id')
    user_id = foreign_id('users.id')
    rating = db.Column(db.SmallInteger, nullable=False)
    body = db.Column(db.String(2000), nullable=False)
    status = db.Column(db.String(20), nullable=False, default='pending', server_default='pending', index=True)
    moderated_by = foreign_id('users.id', nullable=True)
    moderated_at = db.Column(db.DateTime)
    moderation_reason = db.Column(db.String(500))
    user = db.relationship('User', foreign_keys=[user_id])
    product = db.relationship('Product')
