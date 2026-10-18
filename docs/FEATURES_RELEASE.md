# Chức năng mở rộng TechFlow

Triển khai 10 ID từ `FEATURES_BACKLOG.md`. Mọi thao tác ghi dùng POST + CSRF;
quyền và chủ sở hữu được kiểm tra tại server. Nội dung do người dùng nhập hiển thị
dưới dạng văn bản thuần được Jinja escape, không chấp nhận HTML thực thi.

| ID | Đường dẫn / cách dùng | Chính sách nghiệm thu |
| --- | --- | --- |
| ORD-01 | `/account/orders/<id>`, `/business/sales/<id>` | Chờ xác nhận → Đã xác nhận → Đang giao → Hoàn tất; từ chối trước giao, hoặc hủy theo quy tắc kho hiện hành. Mỗi mốc/ghi chú có người thực hiện, thời gian; lưu nối tiếp. |
| INV-01 | `/business/low-stock`, chi tiết sản phẩm | Tồn thực tế ≤ ngưỡng; tìm tên/SKU, lọc hoạt động, phân trang. Admin sửa ngưỡng cho mọi sản phẩm tại chi tiết; không sửa tồn hoặc tự nhập kho. |
| RPT-01 | `/business/reports` | Ngày/tháng, tối đa 367 ngày, doanh thu đơn hoàn tất, top 50 bán chạy, tồn kho hiện tại, số lượng/giá trị đơn hủy, CSV cùng bộ lọc. |
| IAM-01 | `/admin/staff` | Admin tạo Staff, kích hoạt/vô hiệu hóa, cấp 6 nhóm nhiệm vụ; Staff mới không có quyền nghiệp vụ. |
| BLOG-01 | `/blog`, `/business/content` | Nháp/đã đăng/ẩn, slug duy nhất, tác giả, thời điểm đăng, ảnh bìa tùy chọn và tối đa 10 sản phẩm liên quan đang bán. |
| CMT-01 | Trang bài viết, `/account/contributions`, `/business/moderation` | Client gửi/sửa/xóa của mình; chờ duyệt/hiển thị/ẩn/xóa mềm. Chống gửi nhanh và lặp nội dung. |
| REV-01 | Trang chi tiết sản phẩm, cùng trang quản lý/kiểm duyệt trên | Có đơn hoàn tất mới được đánh giá; 1 bản ghi/khách/sản phẩm, 1–5 sao, tối đa 2000 ký tự; sửa phải duyệt lại. Admin xem tổng hợp theo trạng thái. |
| WAR-01 | `/account/warranties` | Chỉ sản phẩm từ đơn hoàn tất thuộc tài khoản; đọc snapshot chính sách, ngày bắt đầu/kết thúc và lịch sử xử lý hiện hữu; không tính lại theo chính sách sản phẩm mới. |
| CHAT-01 | `/support` | Hộp thư tải lại, chủ đề và đơn hàng tùy chọn, tin nhắn tối đa 2000 ký tự, mới/đang xử lý/đóng; Staff nhận yêu cầu và trả lời trong phạm vi được giao, Admin phân công/mở lại. |
| FAV-01 | `/account/favorites`, `/compare` | Yêu thích lưu database theo tài khoản. So sánh tối đa 4 sản phẩm theo hãng, model, mô tả/cấu hình có sẵn, giá, danh mục, tồn, trạng thái. |

## Quy tắc đơn hàng và kho

`sales_orders.status` tiếp tục dùng `draft/completed/cancelled` cho nghiệp vụ kho
và báo cáo cũ. Cột `fulfillment_status` bổ sung tiến độ giao hàng. Xác nhận/giao
không giữ chỗ và không thay đổi tồn; hoàn tất mới khóa sản phẩm, kiểm tra tồn và
trừ kho một lần. Đơn online phải đi qua xác nhận và đang giao trước hoàn tất.
Đơn nội bộ giữ khả năng hoàn tất trực tiếp của quy trình hiện có.

Client chỉ hủy khi còn chờ xác nhận. Staff chỉ thao tác đơn tự tạo hoặc đơn online;
chỉ Admin được hủy đơn đã hoàn tất, với kiểm tra bảo hành và hoàn kho vốn có.
Hệ thống từ chối gửi lại thao tác hoàn tất/hủy. Ghi chú trong lịch sử là thông tin
hiển thị cho khách; không nhập dữ liệu nội bộ hoặc bí mật vào đó.

