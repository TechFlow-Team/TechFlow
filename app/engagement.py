import re

from flask import Blueprint, abort, jsonify, redirect, render_template, request, session, url_for
from flask_login import current_user
from sqlalchemy import func, select

from app.auth.permissions import client_required
from app.extensions import db
from app.models import Favorite, Product, ProductReview, SalesOrder, SalesOrderItem, User, WarrantyCoverage, WarrantyDevice, WarrantyEvent, WarrantyTicket
from app.services.image_storage import product_image_src
from app.services.warranty_service import coverage_state, STATES

blueprint = Blueprint('engagement', __name__)


MAX_COMPARE = 4


def compare_ids():
    raw = session.get('compare', [])
    if not isinstance(raw, list) or len(raw) > MAX_COMPARE:
        return []
    return list(dict.fromkeys(value for value in raw if type(value) is int and 0 < value <= 18446744073709551615))


def compare_products():
    ids = compare_ids()
    if not ids:
        return []
    products = db.session.scalars(select(Product).where(Product.id.in_(ids))).all()
    return sorted(products, key=lambda item: ids.index(item.id))


def compare_state():
    products = compare_products()
    return {'count': len(products), 'max': MAX_COMPARE, 'ids': [p.id for p in products],
            'items': [{'id': p.id, 'name': p.name, 'image': product_image_src(p), 'category_id': p.category_id,
                       'url': url_for('shop.product_detail', product_id=p.id)} for p in products]}


@blueprint.get('/compare/state')
def compare_state_view():
    return jsonify(compare_state())


@blueprint.post('/compare/<int:product_id>')
def compare_toggle(product_id):
    product = db.get_or_404(Product, product_id)
    ids = compare_ids()
    if product.id in ids:
        ids.remove(product.id)
    elif len(ids) < MAX_COMPARE:
        ids.append(product.id)
    else:
        abort(422, description='So sánh tối đa 4 sản phẩm; bỏ một sản phẩm trước khi thêm.')
    session['compare'] = ids
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.args.get('format') == 'json':
        return jsonify(compare_state())
    return redirect(url_for('engagement.compare'), code=303)


@blueprint.post('/compare/<int:product_id>/add')
def compare_add(product_id):
    product = db.get_or_404(Product, product_id)
    ids = compare_ids()
    if product.id in ids:
        return jsonify(compare_state())
    if len(ids) >= MAX_COMPARE:
        return jsonify(dict(compare_state(), error='Chỉ so sánh tối đa 4 sản phẩm. Hãy bỏ bớt trước khi thêm.')), 422
    others = compare_products()
    if others and others[0].category_id != product.category_id:
        return jsonify(dict(compare_state(), error='Chỉ so sánh các sản phẩm cùng danh mục.')), 422
    ids.append(product.id)
    session['compare'] = ids
    return jsonify(compare_state())


@blueprint.post('/compare/<int:product_id>/remove')
def compare_remove(product_id):
    session['compare'] = [value for value in compare_ids() if value != product_id]
    return jsonify(compare_state())


@blueprint.post('/compare/clear')
def compare_clear():
    session['compare'] = []
    return jsonify(compare_state())


@blueprint.get('/compare')
def compare():
    products = compare_products()
    ratings = {}
    if products:
        for pid, avg, cnt in db.session.execute(
                select(ProductReview.product_id, func.avg(ProductReview.rating), func.count())
                .where(ProductReview.product_id.in_([p.id for p in products]), ProductReview.status == 'visible')
                .group_by(ProductReview.product_id)):
            ratings[pid] = {'avg': round(float(avg), 1) if avg else 0, 'count': cnt}
    return render_template('features/compare.html', products=products, ratings=ratings, compare_max=MAX_COMPARE)


@blueprint.get('/account/favorites')
@client_required
def favorites():
    results = db.paginate(select(Favorite).where(Favorite.user_id == current_user.id).order_by(Favorite.id.desc()),
                          per_page=20, max_per_page=20, error_out=False)
    return render_template('features/favorites.html', results=results)


@blueprint.get('/account/favorites/state')
@client_required
def favorites_state():
    ids = db.session.scalars(select(Favorite.product_id).where(Favorite.user_id == current_user.id)).all()
    return jsonify({'ids': list(ids), 'count': len(ids)})


@blueprint.post('/account/favorites/<int:product_id>')
@client_required
def favorite_toggle(product_id):
    db.session.scalar(select(User).where(User.id == current_user.id).with_for_update())
    product = db.get_or_404(Product, product_id)
    entry = db.session.scalar(select(Favorite).where(Favorite.user_id == current_user.id, Favorite.product_id == product.id))
    if entry:
        db.session.delete(entry)
        favorited = False
    else:
        db.session.add(Favorite(user_id=current_user.id, product_id=product.id))
        favorited = True
    db.session.commit()
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.args.get('format') == 'json':
        count = db.session.scalar(select(func.count()).select_from(Favorite).where(Favorite.user_id == current_user.id)) or 0
        return jsonify({'favorited': favorited, 'count': count, 'product_id': product.id})
    return redirect(url_for('engagement.favorites'), code=303)


@blueprint.get('/account/warranties')
@client_required
def warranties():
    owned = (SalesOrder.created_by == current_user.id) | SalesOrder.customer.has(user_id=current_user.id)
    query = select(SalesOrderItem).join(SalesOrder).where(owned, SalesOrder.status == 'completed').order_by(SalesOrderItem.id.desc())
    results = db.paginate(query, per_page=20, max_per_page=20, error_out=False)
    ids = [item.id for item in results.items]
    coverages = {c.sale_item_id: c for c in db.session.scalars(select(WarrantyCoverage).where(WarrantyCoverage.sale_item_id.in_(ids)))}
    tickets = db.session.scalars(select(WarrantyTicket).join(WarrantyDevice).join(WarrantyCoverage)
        .where(WarrantyCoverage.sale_item_id.in_(ids)).order_by(WarrantyTicket.id.desc())).all()
    events = {}
    if tickets:
        for event in db.session.scalars(select(WarrantyEvent).where(WarrantyEvent.ticket_id.in_([ticket.id for ticket in tickets])).order_by(WarrantyEvent.id)):
            events.setdefault(event.ticket_id, []).append(event)
    return render_template('features/client_warranties.html', results=results, coverages=coverages,
                           tickets=tickets, events=events, coverage_state=coverage_state, warranty_labels=STATES)
