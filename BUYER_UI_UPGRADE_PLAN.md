# TechFlow — Kế hoạch nâng cấp giao diện bên mua hàng (buyer UI)

> **Tài liệu sống (living doc).** AI/dev tiếp theo hãy đọc file này ĐẦU TIÊN để nắm bối cảnh,
> ràng buộc, việc đã làm và việc cần làm tiếp. Cập nhật mục **§9 Nhật ký tiến độ** sau mỗi thay đổi.

## 0. Thông tin nhanh
- **Nhánh:** `feature/buyer-ui` (tách từ `main`, đã pull mới nhất).
- **Phạm vi:** nâng cấp trải nghiệm phía mua hàng (storefront `shop`, `engagement`, `content`, `support`).
- **Nguồn yêu cầu gốc:** prompt người dùng (8 mục + tiêu chí nghiệm thu). Tóm tắt ở §5.

## 1. RÀNG BUỘC CỨNG (bắt buộc tuân thủ)
1. **KHÔNG thay đổi schema DB**: không tạo bảng/cột mới, **không viết migration**. Chỉ dùng schema hiện có + code (route/service/template/JS/CSS).
2. **KHÔNG phá vỡ** luồng đang chạy: đăng nhập, đặt hàng, đơn hàng, kiểm duyệt nội dung.
3. **Chữ hiển thị: tiếng Việt CÓ DẤU, đúng chính tả.**
4. **Không cần dựng lại** (không rebuild/docker/seed lại DB) — chỉnh sửa code trực tiếp. Chỉ byte-compile/kiểm tra cú pháp khi cần.
5. Giữ tông **xanh dương**; dùng Bootstrap 5 + bootstrap-icons sẵn có; không thêm framework JS nặng. Dùng `fetch` thuần cho AJAX.

## 2. Stack & cấu trúc
- **Flask 3.1** (app factory, blueprints) · **Flask-SQLAlchemy 2.0** · **Flask-Migrate/Alembic** (MySQL/PyMySQL) · **Flask-Login** · **Flask-WTF (CSRF — mọi POST cần `csrf_token`)** · **boto3 + Pillow** (ảnh S3, fallback local) · Jinja2 · Bootstrap 5.
- Blueprint chính của buyer UI:
  - `app/shop/routes.py` — storefront: `/shop`, `/shop/product/<id>`, giỏ hàng `/cart` (+ `/cart/update`, `/cart/remove`, `/shop/cart/<id>`), `/checkout`, `/account/...` (orders, profile).
  - `app/engagement.py` — So sánh (`/compare`, session, tối đa 4), Yêu thích (`/account/favorites`, bảng `favorites`), Bảo hành của tôi.
  - `app/content.py` — Blog, **Đánh giá** (`POST /shop/product/<id>/review` — đã chặn 403), bình luận, "Đánh giá của tôi" (`/account/contributions`), kiểm duyệt.
  - `app/support.py` — Hộp thư hỗ trợ (`/support`, hiện "reload-based").

## 3. Hạ tầng ĐÃ CÓ (đừng điều tra lại)
- `Product.image_url` (`String(500)`) **đã tồn tại**. `app/services/image_storage.py` có `save_product_image`, `display_product_image` (ký URL S3), `delete_product_image`.
- **BE đánh giá ĐÃ kiểm tra quyền + trả 403** khi chưa có đơn `completed` chứa sản phẩm — xem `app/content.py → review()`. ⇒ Mục 1 chủ yếu là FE.
- Models liên quan: `ProductReview` (unique user+product, rating 1–5, status pending→visible, kiểm duyệt), `Favorite` (unique user+product), `SupportConversation` (status `new|processing|closed`) + `SupportMessage` (body, chưa có đính kèm).
- Giỏ hàng: **session-based** (`_cart`, `_cart_rows` trong `shop/routes.py`); badge qua context processor `cart_count`.
- So sánh: **session-based** (`compare_ids()` trong `engagement.py`), giới hạn 4 (abort 422).
- Filter giá `vnd` ở `app/__init__.py` dùng `,.2f` → **đang in ra `,00`** (cần sửa).
- Danh mục seed (`app/services/seed_service.py`): Laptop, Linh kiện máy tính, Màn hình, Thiết bị ngoại vi, Thiết bị mạng, Phụ kiện.

