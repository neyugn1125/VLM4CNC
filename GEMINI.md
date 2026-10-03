# Quy tắc phát triển dự án (Workspace Rules)

Tất cả các hành động của agent trên dự án này phải tuân thủ nghiêm ngặt các nguyên tắc dưới đây (đã đồng bộ với [AGENTS.md](AGENTS.md)):

---

## 1. Luôn cung cấp Implementation Plan trước khi code
- **Yêu cầu**: Trước khi tạo, sửa hoặc xóa bất kỳ file mã nguồn nào, agent PHẢI trình bày Implementation Plan chi tiết (dưới dạng Plan Artifact hoặc bảng kế hoạch trực tiếp trong phiên tương tác). **Tuyệt đối không lưu các file plan tạm vào cấu trúc thư mục của repository**.
- **Nội dung Plan**:
  - Mục tiêu công việc
  - Thiết kế / Phương án giải quyết
  - Danh sách file thay đổi (Create / Modify / Delete)
  - Kế hoạch thực hiện từng bước
  - Phương pháp kiểm tra / xác thực
- **Xác nhận**: Đợi người dùng xác nhận kế hoạch trước khi tiến hành code.

---

## 2. Tất cả thay đổi code phải lưu vào CHANGELOG.md
- **Yêu cầu**: Bất kỳ thay đổi code nào được thực hiện đều phải được ghi chép vào file [CHANGELOG.md](CHANGELOG.md) ở thư mục gốc.
- **Mục đích**: Đảm bảo tính liên tục của dự án khi làm việc với nhiều AI agent khác nhau (Antigravity, Cursor, Claude Code, v.v.).
- **Định dạng ghi**:
  - Thời gian (`YYYY-MM-DD HH:mm`)
  - Agent thực hiện (`[Antigravity / Gemini]`, v.v.)
  - Plan tương ứng
  - Danh sách file thay đổi
  - Mô tả chi tiết (Added / Changed / Fixed / Removed)
  - Lưu ý / Bước tiếp theo cho agent kế tiếp