Migration thêm một mốc cho mỗi đơn cũ tại thời điểm nâng cấp, có ghi rõ đây là
trạng thái hiện tại, không suy diễn lịch sử cũ hoặc tác giả thao tác.

## Phân quyền Staff

| Nhóm | Quyền |
| --- | --- |
| `orders` | Đơn bán và dữ liệu khách cần thiết theo phạm vi hiện hành |
| `inventory` | Catalog, tồn kho và cảnh báo tồn; nhập kho vẫn chỉ Admin |
| `content` | Soạn/sửa bài nháp của mình, duyệt đánh giá và bình luận |
| `warranty` | Nghiệp vụ bảo hành hiện hành, vẫn giới hạn phiếu tự tạo/được giao |
| `support` | Hàng chờ chưa phân công và hội thoại được giao; nhận và trả lời |
| `reports` | Xem/xuất báo cáo kinh doanh tổng hợp |

Admin có mọi nhóm. Staff không được cấp quyền, xuất bản bài hoặc tự thay đổi
nhóm của mình. Staff cũ được giữ ba quyền đã có (`inventory,orders,warranty`),
không tự nhận quyền báo cáo/nội dung/hỗ trợ. Mỗi request đọc lại tài khoản và
nhóm quyền; thay đổi có hiệu lực từ request tiếp theo, kể cả phiên đang hoạt động.
Vô hiệu hóa ngăn phiên hiện tại và đăng nhập mới. Không đổi khóa session toàn hệ
thống; nếu kích hoạt lại trước khi cookie hết hạn, cookie cũ có thể dùng lại.

## Nội dung, ảnh và chống spam

Staff chỉ sửa bài nháp của chính mình; Admin quản lý và đăng/ẩn mọi bài. Nội dung
bài viết là văn bản thuần, tối đa 50000 ký tự; tiêu đề/slug tối đa 200 ký tự, slug
dùng chữ thường Latin/số/gạch ngang. Bài ẩn/nháp không truy cập được qua URL công khai.
Ảnh bìa dùng cùng pipeline ảnh sản phẩm: kiểm định JPEG/PNG/WebP ≤ 6 MB và
24 megapixel, chuyển WebP, bỏ EXIF; local hoặc S3 theo cấu hình hiện có.

Đánh giá và bình luận mới/sửa luôn chờ duyệt. Màn hình công khai chỉ lấy `visible`.
Xóa là xóa mềm để giữ dấu vết kiểm tra. Audit lưu người thao tác, thời gian,
hành động và lý do duyệt; trường thông tin duyệt trên bản ghi là lần duyệt gần nhất.
Chờ 30 giây giữa các lần gửi/sửa; bình luận trùng trong cùng bài bị từ chối.
Các giới hạn gửi dùng khóa hàng người dùng trong MySQL, có tác dụng giữa workers.

Hỗ trợ: tạo hội thoại cách nhau ≥ 30 giây, tin nhắn cách nhau ≥ 10 giây trên mỗi
tài khoản. Staff chỉ gửi khi đã nhận/được giao hội thoại, không truy cập hội thoại
được giao cho người khác. Client chỉ xem hội thoại của mình và chỉ gắn đơn của mình.
Đóng hội thoại ngăn gửi tiếp; Admin có thể mở lại hoặc phân công lại. Không có
thông báo ngoài ứng dụng hay yêu cầu WebSocket trong phiên bản này.

Khách vãng lai không lưu yêu thích; không có luồng hợp nhất yêu thích khi đăng nhập.
So sánh lưu tối đa 4 ID trong session trình duyệt, có thể mất khi đăng nhập/đăng xuất.
Sản phẩm ngừng bán vẫn xuất hiện đúng trạng thái trong yêu thích/so sánh, không
có nút mua từ các trang này; giỏ/checkout vẫn kiểm tra lại sản phẩm và tồn thực tế.

## Định nghĩa báo cáo và giới hạn danh sách

Doanh thu là tổng `total_amount` của đơn đang `completed`, lọc theo `completed_at`
với ngày/tháng tại `Asia/Ho_Chi_Minh`. Đơn hủy/từ chối loại khỏi doanh thu; số lượng
và giá trị đơn hủy lọc theo **ngày đặt**. Đây là số liệu giá trị đơn, không phải
sổ thanh toán hay dòng tiền đã thu. Tồn kho luôn là số tại thời điểm truy vấn,
không phải ảnh chụp tồn lịch sử. CSV có đủ các phần như màn hình, dùng cùng hàm
truy vấn và tham số; bảo vệ ô văn bản khỏi CSV formula injection.

