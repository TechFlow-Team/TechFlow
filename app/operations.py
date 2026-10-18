import csv
from io import StringIO

from flask import Blueprint, Response, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy import select

from app.auth.permissions import admin_required, business_required
from app.extensions import db
from app.models import AuditLog, Product
from app.services.report_service import report_data

blueprint = Blueprint('operations', __name__)


@blueprint.get('/business/low-stock')
@business_required
def low_stock():
    q = request.args.get('q', '').strip()
    if len(q) > 120 or request.args.get('state', '') not in {'', 'active', 'inactive'}:
        abort(400)
    query = select(Product).where(Product.stock_quantity <= Product.reorder_level)
    if q:
        query = query.where(Product.name.contains(q, autoescape=True) | Product.sku.contains(q, autoescape=True))
    if request.args.get('state'):
        query = query.where(Product.is_active.is_(request.args['state'] == 'active'))
    results = db.paginate(query.order_by(Product.stock_quantity, Product.id), per_page=20, max_per_page=20, error_out=False)
    return render_template('features/low_stock.html', results=results, active_page='low_stock')


@blueprint.post('/business/low-stock/<int:product_id>')
@admin_required
def threshold(product_id):
    raw = request.form.get('threshold', '')
    if not raw.isascii() or not raw.isdigit() or len(raw) > 10 or int(raw) > 4294967295:
        abort(422)
    product = db.get_or_404(Product, product_id)
    product.reorder_level = int(raw)
    db.session.add(AuditLog(user_id=current_user.id, action='stock_threshold', entity_type='products', entity_id=product.id))
    db.session.commit()
    flash('Đã lưu ngưỡng cảnh báo.', 'success')
    return redirect(url_for('operations.low_stock'), code=303)


def csv_cell(value):
    value = str(value)
    return "'" + value if value.lstrip().startswith(('=', '+', '-', '@')) else value


@blueprint.get('/business/reports')
@business_required
def reports():
    if request.args.get('format', '') not in {'', 'csv'}:
        abort(400)
    try:
        data = report_data(request.args)
    except (ValueError, OverflowError):
        abort(400, description='Khoảng ngày không hợp lệ; tối đa 367 ngày.')
    if request.args.get('format') == 'csv':
        stream = StringIO(newline='')
        writer = csv.writer(stream)
        def row(*values):
            writer.writerow([csv_cell(value) for value in values])
        row('Từ ngày', data['start'], 'Đến ngày', data['end'], 'Nhóm', data['group'])
        row('Doanh thu theo ngày hoàn tất (giờ Việt Nam)', 'Số đơn', 'Doanh thu VND')
        for entry in data['revenue']:
            row(*entry)
        row('Tổng doanh thu', '', data['total'])
        row('Đơn hủy theo ngày đặt', data['cancelled'][0], data['cancelled'][1])
        row('Top 50 sản phẩm', 'Tên', 'Số lượng', 'Doanh thu VND')
        for entry in data['best']:
            row(*entry)
        row('Tồn kho hiện tại', 'Tên', 'Số lượng', 'Ngưỡng', 'Hoạt động')
        for product in data['stock']:
            row(product.sku, product.name, product.stock_quantity, product.reorder_level, product.is_active)
        return Response('\ufeff' + stream.getvalue(), mimetype='text/csv',
                        headers={'Content-Disposition': 'attachment; filename=techflow-report.csv'})
    return render_template('features/reports.html', **data, active_page='reports')
