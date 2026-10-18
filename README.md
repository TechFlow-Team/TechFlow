# TechFlow

Hệ thống quản lý kinh doanh thiết bị công nghệ — đồ án Flask, Docker và Amazon EC2.
Các chức năng mở rộng gồm theo dõi đơn, đánh giá sau mua, yêu thích/so sánh,
bảo hành cá nhân, cảnh báo kho, báo cáo CSV, nhóm quyền Staff, blog, bình luận
và hộp thư hỗ trợ. Xem [hướng dẫn phát hành và migration](docs/FEATURES_RELEASE.md).
**Trạng thái: Giai đoạn 1–6, gồm khách hàng 5.1 và bảo hành 5.2, đã được tích hợp
vào main tại baseline `ba70f97`. Đợt UI/UX trước Giai đoạn 7 đã được nghiệm thu
trên branch `feature/ui-ux-before-stage-7`.**

Có đăng nhập username/email, phân quyền Admin/Staff, hai workspace riêng và
sidebar xổ xuống. Catalog lưu vào MySQL; nhập/bán cập nhật tồn bằng transaction,
có hồ sơ khách/lịch sử mua, bảo hành và Dashboard thống kê dữ liệu thật.
Báo cáo doanh thu và xuất CSV đã được bổ sung, xem hướng dẫn phát hành ở trên. Phần chuẩn bị production/AWS đang được
thực hiện riêng; môi trường demo hiện dùng EC2, RDS, ECR, S3 và domain DuckDNS
tại `ap-southeast-2`. GitHub Actions đã được cấu hình cho CI/CD; trạng thái xác nhận
deploy mới nhất và các việc vận hành còn lại xem [hành trình dự án](docs/PROJECT_JOURNEY_AND_PRESENTATION.md).

Đặc tả chính thức: [tech_business_manager_aws_spec.md](tech_business_manager_aws_spec.md).

Mỗi giai đoạn dùng một báo cáo tổng hợp:

| Giai đoạn | Báo cáo |
| --- | --- |
| 1 — Nền tảng Flask, Docker, MySQL | [Giai đoạn 1](docs/STAGE_1_REPORT.md) |
| 2 — Database và seed | [Giai đoạn 2](docs/STAGE_2_REPORT.md) |
| 3 — Authentication, phân quyền, hai workspace | [Giai đoạn 3](docs/STAGE_3_REPORT.md) |
| 4 — Catalog CRUD và các đợt UI/UX | [Giai đoạn 4](docs/STAGE_4_REPORT.md) |
| 5 — Nhập/bán, khách hàng 5.1, bảo hành 5.2 và UI chi tiết | [Giai đoạn 5](docs/STAGE_5_REPORT.md) |
| 6 — Dashboard và thống kê | [Giai đoạn 6](docs/STAGE_6_REPORT.md) |

Hướng dẫn nghiệp vụ: [Catalog](docs/CATALOG.md), [Kho/bán hàng](docs/INVENTORY.md),
[Khách hàng](docs/CUSTOMERS.md), [Bảo hành](docs/WARRANTY.md),
[Dashboard](docs/DASHBOARD.md).

## Yêu cầu

- Docker Desktop với Linux Engine đang chạy và Docker Compose.
- Internet để build images và cài dependencies.
- Cổng localhost 8000 trống (đổi APP_PORT nếu cần).

Nếu `docker version` chỉ có Client, làm theo
[hướng dẫn xử lý Engine](docs/DOCKER_TROUBLESHOOTING.md) trước khi chạy container.

## Chạy local bằng Docker (PowerShell)

```powershell
Set-Location E:\AWS
# Chỉ tạo .env khi chưa có; giữ nguyên secrets/database của dự án hiện tại.
if (!(Test-Path .env)) { Copy-Item .env.example .env }
```

Điền SECRET_KEY (ít nhất 32 ký tự), MYSQL_PASSWORD, MYSQL_ROOT_PASSWORD bằng
ba giá trị ngẫu nhiên khác nhau. Có thể tạo từng giá trị bằng PowerShell:

```powershell
$secretBytes = New-Object byte[] 32
$generator = [System.Security.Cryptography.RandomNumberGenerator]::Create()
$generator.GetBytes($secretBytes)
[Convert]::ToBase64String($secretBytes)
$generator.Dispose()
```