## 4. Bản đồ file quan trọng
| Khu vực | File |
|---|---|
| App factory, filter `vnd`, template globals | `app/__init__.py` |
| Storefront routes + giỏ hàng | `app/shop/routes.py` |
| So sánh / Yêu thích | `app/engagement.py` |
| Đánh giá / Blog / "Đánh giá của tôi" | `app/content.py` |
| Hỗ trợ | `app/support.py` |
| Ảnh | `app/services/image_storage.py`, `app/static/images/` |
| Layout cửa hàng (header + cụm 6 nút) | `app/templates/shop/base.html` |
| Trang chi tiết / giỏ / danh sách | `app/templates/shop/product.html`, `cart.html`, `index.html` |
| So sánh / Yêu thích / Hỗ trợ (view) | `app/templates/features/compare.html`, `favorites.html`, `support_inbox.html`, `support_detail.html`, `support_new.html` |
| CSS | `app/static/css/storefront.css`, `features.css`, `detail-polish.css`, `foundation.css` |
| JS | `app/static/js/app.js` |
| Test | `tests/` (pytest, chạy `pytest -q`) |

## 5. Kế hoạch theo từng mục (đã điều chỉnh cho ràng buộc KHÔNG đổi DB)

### Mục 5 — Ảnh sản phẩm  *(nền tảng, làm trước)*
- **FE/BE:** thêm helper Jinja `product_image_src(product)` → trả `image_url` (ký S3 nếu cần) hoặc **placeholder theo danh mục**. Tạo SVG placeholder cho từng nhóm: laptop / màn hình / linh kiện / ngoại vi / mạng / phụ kiện / mặc định (trong `app/static/images/placeholders/`). Dùng `loading="lazy"` cho mọi `<img>`.
- **Trang chi tiết:** ảnh lớn + dải thumbnail + **zoom khi hover** (CSS). *(Chỉ có 1 ảnh `image_url` + placeholder vì không có bảng gallery.)*
- **Không cần seed** `image_url`: thiếu ảnh sẽ tự fallback placeholder đúng danh mục.

### Mục 8 (phần giá) — Định dạng VND
- Sửa filter `vnd` trong `app/__init__.py`: bỏ `,00` → `"13.990.000 ₫"`.

### Mục 7 — Điều hướng (`shop/base.html`)
- Xoá cụm `.feature-links` (6 nút). Header: logo, ô tìm kiếm, **Sản phẩm**, **Blog**, icon **So sánh** (số), **Yêu thích** (số), **Giỏ hàng** (số), **menu tài khoản** (dropdown: Đơn hàng, Bảo hành của tôi, Đánh giá của tôi, Hộp thư hỗ trợ + số chưa đọc, Tài khoản, Đăng xuất). Sidebar dọc cho trang tài khoản. Mobile: hamburger/bottom-nav, không tràn ngang.

### Mục 1 — Đánh giá sau mua
- **BE 403 đã có.** `product_detail` truyền thêm: `can_review` (đã đăng nhập + có đơn completed + chưa/đã có review để sửa), review cũ của tôi, **phân bố sao 5→1**, cờ "đã mua" mỗi review.
- **FE `product.html`:** ẩn form nếu không đủ điều kiện (+ dòng "Chỉ khách đã mua sản phẩm mới có thể đánh giá"); **component 5 sao bấm/hover** thay dropdown; danh sách: điểm TB, số lượt, biểu đồ phân bố, huy hiệu "Đã mua hàng". Trang "Đánh giá của tôi" (đã có `contributions`) rà lại hiển thị sao + sửa/xóa.

