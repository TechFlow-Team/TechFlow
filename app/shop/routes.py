import re

from flask import Blueprint, abort, current_app, flash, jsonify, redirect, render_template, request, session, url_for
from flask_login import current_user, login_user
from sqlalchemy import or_, select, func
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import selectinload

from app.auth.permissions import client_required
from app.extensions import db
from app.models import Category, Customer, Favorite, Product, SalesOrder, SalesOrderItem, SupportConversation, User, ProductReview
from app.services.client_order_service import cancel_client_order, place_client_order
from app.services.customer_service import normalize_registered_profile
from app.services.inventory_service import InventoryError
from app.shop.forms import CheckoutForm, ProfileForm, RegisterForm

blueprint = Blueprint("shop", __name__)
MAX_PRODUCT_ID = 18446744073709551615


def _cart():
    raw = session.get("cart", {})
    if not isinstance(raw, dict) or len(raw) > 20:
        return {}
    cart = {}
    for key, value in raw.items():
        if str(key).isascii() and str(key).isdigit() and len(str(key)) <= 20 and str(value).isascii() and str(value).isdigit():
            if 1 <= int(key) <= MAX_PRODUCT_ID and 1 <= int(value) <= 20:
                cart[str(int(key))] = int(value)
    return cart


def _cart_rows(cart):
    if not cart:
        return [], 0
    products = db.session.scalars(select(Product).where(Product.id.in_([int(key) for key in cart]), Product.is_active.is_(True))).all()
    rows = [(product, cart[str(product.id)], product.selling_price * cart[str(product.id)]) for product in products]
    return rows, sum((row[2] for row in rows), start=0)


# Mã giảm giá demo (giảm theo %). Chỉ áp dụng hiển thị ở giỏ; đơn hàng do backend tính lại.
DISCOUNTS = {"TECHFLOW10": 10, "SINHVIEN5": 5}


def _vnd(value):
    try:
        amount = int(round(float(value)))
    except (TypeError, ValueError):
        return "0 ₫"
    return f"{amount:,}".replace(",", ".") + " ₫"


def _cart_summary(cart):
    _rows, subtotal = _cart_rows(cart)
    code = session.get("discount") if session.get("discount") in DISCOUNTS else None
    percent = DISCOUNTS.get(code, 0)
    discount = (subtotal * percent) / 100
    total = subtotal - discount
    return {"count": sum(cart.values()), "items": len(cart),
            "subtotal_display": _vnd(subtotal), "discount_percent": percent,
            "discount_display": _vnd(discount), "shipping_display": "Miễn phí",
            "total_display": _vnd(total), "discount_code": code}


@blueprint.app_context_processor
def storefront_context():
    compare_raw = session.get("compare", [])
    compare_count = len(compare_raw) if isinstance(compare_raw, list) else 0
    favorite_count = 0
    support_unread = 0
    if current_user.is_authenticated and getattr(current_user, "role", None) == "client":
        favorite_count = db.session.scalar(select(func.count()).select_from(Favorite).where(Favorite.user_id == current_user.id)) or 0
        # Chưa đọc = ticket chưa từng mở, hoặc có cập nhật mới hơn mốc "đã xem" lưu trong session.
        seen = session.get("support_seen", {})
        if not isinstance(seen, dict):
            seen = {}
        rows = db.session.execute(select(SupportConversation.id, SupportConversation.updated_at)
                                  .where(SupportConversation.user_id == current_user.id)).all()
        support_unread = sum(1 for cid, updated_at in rows
                             if str(cid) not in seen or (updated_at and updated_at.isoformat() > seen[str(cid)]))
    return {"cart_count": sum(_cart().values()), "compare_count": compare_count,
            "favorite_count": favorite_count, "support_unread": support_unread}