Lặp lại để tạo các giá trị khác nhau, giữ chúng riêng trên máy. Đặt giá trị `.env`
trong dấu nháy đơn nếu chứa ký tự đặc biệt. Không commit `.env`. DATABASE_URL để
trống: app tự xây URL an toàn từ MYSQL_* và DB_HOST. Không đưa MYSQL_ROOT_PASSWORD
vào container web; user ứng dụng chỉ dùng database riêng.

```powershell
docker compose config --quiet
docker compose up --build -d
docker compose ps
docker compose exec web flask --app wsgi check-db
Invoke-RestMethod http://localhost:8000/health
```

Mở http://localhost:8000/login để đăng nhập; `/dashboard` yêu cầu xác thực.
Trang `/` vẫn là thông tin nền tảng công khai. `/health`
trả `{"status":"ok"}` khi Flask phản hồi; endpoint này không chứng minh DB hoạt động.
Lệnh `check-db` mới kiểm tra MySQL thực sự.

## Khởi tạo database và dữ liệu demo

Sau khi services healthy, chạy migration một lần có kiểm soát:

```powershell
docker compose exec web flask --app wsgi db upgrade
docker compose exec web flask --app wsgi db current
docker compose exec web flask --app wsgi db check
docker compose exec web flask --app wsgi seed-demo
```

Revision hiện tại `f005_client_index`. Seed chỉ thêm bản ghi thiếu, không reset dữ liệu;
chạy lại tạo mới 0 bản ghi nếu dữ liệu DEMO đã đủ. Database demo trên máy này đã
được upgrade và seed. Bảng stage1_probe và volume hiện tại được giữ nguyên.

Tạo Admin với mật khẩu do bạn chọn tại prompt ẩn (nhập hai lần, 12–128 ký tự):

```powershell
docker compose exec web flask --app wsgi create-admin --username admin --full-name "Quản trị TechFlow"
```

Email tùy chọn bằng `--email`. Không có mật khẩu mặc định; seed không tạo user.
Trùng username/email bị từ chối, không reset password. Dùng username `admin`
(hoặc email đã cung cấp) và mật khẩu vừa nhập tại trang Login. Không gửi mật khẩu
qua chat hoặc ghi vào command. Nếu đã tạo Admin, tiếp tục dùng tài khoản hiện có;
CLI không ghi đè mật khẩu hoặc role.

## Đăng nhập, phân quyền và giao diện

- Login bằng username/email không phân biệt hoa thường; mật khẩu được kiểm tra với
  hash scrypt trong MySQL. Tài khoản inactive bị chặn, kể cả phiên đã đăng nhập.
- Admin vào `/admin/dashboard`, Staff vào `/staff/dashboard` ngay sau login.
  `/dashboard` chuyển tới trang chủ theo vai trò; `/admin` chỉ Admin mới được
  chuyển tới Dashboard quản trị. Admin được vào cả hai Dashboard, Staff bị chặn
  tại các route Admin. Hai layout/menu giữ riêng; chưa có CRUD tài khoản/cấu hình.
  Sidebar Admin có **Không gian kinh doanh**; topbar Business của Admin có
  **Quay về quản trị** (mobile hiện icon có nhãn hỗ trợ). Chuyển qua lại không
  đăng nhập lại hoặc đổi role.
- Đăng xuất qua nút trên topbar bằng POST + CSRF. CSRF được bật toàn cục.
- Sai 5 lần trong 15 phút sẽ tạm chặn đăng nhập tài khoản, dùng chung giới hạn giữa
  username/email và giữa các Gunicorn workers. Nginx còn giới hạn POST Login theo IP.
- Session ký bằng SECRET_KEY, thời gian sống 8 giờ có gia hạn khi hoạt động;
  HttpOnly, SameSite=Lax, Secure bắt buộc ở production HTTPS. Local HTTP để Secure=false.
- Sidebar navy, nội dung sáng, Bootstrap Icons và assets Bootstrap lưu nội bộ.
  Sidebar 244px, thu gọn desktop 80px, offcanvas tablet/mobile và scrollbar tinh tế.
  Admin có tài khoản, ma trận quyền chỉ đọc và SELECT 1 kiểm tra MySQL tại thời điểm
  tải trang. Business có menu CRUD hoạt động; tác vụ nhập/bán/kho vẫn khóa.
  Module chưa triển khai hiển thị trạng thái; không có nút CRUD giả hay số liệu KPI giả.

Chi tiết bảo mật và tích hợp module sau: [docs/AUTHENTICATION.md](docs/AUTHENTICATION.md).

## Quản lý dữ liệu kinh doanh — Giai đoạn 4

