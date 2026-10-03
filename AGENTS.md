# Agent Guidelines & Collaboration Rules

Tất cả các AI coding agents (Antigravity, Cursor, Claude Code, Codex CLI, Aider, v.v.) và các lập trình viên làm việc trên repository này **BẮT BUỘC** tuân thủ các quy tắc sau đây để đảm bảo tính nhất quán và tính linh hoạt khi chuyển đổi giữa các agent.

---

## 1. BẮT BUỘC TRÌNH BÀY IMPLEMENTATION PLAN TRƯỚC KHI CODE (Plan Before Code)

- **Quy tắc**: Tuyệt đối **KHÔNG** được viết, sửa, xóa mã nguồn trước khi trình bày kế hoạch triển khai (Implementation Plan) cho người dùng duyệt.
- **Quy cách thực hiện**:
  1. Phân tích yêu cầu, khảo sát codebase.
  2. Trình bày **Implementation Plan** trực tiếp (dưới dạng Plan Artifact hoặc bảng kế hoạch trong phiên làm việc). **KHÔNG lưu các file plan tạm vào thư mục mã nguồn của repository**.
  3. Nội dung Plan bắt buộc bao gồm:
     - **Mục tiêu & Yêu cầu** (Objective & Requirements).
     - **Phương án kỹ thuật** (Technical Approach & Architecture).
     - **Danh sách file bị ảnh hưởng** (Files to Create / Modify / Delete).
     - **Các bước thực hiện chi tiết** (Step-by-step Implementation Steps).
     - **Phương án kiểm thử & xác minh** (Verification & Testing Strategy).
  4. Đợi người dùng bấm xác nhận / duyệt plan trước khi tiến hành chỉnh sửa mã nguồn.

---

## 2. BẮT BUỘC CẬP NHẬT CHANGELOG (Centralized Changelog Tracking)

- **Quy tắc**: MỌI thay đổi về mã nguồn, cấu hình hoặc cấu trúc thư mục từ BẤT KỲ agent nào đều phải được ghi nhận đầy đủ vào duy nhất một file: [`CHANGELOG.md`](CHANGELOG.md) tại thư mục gốc.
- **Mục đích**: Lưu trữ ngữ cảnh dự án liên tục, giúp các AI agent khác nhau (và con người) nắm bắt được tiến độ và trạng thái hiện tại mà không bị mất dấu ngữ cảnh.
- **Quy trình thực hiện**:
  - Ngay sau khi hoàn thành các thay đổi code hoặc trước khi kết thúc lượt phản hồi, agent phải cập nhật [`CHANGELOG.md`](CHANGELOG.md).
  - Nội dung mỗi mục log phải theo đúng định dạng chuẩn:
    - **Thời gian**: `[YYYY-MM-DD HH:mm]`
    - **Agent / Tác giả**: `[Tên Agent / Model]` (ví dụ: `[Antigravity / Gemini]`, `[Cursor / Claude]`, `[Human]`)
    - **Tham chiếu Plan**: Đường dẫn tới file plan tương ứng
    - **Danh sách file thay đổi**: Ghi rõ trạng thái (Created / Modified / Deleted)
    - **Chi tiết thay đổi**: Phân loại theo `Added`, `Changed`, `Fixed`, `Removed`
    - **Ghi chú cho Agent kế tiếp**: Ngữ cảnh lưu ý, việc cần làm tiếp theo

---

## 3. NGUYÊN TẮC BẢO TOÀN & CODE QUALITY

- Giữ nguyên các chú thích, cấu trúc mã nguồn hiện hữu trừ khi nằm trong kế hoạch tái cấu trúc.
- Đảm bảo kiểm tra cú pháp và khả năng chạy sau mỗi lần chỉnh sửa.
- Tạo liên kết markdown `[filename](file:///path/to/file)` khi đề cập đến file.