### Mục 2 — So sánh *(session + localStorage, KHÔNG bảng mới)*
- API JSON `/compare/state` (lấy/thêm/bỏ/xóa hết) dùng session. Checkbox/nút "So sánh" trên mỗi thẻ; **thanh nổi sticky** (ảnh nhỏ, bỏ từng cái, "Xóa tất cả", "So sánh ngay" bật khi ≥2); chặn khác danh mục (cảnh báo); `/compare` bảng cạnh nhau + tô khác biệt + "Chỉ hiện khác nhau" + thêm giỏ/bỏ. localStorage mirror cho khách.

### Mục 3 — Yêu thích
- `favorite_toggle` trả **JSON** khi gọi AJAX (giữ redirect cho no-JS). Icon tim trên mỗi thẻ + chi tiết, toggle optimistic (không reload), tim đặc khi đã thích. `favorites.html`: lưới + thêm giỏ + bỏ thích + trạng thái trống có minh hoạ + "Khám phá sản phẩm". Chưa đăng nhập → chuyển login rồi quay lại (`?next=`).

### Mục 4 — Giỏ hàng
- API JSON cập nhật 1 dòng + `/cart/count`. `cart.html`: mỗi dòng có ảnh, tên-link, SKU, đơn giá, bộ chọn `[−] n [+]` **tự cập nhật** (bỏ nút "Cập nhật giỏ"; giới hạn tồn kho), thành tiền, nút xoá (icon + xác nhận). Khung **"Tóm tắt đơn hàng" sticky** (tạm tính, phí vận chuyển, ô mã giảm giá, tổng, "Tiến hành thanh toán", "← Tiếp tục mua sắm"). Giỏ trống có minh hoạ. Badge realtime mọi trang. Cảnh báo hết hàng/đổi giá.

### Mục 6 — Hộp thư hỗ trợ *(KHÔNG bảng/cột mới)*
- Bố cục **2 cột** helpdesk: trái danh sách (tiêu đề, trạng thái, phụ trách, thời gian, chấm "chưa đọc" suy từ **session** last-seen), phải khung **chat** (bong bóng khách/nhân viên, giờ gửi). Form tạo (chủ đề, danh mục, đơn liên quan, nội dung). **Polling 5s** qua JSON `/support/<id>/messages`, bỏ câu "Tải lại trang…". Lọc trạng thái (3 trạng thái hiện có) + tìm kiếm + phân trang; đóng/mở lại (closed ↔ new). Giữ cảnh báo bảo mật.
- ⚠️ **Đính kèm ảnh: TẠM BỎ** (cần cột/bảng lưu metadata → vi phạm "không đổi DB"). Ghi rõ là giới hạn.

### Mục 8 — Chất lượng chung
- Lọc danh mục/**khoảng giá**/**thương hiệu**/sắp xếp + phân trang/tải thêm + huy hiệu "Còn X / Hết hàng". Chi tiết: tab Mô tả/Thông số/Đánh giá + sản phẩm liên quan. Skeleton/empty/error. **Toast** khi thêm giỏ/yêu thích/so sánh. Responsive + focus state + `aria-label`. Design token (biến CSS, giữ tông xanh).

## 6. Giả định
- Realtime hỗ trợ = **polling 5s** (gunicorn đồng bộ, chưa có WebSocket) — đúng phương án dự phòng cho phép.
- Ảnh = **placeholder theo danh mục** khi thiếu; vẫn nhận `image_url` thật nếu có.
- Đánh giá vẫn qua kiểm duyệt (`pending`→`visible`); chỉ review `visible` hiển thị công khai.
- Mã giảm giá = khung UI + mức cố định đơn giản (không có bảng mã trong DB).
- "Chưa đọc" của hỗ trợ suy từ session (so `updated_at` với mốc đã xem) — reset khi mở ticket.

