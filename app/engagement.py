import re

from flask import Blueprint, abort, redirect, render_template, request, session, url_for
from flask_login import current_user
from sqlalchemy import select

from app.auth.permissions import client_required
from app.extensions import db
from app.models import Favorite, Product, SalesOrder, SalesOrderItem, User, WarrantyCoverage, WarrantyDevice, WarrantyEvent, WarrantyTicket
from app.services.warranty_service import coverage_state, STATES

blueprint = Blueprint('engagement', __name__)


def compare_ids():
    raw = session.get('compare', [])
    if not isinstance(raw, list) or len(raw) > 4:
        return []
    return list(dict.fromkeys(value for value in raw if type(value) is int and 0 < value <= 18446744073709551615))


@blueprint.post('/compare/<int:product_id>')
def compare_toggle(product_id):
    product = db.get_or_404(Product, product_id)
    ids = compare_ids()
    if product.id in ids:
        ids.remove(product.id)
    elif len(ids) < 4:
        ids.append(product.id)
    else:
        abort(422, description='So sánh tối đa 4 sản phẩm; bỏ một sản phẩm trước khi thêm.')
    session['compare'] = ids
    return redirect(url_for('engagement.compare'), code=303)


@blueprint.get('/compare')
def compare():
    products = db.session.scalars(select(Product).where(Product.id.in_(compare_ids())).order_by(Product.id)).all()
    return render_template('features/compare.html', products=products)


@blueprint.get('/account/favorites')
@client_required
def favorites():
    results = db.paginate(select(Favorite).where(Favorite.user_id == current_user.id).order_by(Favorite.id.desc()),
                          per_page=20, max_per_page=20, error_out=False)
    return render_template('features/favorites.html', results=results)


@blueprint.post('/account/favorites/<int:product_id>')
@client_required
def favorite_toggle(product_id):
    db.session.scalar(select(User).where(User.id == current_user.id).with_for_update())
    product = db.get_or_404(Product, product_id)
    entry = db.session.scalar(select(Favorite).where(Favorite.user_id == current_user.id, Favorite.product_id == product.id))
    if entry:
        db.session.delete(entry)
    else:
        db.session.add(Favorite(user_id=current_user.id, product_id=product.id))
    db.session.commit()
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