Đăng nhập bằng tài khoản hiện có; Admin chọn **Không gian kinh doanh** trên sidebar.
Admin và Staff đều được dùng ba module theo yêu cầu quyền mới:

| Module | Đường dẫn |
| --- | --- |
| Danh mục sản phẩm | http://localhost:8000/business/categories |
| Nhà cung cấp | http://localhost:8000/business/suppliers |
| Sản phẩm | http://localhost:8000/business/products |

Mỗi module có danh sách, chi tiết, thêm, sửa, xóa có xác nhận, tìm kiếm, sắp xếp,
lọc trạng thái và phân trang. Sản phẩm lọc thêm danh mục/nhà cung cấp. Giá dùng
Decimal, hiển thị VND; nhập `15.000.000,50` hoặc `15000000,50` khi có JavaScript
(không JS dùng `15000000.50`). Tồn kho chỉ xem; sản phẩm mới
có tồn kho 0. Không tạo phiếu nhập, đơn bán hoặc stock movement.

Không xóa dữ liệu có liên kết hoặc sản phẩm còn tồn kho; dùng tùy chọn ngừng
hoạt động ở form sửa. Các thao tác thành công và audit được commit cùng nhau.
Không cần migration mới, không chạy lại seed trên database hiện có.

Sau khi cập nhật code, chạy `docker compose up --build -d --wait`, rồi
`docker compose exec nginx nginx -s reload` để Nginx nhận địa chỉ container mới.
Giữ nguyên `.env`, tài khoản và volume hiện tại. Giai đoạn 4 đã được chấp thuận
lưu bằng commit local; không tự động push. Giai đoạn 3 đã push tại commit `09e9c4b`.

Xem [schema và ERD](docs/DATABASE.md). Không chạy downgrade hoặc xóa volume trên
database đang dùng. `db check` so sánh schema với models, tự bỏ qua bảng probe.

```powershell
docker compose logs --tail 100 web nginx
docker compose stop
docker compose start
```

Để recreate sau khi sửa code: `docker compose up --build -d`.
Để dừng và gỡ container/network: `docker compose down` (giữ named volume).
Không thêm `-v`: thao tác này xóa dữ liệu volume.

## Kiểm thử

Tests nền tảng không kết nối DB hoặc tạo/xóa schema. Chạy trong runner biệt lập:

```powershell
docker compose -f docker-compose.test.yml run --build --rm tests
```

Hoặc dùng Python 3.12 local, không cần Docker để test Flask:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest
```

Các bài database được skip khi chưa bật runner MySQL. Chạy đầy đủ trên MySQL riêng:

```powershell
docker compose -f docker-compose.db-test.yml run --build --rm tests
docker compose -f docker-compose.db-test.yml stop db-test
```

Runner áp dụng migration rồi chạy cả tests nền tảng và database. DB/network/volume
test tách khỏi demo; không xóa/reset database hay volume. Giữ dữ liệu test giữa các lần chạy.

Kiểm tra trình duyệt tùy chọn (Chromium; cần Python local và tải browser một lần):

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-ui.txt
$env:PLAYWRIGHT_BROWSERS_PATH = 'E:\AWS\.browser-cache'
.\.venv\Scripts\python.exe -m playwright install chromium
# Chạy runner MySQL ở trên trước để có image test và schema.
docker compose -f docker-compose.db-test.yml --profile ui up -d --wait ui-nginx
.\.venv\Scripts\python.exe scripts/verify_ui.py --screenshot-prefix stage4-ui-regression
.\.venv\Scripts\python.exe scripts/verify_catalog_ui.py --screenshot-prefix stage4-ui
docker compose -f docker-compose.db-test.yml --profile ui stop ui-nginx ui db-test
```

Scripts tạo tài khoản có mật khẩu ngẫu nhiên và dữ liệu CRUD trong DB test, lưu ảnh vào
`docs/screenshots`; không in credentials, không thay đổi demo. Kiểm tra ba viewport
desktop/tablet/mobile cho cả hai vai trò, menu, collapse, hover/focus bàn phím,
login/logout, 403/404, link/anchor thực, CRUD thật, modal, validation và tràn ngang. Khi image UI thay
đổi địa chỉ container, restart riêng `ui-nginx` nếu gặp 502.