## 7. Tiêu chí nghiệm thu & test
- Tài khoản chưa mua: không thấy form đánh giá **và** API trả 403 (test).
- Chọn ≥3 sản phẩm ở danh sách → thanh nổi → bảng so sánh (không cần vào từng chi tiết).
- Thả tim trực tiếp trên thẻ; số đếm header cập nhật ngay.
- Giỏ hàng có ảnh, `+/-` tự cập nhật, không còn nút "Cập nhật giỏ".
- Ticket hỗ trợ nhận tin mới không cần reload (polling).
- Không còn cụm 6 nút dưới header. Không lỗi console.
- **Test pytest** (`tests/`): quyền đánh giá (403), giới hạn so sánh (≤4 → 422), tồn kho trong giỏ.

## 8. Thứ tự thực hiện
`5 (ảnh) + 8-giá` → `7 (điều hướng)` → `1 (đánh giá)` → `2 (so sánh)` → `3 (yêu thích)` → `4 (giỏ hàng)` → `6 (hỗ trợ)` → `8 (polish còn lại)` → `Test`.

## 9. Nhật ký tiến độ  *(cập nhật sau mỗi thay đổi — đây là phần quan trọng nhất cho AI kế tiếp)*
Trạng thái: ☐ chưa làm · ◧ đang làm · ☑ xong

- ☑ **Mục 5 — Ảnh sản phẩm** + **Mục 8-giá (VND)** — XONG.
  - `vnd` bỏ `,00` → "13.990.000 ₫" (app/__init__.py).
  - Helper `product_image_src(product)` + `placeholder_for(product)` trong `app/services/image_storage.py`; đăng ký template global trong `app/__init__.py` (giữ nguyên filter `product_image`).
  - 7 SVG placeholder theo danh mục: `app/static/images/placeholders/{laptop,monitor,components,peripherals,network,accessory,default}.svg`.
  - `shop/index.html` thẻ sản phẩm dùng `product_image_src` + `loading="lazy"`; `shop/product.html` có `.product-gallery` (ảnh lớn + thumbnail + zoom hover). CSS ở `storefront.css` + `detail-polish.css`. `py_compile` PASS.
  - ⚠️ Giới hạn: thumbnail swap chỉ markup/CSS (1 ảnh/sản phẩm vì không có bảng gallery, đúng ràng buộc không đổi DB).
- ☑ **Mục 7 — Điều hướng** — XONG.
  - BE: `storefront_context` thêm `compare_count` / `favorite_count` / `support_unread` (+ import `Favorite`) trong `app/shop/routes.py`.
  - FE: `shop/base.html` dựng header mới (ô tìm kiếm + Sản phẩm/Blog + icon So sánh/Yêu thích/Giỏ có badge `data-*-count` + menu tài khoản dropdown) và **đã xoá 2 khối `.feature-links` (cụm 6 nút)**.
  - Mới: `app/static/css/navbar.css`, `app/static/js/storefront-nav.js` (hamburger mobile), `app/templates/shop/_account_sidebar.html`. Sidebar gắn vào `orders.html` / `profile.html` / `order_detail.html`. Parse Jinja OK.
  - ⚠️ Còn lại: gắn sidebar cho `features/*` (favorites, contributions, client_warranties, support_inbox) — làm khi dựng lại từng trang ở Mục 1/2/3/6. `support_unread` tạm = 0, nối thật ở Mục 6.
- ☑ **Mục 1 — Đánh giá** — XONG.
  - BE `product_detail` (shop/routes.py) truyền `review_distribution` (5→1), `can_review`, `my_review`. Chặn 403 vẫn ở `content.py → review()`.
  - `features/reviews.html`: component chọn sao (radio CSS + hover), điểm TB + biểu đồ phân bố, mỗi review có sao + ngày + huy hiệu "Đã mua hàng"; ẩn form nếu không đủ điều kiện ("Chỉ khách đã mua..."), hỗ trợ sửa đánh giá cũ.
  - `product.html` nạp `shop-detail.css` (mới) — file này cũng chứa CSS gallery vì base shop KHÔNG nạp `detail-polish.css`.
  - `features/contributions.html` ("Đánh giá của tôi"): dropdown → chọn sao + gắn sidebar. PY_OK + JINJA_OK.