@blueprint.get("/shop")
def index():
    q = request.args.get("q", "").strip()
    category = request.args.get("category", "")
    sort = request.args.get("sort", "name")
    brand = request.args.get("brand", "").strip()
    price_min = request.args.get("price_min", "").strip()
    price_max = request.args.get("price_max", "").strip()
    if len(q) > 120 or sort not in {"name", "price_asc", "price_desc", "newest"}:
        abort(400)
    if len(brand) > 100:
        abort(400)
    if price_min and not re.fullmatch(r"[0-9]{1,12}", price_min):
        abort(400)
    if price_max and not re.fullmatch(r"[0-9]{1,12}", price_max):
        abort(400)
    if price_min and price_max and int(price_min) > int(price_max):
        abort(400)
    query = select(Product).where(Product.is_active.is_(True))
    if q:
        query = query.where(or_(Product.name.contains(q, autoescape=True), Product.sku.contains(q, autoescape=True),
                                Product.brand.contains(q, autoescape=True), Product.model.contains(q, autoescape=True)))
    if category:
        if not category.isascii() or not category.isdigit() or len(category) > 19 or int(category) < 1:
            abort(400)
        query = query.where(Product.category_id == int(category))
    if brand:
        query = query.where(Product.brand == brand)
    if price_min:
        query = query.where(Product.selling_price >= int(price_min))
    if price_max:
        query = query.where(Product.selling_price <= int(price_max))
    order_by = {"name": Product.name.asc(), "price_asc": Product.selling_price.asc(),
                "price_desc": Product.selling_price.desc(), "newest": Product.id.desc()}[sort]
    page = request.args.get("page", "1")
    if not page.isascii() or not page.isdigit() or len(page) > 9 or int(page) < 1:
        abort(400)
    results = db.paginate(query.order_by(order_by, Product.id), page=int(page), per_page=12, error_out=False)
    categories = db.session.scalars(select(Category).where(Category.is_active.is_(True),
        Category.products.any(Product.is_active.is_(True))).order_by(Category.name)).all()
    brands = db.session.scalars(select(Product.brand).where(Product.is_active.is_(True),
        Product.brand.is_not(None), Product.brand != "").distinct().order_by(Product.brand)).all()
    return render_template("shop/index.html", results=results, categories=categories, brands=brands,
                           cart_count=sum(_cart().values()), page_url=lambda n: url_for("shop.index", **{**request.args.to_dict(), "page": n}))


@blueprint.get("/shop/product/<int:product_id>")
def product_detail(product_id):
    if product_id > MAX_PRODUCT_ID:
        abort(404)
    product = db.session.scalar(select(Product).where(Product.id == product_id, Product.is_active.is_(True)))
    if not product:
        abort(404)
    visible = (ProductReview.product_id == product_id, ProductReview.status == 'visible')
    reviews = db.session.scalars(select(ProductReview).where(*visible).order_by(ProductReview.id.desc()).limit(50)).all()
    summary = db.session.execute(select(func.count(), func.avg(ProductReview.rating)).where(*visible)).one()
    distribution = {star: 0 for star in range(1, 6)}
    for star, total in db.session.execute(select(ProductReview.rating, func.count()).where(*visible).group_by(ProductReview.rating)):
        distribution[int(star)] = total
    can_review = False
    my_review = None
    if current_user.is_authenticated and getattr(current_user, "role", None) == "client":
        my_review = db.session.scalar(select(ProductReview).where(
            ProductReview.user_id == current_user.id, ProductReview.product_id == product_id))
        can_review = db.session.scalar(select(SalesOrderItem.id).join(SalesOrder).where(
            SalesOrderItem.product_id == product_id, SalesOrder.status == "completed",
            (SalesOrder.created_by == current_user.id) | SalesOrder.customer.has(user_id=current_user.id)).limit(1)) is not None
    related = db.session.scalars(select(Product).where(
        Product.category_id == product.category_id, Product.id != product.id,
        Product.is_active.is_(True)).order_by(Product.id.desc()).limit(4)).all()
    return render_template("shop/product.html", product=product, reviews=reviews, review_summary=summary,
                           review_distribution=distribution, can_review=can_review, my_review=my_review, related=related)


@blueprint.post("/shop/cart/<int:product_id>")
def add_to_cart(product_id):
    if product_id > MAX_PRODUCT_ID:
        abort(404)
    product = db.session.scalar(select(Product).where(Product.id == product_id, Product.is_active.is_(True)))
    if not product:
        abort(404)
    try:
        quantity = int(request.form.get("quantity", "1"))
        if str(quantity) != request.form.get("quantity", "1") or not 1 <= quantity <= 20:
            raise ValueError
    except ValueError:
        abort(400)
    cart = _cart()
    new_quantity = cart.get(str(product_id), 0) + quantity
    if new_quantity > 20 or len(cart) >= 20 and str(product_id) not in cart:
        flash("Giỏ hàng tối đa 20 sản phẩm cho mỗi mã và 20 mã hàng.", "warning")
    elif new_quantity > product.stock_quantity:
        flash("Số lượng vượt tồn kho hiện tại.", "warning")
    else:
        cart[str(product_id)] = new_quantity
        session["cart"] = cart
        flash("Đã thêm sản phẩm vào giỏ.", "success")
    return redirect(url_for("shop.index"), code=303)


@blueprint.get("/cart")
def cart():
    cart_items = _cart()
    rows, total = _cart_rows(cart_items)
    if len(rows) != len(cart_items):
        available = {str(product.id) for product, _, _ in rows}
        cart_items = {key: qty for key, qty in cart_items.items() if key in available}
        session["cart"] = cart_items
        flash("Giỏ hàng đã được làm mới vì một số sản phẩm không còn được bán.", "info")
    return render_template("shop/cart.html", rows=rows, total=total, summary=_cart_summary(cart_items))


