# TechFlow — Đề xuất chức năng mở rộng

Tài liệu này mô tả các chức năng đề xuất để giao cho coding agent triển khai ở các giai đoạn sau. Đây là **backlog/đặc tả đề xuất**, không khẳng định các chức năng đã được triển khai. Trước khi bắt đầu mỗi chức năng, cần kiểm tra code và schema hiện tại để tái sử dụng luồng nghiệp vụ sẵn có.

## Mục tiêu

Mở rộng cửa hàng thiết bị công nghệ theo hai phía: khách hàng có thể theo dõi và tương tác với cửa hàng; Admin/Staff có công cụ xử lý đơn, quản lý nội dung và theo dõi hoạt động kinh doanh. Ưu tiên các chức năng có luồng nghiệp vụ đầu cuối và dùng chung dữ liệu hiện tại.

## Phân quyền tổng quát

- **Client:** chỉ đọc/sửa dữ liệu thuộc tài khoản của mình; nội dung công khai được đọc theo trạng thái đã đăng/đã duyệt.
- **Staff:** thực hiện nghiệp vụ được cấp quyền; chỉ xem thông tin khách hàng cần thiết để xử lý đơn/hỗ trợ.
- **Admin:** quản lý người dùng, cấu hình, phân công và xem báo cáo tổng hợp.
- Mọi quyền phải được kiểm tra ở server; ẩn nút trên giao diện không được xem là kiểm soát truy cập.

## Backlog chức năng

| ID | Chức năng | Phía Client | Phía Admin/Staff | Ưu tiên |
| --- | --- | --- | --- | --- |
| ORD-01 | Theo dõi trạng thái đơn hàng | Xem trạng thái, mốc thời gian và ghi chú của từng đơn thuộc mình | Cập nhật trạng thái, thêm ghi chú; hệ thống lưu lịch sử để truy vết | Cao |
| REV-01 | Đánh giá sản phẩm sau mua | Khách có đơn hoàn tất đánh giá sao và nhận xét sản phẩm đã mua | Duyệt/ẩn đánh giá vi phạm; Admin xem tổng hợp | Cao |
| FAV-01 | Yêu thích và so sánh sản phẩm | Lưu sản phẩm yêu thích; chọn sản phẩm để so sánh thuộc tính chính | Không cần thao tác quản trị riêng; dữ liệu sản phẩm lấy từ catalog | Trung bình |
| WAR-01 | Tra cứu bảo hành | Xem thông tin sản phẩm đã mua, thời hạn và trạng thái yêu cầu bảo hành của mình | Nhân viên tiếp nhận/cập nhật xử lý; Admin quản lý chính sách nếu cần | Cao |
| INV-01 | Cảnh báo tồn kho thấp | Không áp dụng trực tiếp | Admin cấu hình ngưỡng; Admin/Staff xem danh sách sản phẩm cần nhập | Cao |
| RPT-01 | Báo cáo kinh doanh | Không áp dụng | Lọc ngày/tháng/khoảng thời gian; xem doanh thu, sản phẩm bán chạy, tồn kho, đơn hủy; xuất CSV | Cao |
| IAM-01 | Phân quyền Staff theo nhiệm vụ | Không áp dụng | Admin tạo tài khoản và cấp quyền theo nhóm nhiệm vụ (ví dụ xử lý đơn, kho, nội dung) | Trung bình |
| BLOG-01 | Blog giới thiệu sản phẩm | Đọc bài đã đăng, xem sản phẩm liên quan, mở trang sản phẩm/mua hàng | Admin tạo/sửa/lưu nháp/đăng; Staff có thể soạn bài nếu được cấp quyền | Cao |
| CMT-01 | Bình luận bài viết | Client đăng bình luận, sửa/xóa bình luận của mình | Admin/Staff duyệt, ẩn hoặc xóa bình luận vi phạm | Cao |
| CHAT-01 | Chat/hộp thư hỗ trợ | Gửi câu hỏi trước/sau khi mua, xem lịch sử hội thoại | Staff tiếp nhận và trả lời; Admin quản lý/phân công và theo dõi hội thoại | Trung bình |