- ☑ **Mục 2 — So sánh** — XONG.
  - BE `engagement.py`: API JSON `/compare/state`, `/compare/<id>/add`, `/compare/<id>/remove`, `/compare/clear` (session; chặn khác danh mục + giới hạn 4 → 422). `compare_toggle` trả JSON khi gọi XHR. `compare()` truyền `ratings`.
  - FE: nút "So sánh" trên thẻ `index.html`; thanh nổi `shop/_compare_bar.html` + `compare.js` (AJAX + header `X-CSRFToken` + mirror localStorage); trang `features/compare.html` bảng cạnh nhau + tô khác biệt + "Chỉ hiện khác nhau" + thêm giỏ/bỏ. CSS + toast trong `navbar.css`.
  - ⚠️ CSP: `style-src 'self'` chặn `style=""` → biểu đồ phân bố sao set width qua CSSOM trong `compare.js` (`.review-dist__fill[data-pct]`). MỌI JS/CSS phải là file ngoài; AJAX gửi `X-CSRFToken` từ `<meta name="csrf-token">`.
- ☑ **Mục 3 — Yêu thích** — XONG.
  - BE `engagement.py`: `favorite_toggle` trả JSON khi XHR (`favorited`, `count`); thêm `GET /account/favorites/state`.
  - FE: tim trên thẻ `index.html` (client = nút `data-favorite-id`; khách = link `auth.login?next=`), nút tim ở `product.html`, `favorites.js` (optimistic, badge header, xóa thẻ khi bỏ thích ở trang favorites). `favorites.html` dựng lại dạng lưới + trạng thái trống + "Khám phá sản phẩm". CSS tim trong `navbar.css`.
  - ⚠️ `auth.login` dùng allowlist cho `next` (không đụng) → trang chi tiết sau đăng nhập về `/shop` (best-effort).
- ☑ **Mục 4 — Giỏ hàng** — XONG.
  - BE `shop/routes.py`: `_vnd`, `_cart_summary`, `DISCOUNTS`; endpoint `POST /cart/item/<id>` (set số lượng, giới hạn tồn kho/20), `GET /cart/count`, `POST /cart/discount`, `remove_from_cart` trả JSON khi XHR. `cart()` truyền `summary`.
  - FE `cart.html`: mỗi dòng ảnh + tên + SKU + đơn giá + stepper `[−] n [+]` tự cập nhật + thành tiền + nút xoá (xác nhận); tóm tắt sticky (tạm tính/ship/mã giảm/tổng) + "Tiến hành thanh toán" + "← Tiếp tục mua sắm"; giỏ trống có minh hoạ. `cart.js` cập nhật realtime + badge. CSS trong `shop-detail.css`. Bỏ phụ thuộc nút "Cập nhật giỏ".
  - ⚠️ Mã giảm giá chỉ hiển thị ở giỏ (demo, không sửa pipeline đặt hàng). Route cũ `/cart/update` vẫn còn nhưng template không dùng.
- ☑ **Mục 6 — Hỗ trợ** — XONG.
  - BE `app/support.py` `inbox()`: thêm tìm kiếm `?q` (lọc `subject.contains`, tối đa 120 ký tự), tính cờ `unread_ids` từ `session['support_seen']` để hiện chấm chưa đọc; phân trang mang theo cả `status` và `q`. Không đụng hàm khác.
  - FE dựng lại `features/support_inbox.html` (2 cột helpdesk + ô tìm + lọc trạng thái + chấm chưa đọc), `support_detail.html` (chat bong bóng + nút đóng/mở lại cho khách, giữ nguyên form quản lý staff/admin), `support_new.html` (thêm trường Danh mục + sidebar tài khoản); bỏ câu \"Tải lại trang…\" và link \"Tải lại tin nhắn\".
  - Mới `app/static/js/support.js`: polling 5s `/support/<id>/messages`, gửi trả lời qua fetch (`X-CSRFToken`), dựng DOM bằng `textContent`, tự cuộn; giữ form POST thường làm dự phòng. Mới `app/static/css/support.css` (chat + danh sách + chấm chưa đọc, tông xanh).
  - ⚠️ Đính kèm ảnh: TẠM BỎ (cần đổi DB).