@blueprint.post("/cart/update")
def update_cart():
    cart = _cart()
    if not cart:
        return redirect(url_for("shop.cart"), code=303)
    products = {str(p.id): p for p in db.session.scalars(select(Product).where(
        Product.id.in_([int(key) for key in cart]), Product.is_active.is_(True))).all()}
    updated = {}
    for product_id in cart:
        raw = request.form.get(f"quantity_{product_id}", "")
        if not raw.isascii() or not raw.isdigit() or len(raw) > 2 or not 0 <= int(raw) <= 20:
            flash("Số lượng phải từ 1 đến 20; nhập 0 để bỏ sản phẩm.", "warning")
            return redirect(url_for("shop.cart"))
        quantity = int(raw)
        if quantity == 0:
            continue
        product = products.get(product_id)
        if not product:
            flash("Một sản phẩm trong giỏ đã ngừng bán. Vui lòng bỏ khỏi giỏ.", "warning")
            return redirect(url_for("shop.cart"))
        if quantity > product.stock_quantity:
            flash(f"Số lượng {product.name} vượt tồn kho hiện tại.", "warning")
            return redirect(url_for("shop.cart"))
        updated[product_id] = quantity
    session["cart"] = updated
    flash("Đã cập nhật giỏ hàng.", "success")
    return redirect(url_for("shop.cart"), code=303)


@blueprint.post("/cart/remove/<int:product_id>")
def remove_from_cart(product_id):
    cart = _cart()
    cart.pop(str(product_id), None)
    session["cart"] = cart
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify(_cart_summary(cart))
    return redirect(url_for("shop.cart"), code=303)


@blueprint.get("/cart/count")
def cart_count():
    return jsonify({"count": sum(_cart().values())})


@blueprint.post("/cart/item/<int:product_id>")
def set_cart_item(product_id):
    cart = _cart()
    raw = request.form.get("quantity", "")
    if not raw.isascii() or not raw.isdigit() or len(raw) > 2:
        return jsonify({"error": "Số lượng không hợp lệ."}), 400
    quantity = int(raw)
    product = db.session.scalar(select(Product).where(Product.id == product_id, Product.is_active.is_(True)))
    warning = None
    removed = False
    if not product:
        cart.pop(str(product_id), None)
        removed = True
        warning = "Sản phẩm đã ngừng bán và được bỏ khỏi giỏ."
    elif quantity <= 0:
        cart.pop(str(product_id), None)
        removed = True
    else:
        if quantity > 20:
            quantity = 20
            warning = "Mỗi mã hàng tối đa 20 sản phẩm."
        if quantity > product.stock_quantity:
            quantity = product.stock_quantity
            warning = "Số lượng vượt tồn kho, đã điều chỉnh về mức còn lại." if quantity > 0 else "Sản phẩm đã hết hàng."
        if quantity <= 0:
            cart.pop(str(product_id), None)
            removed = True
        else:
            cart[str(product_id)] = quantity
    session["cart"] = cart
    line_total = (product.selling_price * cart[str(product_id)]) if product and str(product_id) in cart else 0
    return jsonify(dict(_cart_summary(cart), quantity=cart.get(str(product_id), 0), removed=removed,
                        line_total_display=_vnd(line_total), warning=warning))


@blueprint.post("/cart/discount")
def cart_discount():
    code = (request.form.get("code") or "").strip().upper()
    if code and code not in DISCOUNTS:
        return jsonify(dict(_cart_summary(_cart()), error="Mã giảm giá không hợp lệ.")), 422
    if code:
        session["discount"] = code
    else:
        session.pop("discount", None)
    return jsonify(dict(_cart_summary(_cart()), applied=bool(code)))


@blueprint.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.index"))
    form = RegisterForm()
    message = None
    if form.validate_on_submit():
        username = form.username.data.strip().lower()
        email = form.email.data.strip().lower()
        try:
            profile = normalize_registered_profile(dict(name=form.full_name.data, phone=form.phone.data,
                                             email=email, address=form.address.data))
            if db.session.scalar(select(User.id).where((User.username == username) | (User.email == email))):
                raise ValueError("Tên đăng nhập hoặc email đã được sử dụng.")
            user = User(username=username, email=email, full_name=form.full_name.data.strip(), role="client", is_active=True)
            user.set_password(form.password.data)
            db.session.add(user)
            db.session.flush()
            db.session.add(Customer(**profile, user_id=user.id, created_by=user.id, is_active=True))
            db.session.commit()
            cart = _cart()
            session.clear()
            if cart:
                session["cart"] = cart
            login_user(user, remember=False, fresh=True)
            session.permanent = True
            flash("Tạo tài khoản thành công. Bạn có thể đặt hàng ngay.", "success")
            return redirect(url_for("shop.cart" if cart else "shop.index"), code=303)
        except ValueError as error:
            db.session.rollback()
            message = str(error)
        except IntegrityError:
            db.session.rollback()
            message = "Tên đăng nhập, email hoặc số điện thoại đã được đăng ký."
        except SQLAlchemyError:
            db.session.rollback()
            current_app.logger.error("Client registration failed")
            message = "Chưa thể tạo tài khoản. Vui lòng thử lại sau."
    return render_template("shop/register.html", form=form, message=message), 422 if request.method == "POST" else 200