Chạy app local tùy chọn: load `.env` qua wsgi rồi dùng
`.\.venv\Scripts\python.exe -m flask --app wsgi run --host 127.0.0.1 --port 8000`.
Chỉ dùng dev server local. MySQL trong Compose không publish cổng; app local muốn
kết nối DB cần MySQL riêng và DB_HOST/DATABASE_URL phù hợp. Docker là đường chạy chính.

## Kiểm tra lưu trữ sau khi Engine hoạt động

Agent đã chạy kiểm tra này trên Docker local; xem kết quả trong báo cáo giai đoạn 1.
Để chạy lại bằng script (tạo dòng probe, restart riêng service db, không xóa dữ liệu):

```powershell
.\.venv\Scripts\python.exe scripts/verify_local_storage.py
```

Bảng `stage1_probe` là bảng kiểm tra riêng, cần loại khỏi Alembic autogenerate khi
thiết lập migrations. Script giữ lại dòng probe để đối chiếu. Phương án kiểm tra thủ công:

Giai đoạn 1 chưa có bảng nghiệp vụ. Có thể kiểm tra volume với bảng probe tạm,
chạy thủ công trong MySQL CLI. Chỉ tạo bảng probe ở database local demo:

```powershell
docker compose exec db mysql -u techflow_app -p tech_business_db
```

Thay user/database theo `.env`; nhập password tại prompt, không truyền password
trong lịch sử command. Trong MySQL:

```sql
CREATE TABLE IF NOT EXISTS stage1_probe (id INT PRIMARY KEY, marker VARCHAR(50)) ENGINE=InnoDB;
INSERT INTO stage1_probe VALUES (1, 'techflow-volume-check');
exit
```

Chạy `docker compose restart db`, chờ db healthy, đăng nhập MySQL lại rồi:

```sql
SELECT * FROM stage1_probe;
```

Kết quả cần giữ nguyên marker. Bảng probe do bạn tạo có thể giữ để đối chiếu hoặc
xóa thủ công sau khi kiểm tra; ứng dụng không tự tạo/xóa bảng này.

## Tài liệu nhóm

- [Kiến trúc và ranh giới module](docs/ARCHITECTURE.md)
- [Các quyết định kỹ thuật](docs/DECISIONS.md)
- [Database và ERD](docs/DATABASE.md)
- [Git workflow và quy ước code](docs/GIT_WORKFLOW.md)
- [Bảo mật và vận hành local](docs/SECURITY.md)
- [Authentication và quyền truy cập](docs/AUTHENTICATION.md)
- [Catalog CRUD và quy ước nhập giá VND](docs/CATALOG.md)

Compose mặc định dành cho localhost; `docker-compose.prod.yml` dành cho EC2/RDS.
HTTPS public đã được thiết lập. Backup/restore production, gia hạn certificate tự
động và kiểm tra tải vẫn cần được hoàn thiện trước khi coi đây là hệ thống production.

Tài liệu chuẩn bị EC2, RDS và GitHub Actions: [AWS deployment](docs/AWS_DEPLOYMENT.md).
`docker-compose.prod.yml` chỉ dành cho máy chủ production sau khi đã có RDS riêng,
DNS và chứng chỉ HTTPS. Không dùng `.env` local hoặc seed dữ liệu demo trên production.

## Bảo hành và Sidebar (5.2)

Trong Không gian kinh doanh, các nhóm Đơn hàng/Kho hàng/Hậu mãi/Tài khoản mở bằng
click hoặc Enter/Space. Hậu mãi → Tra cứu bảo hành tìm giao dịch completed; chọn
thiết bị để tiếp nhận. Admin cấu hình chính sách trong form sản phẩm và xác minh
đơn cũ; Staff xử lý phiếu mình tạo hoặc được phân công. Còn hạn không tự động
đồng nghĩa được bảo hành miễn phí. Không đổi kho hoặc hoàn tiền từ phiếu bảo hành.

- [Hướng dẫn, schema, ERD, quyền và transaction bảo hành](docs/WARRANTY.md)
- [Khách hàng và lịch sử mua](docs/CUSTOMERS.md)
- [Đề xuất Cài đặt hệ thống cho giai đoạn sau](docs/SYSTEM_SETTINGS_PROPOSAL.md)
- [Tinh chỉnh chi tiết giao dịch và bảo hành trước Giai đoạn 7](docs/STAGE_5_REPORT.md#ui-ux-truoc-giai-doan-7)

Kiểm tra liên kết tài liệu bằng `python scripts/verify_document_links.py`.
Backup/restore kiểm chứng trước migration demo được mô tả trong hướng dẫn bảo hành.