- ☑ **Mục 8 — Polish** — XONG.
  - BE `shop/routes.py`: `index()` thêm lọc `brand` (==), `price_min` (>=), `price_max` (<=) với kiểm tra `^[0-9]{1,12}$` (sai → 400) + truyền `brands` (danh sách thương hiệu distinct); `product_detail()` truyền `related` (tối đa 4 sản phẩm cùng danh mục).
  - FE `shop/index.html`: thêm bộ lọc thương hiệu + khoảng giá, huy hiệu tồn kho `.stock-badge` (Còn N / Hết hàng), trạng thái rỗng "Không tìm thấy sản phẩm phù hợp." + nút xóa bộ lọc. `shop/product.html`: tab **Mô tả / Thông số kỹ thuật / Đánh giá** (Bootstrap tabs, không `style=""`) + khối **Sản phẩm liên quan**.
  - CSS ngoài: `.stock-badge*` + `.store-price-range` (storefront.css); `.product-tabs`/`.product-specs`/`.related-grid` (shop-detail.css). Gắn `_account_sidebar.html` cho `favorites.html`, `contributions.html`, `client_warranties.html`. Toast tái dùng `window.tfToast` sẵn có (không trùng lặp).
  - PY_OK + JINJA_OK (parse cú pháp 5 template PASS).
  - ⚠️ Giới hạn: không có bảng gallery nên chi tiết chỉ 1 ảnh + placeholder; skeleton loading để tối giản (ưu tiên lọc/tab/liên quan).
- ☑ **Test & nghiệm thu** — XONG (bổ sung).
  - Rà §7: quyền đánh giá 403, giới hạn so sánh >4 → 422, quyền xem ticket (khách khác → 404) **đã có sẵn** trong `tests/test_backlog.py`.
  - Thêm `tests/test_buyer_ui_muc8.py` cho 3 khoảng trống: (1) giỏ hàng kẹp số lượng theo tồn kho (`add_to_cart` không thêm khi vượt; `/cart/item/<id>` kẹp về mức còn lại), (2) so sánh chặn khác danh mục → 422, (3) endpoint polling `/support/<id>/messages` chặn user khác → 404.
  - `py_compile` test + app = PASS. ⚠️ Chưa chạy được `pytest -q` tại máy này: interpreter local thiếu `flask_login` + các test buyer-UI yêu cầu MySQL cách ly (`RUN_MYSQL_TESTS=1` + host `db-test` qua Docker). Cần chạy trong runner Docker như các test hiện có.

### Việc cần làm tiếp theo (Next steps cho AI kế tiếp)
> **Tất cả 8 mục + Test đã XONG** (Mục 1–8 ☑, Test ☑). Việc còn lại cho AI/dev kế tiếp:
> 1. **Chạy `pytest -q` trong runner Docker** (`RUN_MYSQL_TESTS=1`, host `db-test`) để xác nhận `tests/test_backlog.py` + `tests/test_buyer_ui_muc8.py` PASS — chưa chạy được tại máy local vì thiếu `flask_login` và DB MySQL cách ly.
> 2. **Rà console trình duyệt** trên các trang chính (index, chi tiết, giỏ, hỗ trợ) để chắc không còn lỗi JS; kiểm tra polling hỗ trợ 5s hoạt động.
> 3. **Giới hạn đã biết (nếu muốn nâng cấp, cần đổi DB — ngoài phạm vi):** đính kèm ảnh ở hỗ trợ; gallery nhiều ảnh ở chi tiết; mã giảm giá thật.
> Luôn giữ `csrf_token` trong mọi POST (form + fetch gửi `X-CSRFToken`) và CSP `style-src 'self'` (không `style=""`).