@blueprint.get("/account/orders")
@client_required
def orders():
    results = db.session.scalars(select(SalesOrder).where(SalesOrder.created_by == current_user.id)
                                 .order_by(SalesOrder.order_date.desc(), SalesOrder.id.desc())).all()
    return render_template("shop/orders.html", orders=results)


@blueprint.get("/account/orders/<int:order_id>")
@client_required
def order_detail(order_id):
    order = db.session.scalar(select(SalesOrder).where(SalesOrder.id == order_id,
        SalesOrder.created_by == current_user.id).options(selectinload(SalesOrder.items).selectinload(SalesOrderItem.product)))
    if not order:
        abort(404)
    return render_template("shop/order_detail.html", order=order, form=CheckoutForm())


@blueprint.post("/account/orders/<int:order_id>/cancel")
@client_required
def cancel_order(order_id):
    form = CheckoutForm()
    if not form.validate_on_submit():
        abort(400)
    try:
        cancel_client_order(current_user.id, order_id)
        flash("Đã hủy đơn đang chờ xử lý.", "success")
    except InventoryError as error:
        if error.status == 404:
            abort(404)
        if error.status == 403:
            abort(403)
        flash(error.message, "warning")
    return redirect(url_for("shop.order_detail", order_id=order_id), code=303)


@blueprint.route("/account/profile", methods=["GET", "POST"])
@client_required
def profile():
    customer = current_user.customer_profile
    if not customer or not customer.is_active:
        abort(403)
    form = ProfileForm(obj=current_user)
    if request.method == "GET":
        form.phone.data = customer.phone
        form.address.data = customer.address
    message = None
    if form.validate_on_submit():
        try:
            values = normalize_registered_profile(dict(name=form.full_name.data, email=form.email.data.strip().lower(),
                phone=form.phone.data, address=form.address.data))
            duplicate_email = db.session.scalar(select(User.id).where(User.email == values["email"], User.id != current_user.id))
            duplicate_phone = db.session.scalar(select(Customer.id).where(Customer.phone == values["phone"], Customer.id != customer.id))
            if duplicate_email or duplicate_phone:
                raise ValueError("Email hoặc số điện thoại đã được sử dụng.")
            current_user.full_name = values["name"]
            current_user.email = values["email"]
            customer.name, customer.email = values["name"], values["email"]
            customer.phone, customer.address = values["phone"], values["address"]
            db.session.commit()
            flash("Đã cập nhật hồ sơ và địa chỉ giao hàng.", "success")
            return redirect(url_for("shop.profile"), code=303)
        except ValueError as error:
            db.session.rollback()
            message = str(error)
        except IntegrityError:
            db.session.rollback()
            message = "Email hoặc số điện thoại đã được sử dụng."
        except SQLAlchemyError:
            db.session.rollback()
            current_app.logger.error("Client profile update failed")
            message = "Chưa thể lưu hồ sơ. Vui lòng thử lại sau."
    return render_template("shop/profile.html", form=form, message=message)


@blueprint.route("/checkout", methods=["GET", "POST"])
@client_required
def checkout():
    cart = _cart()
    rows, total = _cart_rows(cart)
    if not rows or len(rows) != len(cart):
        flash("Giỏ hàng trống hoặc có sản phẩm đã ngừng bán. Vui lòng kiểm tra lại.", "warning")
        return redirect(url_for("shop.cart"))
    form = CheckoutForm()
    message = None
    if form.validate_on_submit():
        try:
            identifier = place_client_order(current_user.id, cart)
            session.pop("cart", None)
            flash("Đã nhận đơn. Nhân viên sẽ xác nhận và xử lý đơn hàng.", "success")
            return redirect(url_for("shop.orders"), code=303)
        except InventoryError as error:
            message = error.message
            if error.status == 403:
                abort(403)
    return render_template("shop/checkout.html", rows=rows, total=total, form=form, message=message), 422 if request.method == "POST" and message else 200
