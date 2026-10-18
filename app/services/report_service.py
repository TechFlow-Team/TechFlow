"""Read-only reports; completed revenue uses completion time in Vietnam."""
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from app.extensions import db
from app.models import Product, SalesOrder, SalesOrderItem


def report_data(args):
    today = datetime.now(ZoneInfo('Asia/Ho_Chi_Minh')).date()
    start = date.fromisoformat(args.get('from', today.replace(day=1).isoformat()))
    end = date.fromisoformat(args.get('to', today.isoformat()))
    group = args.get('group', 'day')
    if start > end or (end - start).days > 366 or group not in {'day', 'month'}:
        raise ValueError('Chọn khoảng tối đa 367 ngày và nhóm ngày/tháng hợp lệ.')
    def boundary(day):
        return datetime.combine(day, time.min, ZoneInfo('Asia/Ho_Chi_Minh')).astimezone(timezone.utc).replace(tzinfo=None)
    lower, upper = boundary(start), boundary(end + timedelta(days=1))
    completed = (SalesOrder.status == 'completed', SalesOrder.completed_at >= lower, SalesOrder.completed_at < upper)
    local_time = func.date_add(SalesOrder.completed_at, db.text('INTERVAL 7 HOUR'))
    bucket = func.date_format(local_time, '%Y-%m' if group == 'month' else '%Y-%m-%d')
    revenue = db.session.execute(select(bucket, func.count(), func.sum(SalesOrder.total_amount))
        .where(*completed).group_by(bucket).order_by(bucket)).all()
    best = db.session.execute(select(Product.sku, Product.name, func.sum(SalesOrderItem.quantity), func.sum(SalesOrderItem.line_total))
        .join(SalesOrderItem, Product.id == SalesOrderItem.product_id).join(SalesOrder)
        .where(*completed).group_by(Product.id, Product.sku, Product.name)
        .order_by(func.sum(SalesOrderItem.quantity).desc(), Product.id).limit(50)).all()
    cancelled = db.session.execute(select(func.count(), func.coalesce(func.sum(SalesOrder.total_amount), 0))
        .where(SalesOrder.status == 'cancelled', SalesOrder.order_date >= lower, SalesOrder.order_date < upper)).one()
    stock = db.session.scalars(select(Product).order_by(Product.sku).limit(5001)).all()
    if len(stock) > 5000:
        raise ValueError('Báo cáo hỗ trợ tối đa 5000 sản phẩm. Thu hẹp catalog trước khi xuất.')
    return dict(start=start, end=end, group=group, revenue=revenue, best=best, cancelled=cancelled, stock=stock,
                total=sum((row[2] for row in revenue), Decimal('0')))