Top bán chạy: 50 sản phẩm; báo cáo tồn: tối đa 5000 sản phẩm (vượt giới hạn sẽ
từ chối thay vì xuất thiếu). Khoảng ngày tối đa 367 ngày. Có phân trang cho blog,
bình luận công khai, yêu thích, sản phẩm bảo hành, hộp thư/tin nhắn và cảnh báo kho.
Trang đóng góp cá nhân/kiểm duyệt hiển thị tối đa 100 mục gần nhất mỗi loại theo
trạng thái. Trang sản phẩm hiển thị 50 đánh giá được duyệt gần nhất, điểm trung bình
tính từ toàn bộ đánh giá đang hiển thị. Form chọn sản phẩm blog liệt kê tối đa 500
sản phẩm hoạt động, form hỗ trợ liệt kê 100 đơn gần nhất.

## Migration và vận hành

Chuỗi revision mới: `c052_clients` → `f001_orders` → `f002_permissions` →
`f003_content` → `f004_engagement` → `f005_client_index`. Revision cuối chuẩn hóa tên unique index liên kết khách/tài khoản của migration cũ để khớp ORM, không đổi dữ liệu.

Sau khi backup và xác nhận cấu hình trỏ tới database local dự định nâng cấp:

```powershell
docker compose build web
docker compose run --rm web flask --app wsgi db upgrade
docker compose run --rm web flask --app wsgi db check
docker compose up -d --wait web
docker compose exec nginx nginx -s reload
```

Không cần seed/reset. Các bảng/cột mới không thay đổi số lượng tồn, số tiền,
snapshot bảo hành hoặc quyền Admin/Client đã có. Downgrade về `c052_clients`
sẽ loại bỏ dữ liệu chức năng mới, cần xuất/backup trước; không chạy downgrade
trên database đang dùng nếu chưa có kế hoạch bảo toàn dữ liệu. Production/AWS
vẫn theo quy trình backup/review/triển khai riêng trong `AWS_DEPLOYMENT.md`.

## Kiểm thử

```powershell
py -m pytest
docker compose -f docker-compose.db-test.yml run --build --rm tests
```

`tests/test_backlog.py` kiểm tra chuyển trạng thái và trừ/hoàn kho một lần,
quyền/CSRF/chủ sở hữu, snapshot bảo hành, đánh giá sau mua và duyệt lại,
bài nháp/ẩn và escape HTML, chống gửi nhanh, phân công hội thoại, yêu thích,
so sánh và doanh thu theo ngày Việt Nam/CSV. Các fixture nghiệp vụ cũ được cấp
rõ ba nhóm quyền cũ để tiếp tục kiểm tra đúng nghiệp vụ sau khi thêm IAM.

Kiểm chứng tại nhánh triển khai ngày 18/10/2026:

- Toàn bộ suite trên MySQL 8.0.44 riêng: **347 passed**.
- Bộ kiểm thử backlog riêng: **16 passed** (nằm trong tổng trên).
- Sau tinh chỉnh nhãn tiến độ, bộ backlog và quyền được chạy lại: **24 passed**.
- `scripts/verify_backlog_migrations.py`: nâng từ schema cũ, hạ về
  `c052_clients`, nâng lại; schema khớp ORM, tồn và snapshot đơn cũ giữ nguyên.
- `scripts/verify_backlog_ui.py`: **63 lượt trang**, ba role ở 1440, 768,
  390 px; kiểm tra phản hồi, lỗi JavaScript, tràn ngang và chọn so sánh.
- `git diff --check` và biên dịch Python: đạt.
- Trình kiểm tra liên kết tài liệu còn báo bốn ảnh `prestage7-*.png` được nhắc
  trong báo cáo giai đoạn 5 nhưng không có ở baseline repository; các liên kết
  tài liệu mới không phát sinh lỗi. Đây là ảnh chứng cứ cũ, không phải lỗi ứng dụng.

GitHub CI bổ sung job MySQL riêng, chạy migration và toàn bộ suite trên mỗi PR
hoặc push nhánh feature, bên cạnh job Flask biệt lập hiện có.