## Đặc tả và tiêu chí nghiệm thu

### ORD-01 — Theo dõi trạng thái đơn hàng

- Luồng hiển thị tối thiểu: **Chờ xác nhận → Đã xác nhận → Đang giao → Hoàn tất**; có nhánh **Bị từ chối/Đã hủy** phù hợp với trạng thái đơn hiện hữu.
- Mỗi lần đổi trạng thái ghi người thực hiện, thời gian và ghi chú; lịch sử không bị ghi đè khi trạng thái mới được cập nhật.
- Client chỉ xem đơn của chính mình. Staff/Admin được phép xử lý theo quyền.
- Quy tắc chuyển trạng thái được kiểm tra phía server và không làm trừ/hoàn tồn kho sai nghiệp vụ.

### REV-01 — Đánh giá sau mua

- Chỉ tài khoản có đơn hoàn tất chứa sản phẩm đó mới được đánh giá; mặc định một đánh giá cho mỗi khách/sản phẩm (có thể sửa theo chính sách).
- Điểm sao nằm trong khoảng 1–5; nội dung được kiểm tra và giới hạn độ dài.
- Đánh giá mới ở trạng thái chờ duyệt hoặc theo chính sách được thống nhất; chỉ đánh giá hiển thị mới xuất hiện công khai.
- Client chỉ sửa/xóa đánh giá của mình; thao tác duyệt/ẩn có kiểm soát quyền và audit.

### FAV-01 — Yêu thích và so sánh

- Khách đăng nhập có danh sách yêu thích lưu bền vững; nếu hỗ trợ khách vãng lai, phải xác định rõ cách hợp nhất khi đăng nhập.
- So sánh tập trung vào thuộc tính phù hợp với thiết bị công nghệ (hãng, danh mục, cấu hình chính, giá, tồn trạng thái).
- Sản phẩm ngừng hoạt động/hết hàng được biểu diễn đúng; không cho thao tác mua trái với tồn kho hiện tại.

### WAR-01 — Tra cứu bảo hành

- Client chỉ thấy các sản phẩm/đơn thuộc tài khoản của mình, ngày bắt đầu/kết thúc bảo hành và trạng thái xử lý.
- Không tự suy diễn hoặc làm thay đổi chính sách bảo hành hiện hành; tận dụng dữ liệu bảo hành hiện có.
- Staff ghi nhận tiến độ xử lý; lịch sử thay đổi có người thực hiện, thời gian và ghi chú.

### INV-01 — Cảnh báo tồn kho thấp

- Admin cấu hình ngưỡng theo sản phẩm hoặc chính sách mặc định; không âm thầm thay đổi tồn kho.
- Danh sách cảnh báo dựa trên tồn thực tế và cho phép lọc/tìm kiếm.
- Cảnh báo không tạo phiếu nhập tự động; thao tác nhập kho vẫn theo quy trình được phân quyền.

### RPT-01 — Báo cáo kinh doanh

- Cho chọn khoảng thời gian và thống nhất định nghĩa doanh thu (ví dụ chỉ tính đơn đã hoàn tất, loại trừ đơn hủy).
- Có ít nhất: doanh thu theo ngày/tháng, sản phẩm bán chạy, tồn kho hiện tại, số lượng/tổng giá trị đơn hủy.
- Tổng hợp từ dữ liệu giao dịch thực, không dùng số liệu mẫu; số liệu và bộ lọc CSV khớp với màn hình.
- Chỉ role được phép xem báo cáo; giới hạn và kiểm tra tham số xuất dữ liệu.

### IAM-01 — Phân quyền Staff

- Admin tạo/kích hoạt/vô hiệu hóa tài khoản và cấp nhóm quyền có tên rõ ràng.
- Quyền được kiểm tra ở route/service; quyền mặc định tối thiểu cần thiết.
- Không cho Staff tự nâng quyền hoặc sửa quyền người khác; thay đổi quyền được audit.
- Xác định chính sách đối với phiên đăng nhập đang hoạt động sau khi tài khoản bị vô hiệu hóa/đổi quyền.

### BLOG-01 — Blog giới thiệu sản phẩm

- Bài viết có tiêu đề, slug, nội dung, ảnh bìa tùy chọn, tác giả, thời điểm đăng và trạng thái **Nháp/Đã đăng/Ẩn**.
- Trang công khai chỉ hiển thị bài đã đăng; bài có thể liên kết một hoặc nhiều sản phẩm đang hoạt động.
- Admin quản lý toàn bộ bài; Staff chỉ tạo/sửa bài theo quyền và không tự cấp quyền xuất bản nếu chính sách yêu cầu duyệt.
- Nội dung được escape/ làm sạch an toàn; ảnh và URL tuân theo quy tắc upload hiện tại.

### CMT-01 — Bình luận

- Chỉ Client đăng nhập được bình luận; nội dung có giới hạn độ dài và chống gửi lặp/spam cơ bản.
- Client chỉ sửa/xóa bình luận của mình; trạng thái tối thiểu **Chờ duyệt/Hiển thị/Ẩn**.
- Admin/Staff có quyền duyệt hoặc ẩn; lưu người duyệt, thời gian và lý do khi cần.
- Bình luận ẩn không xuất hiện trên trang công khai và vẫn có dấu vết kiểm tra cho quản trị.

### CHAT-01 — Hộp thư hỗ trợ

- Phiên bản đầu có thể là hộp thư hội thoại cập nhật khi tải lại trang; chưa bắt buộc chat thời gian thực.
- Client tạo hội thoại, gửi tin nhắn và xem lịch sử của chính mình; có thể gắn đơn hàng liên quan.
- Staff xem hàng chờ, nhận/phân công và trả lời; Admin xem/phân công/quản lý hội thoại.
- Có trạng thái **Mới/Đang xử lý/Đã đóng**, thời gian gửi và người gửi; phân quyền ngăn xem hội thoại ngoài phạm vi.
- Nội dung hiển thị an toàn, có giới hạn kích thước/tần suất gửi và không gửi thông tin bí mật qua thông báo.

## Gợi ý chia giai đoạn triển khai

1. **Giai đoạn A — Hoàn chỉnh giao dịch:** ORD-01, INV-01, RPT-01.
2. **Giai đoạn B — Nội dung và tương tác:** BLOG-01, CMT-01, REV-01.
3. **Giai đoạn C — Dịch vụ khách hàng:** WAR-01, CHAT-01.
4. **Giai đoạn D — Mở rộng vận hành:** FAV-01, IAM-01.

Các giai đoạn là gợi ý; agent triển khai cần kiểm tra khả năng tương thích với schema, role và luồng hiện tại, sau đó chia nhỏ thành migration, service, route, giao diện và kiểm thử phù hợp.

## Hướng dẫn cho coding agent nhận backlog

- Đọc `README.md`, `docs/role-permissions.md`, tài liệu module liên quan và code hiện tại trước khi sửa.
- Triển khai theo từng ID; không cố làm toàn bộ backlog trong một thay đổi lớn.
- Trước khi thêm bảng/cột, kiểm tra model và migration hiện hữu; migration phải an toàn với dữ liệu đang có và có downgrade hợp lý.
- Tôn trọng phân quyền server-side, CSRF, audit, transaction và cách lưu ảnh đang dùng.
- Không đưa secret/dữ liệu cá nhân vào log; không dùng dữ liệu giả cho báo cáo.
- Bổ sung tài liệu hướng dẫn và tiêu chí nghiệm thu cho từng chức năng; nêu rõ migration và lệnh vận hành cần thiết.
