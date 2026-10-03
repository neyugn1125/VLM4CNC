# VLM4CNC - Hướng Dẫn Cài Đặt & Khởi Chạy Hệ Thống

Tài liệu hướng dẫn chi tiết quy trình thiết lập môi trường, cấu hình mô hình trí tuệ nhân tạo (Local Ollama & Cloud API), khởi chạy giao diện làm việc CAD/CAM trên Linux (Ubuntu 24.04), kết nối FastMCP Server và quy trình tự động đóng gói file thực thi `.exe` độc lập trên Windows.

---

## 1. Giới thiệu tổng quan hệ thống

VLM4CNC là trạm gia công kỹ thuật CAD/CAM tích hợp mô hình thị giác ngôn ngữ lớn (Vision-Language Models - VLM) và giao thức Model Context Protocol (MCP) của Anthropic:
- **Đầu vào**: Ảnh bản vẽ kỹ thuật 2D (PNG, JPG, BMP, WebP) ghi kích thước phôi, lỗ tròn khoan và rãnh phay.
- **Tầng AI**: Trích xuất dữ liệu hình học qua mô hình cục bộ ngoại tuyến `qwen2.5vl:7b` (Ollama) hoặc qua Cloud API (`Google Gemini 3.8 Flash`, `OpenAI GPT-5.5 Pro`) ép kiểu cấu trúc Pydantic `DrawingIR`.
- **Cơ chế Human-in-the-Loop**: Bảng tọa độ hiển thị trực quan cho phép kỹ sư kiểm tra, chỉnh sửa, thêm hoặc xóa các lỗ và rãnh nếu AI đọc sai lệch.
- **Tầng CAD/CAM Core**:
  - `core/dxf_engine.py`: Tự động xuất bản vẽ AutoCAD DXF (chuẩn R2010) phân lớp rõ ràng (`STOCK_OUTLINE`, `HOLES`, `SLOTS_CENTERLINE`, `SLOTS_CONTOUR` có bo tròn 2 đầu bán kính R).
  - `core/gcode_engine.py`: Tự động sinh mã lệnh CNC G-Code hoàn chỉnh (chuẩn hệ tọa độ G54, chu trình khoan ngắt phoi G83, chu trình phay rãnh chia nhiều lớp cắt Z step-down).
- **Giao tiếp mở rộng**: Cung cấp FastMCP Server (`mcp_server/server.py`) để các AI Agent khác (như Claude Desktop, Cursor, Antigravity) có thể gọi công cụ sinh file CAD và G-Code qua giao thức stdio.

---

## 2. Yêu cầu hệ thống (System Prerequisites)

### Hệ điều hành được hỗ trợ
- **Linux**: Ubuntu 22.04 LTS hoặc Ubuntu 24.04 LTS (đã kiểm thử và chạy ổn định).
- **Windows**: Windows 10 hoặc Windows 11 (64-bit).

### Phiên bản Python
- Python 3.10, 3.11 hoặc 3.12 (khuyến nghị Python 3.12).

### Cấu hình phần cứng
- **Khi sử dụng Cloud API (Gemini / OpenAI)**:
  - CPU: Bất kỳ vi xử lý 64-bit nào (Intel Core i3 / AMD Ryzen 3 trở lên).
  - RAM: Tối thiểu 4 GB RAM.
  - Kết nối mạng Internet ổn định.
- **Khi chạy mô hình AI cục bộ ngoại tuyến (Local Ollama Qwen2.5-VL)**:
  - Bản 7B (`qwen2.5vl:7b`): Khuyến nghị có card đồ họa NVIDIA (VRAM >= 6 GB - 8 GB) hoặc RAM hệ thống >= 16 GB nếu chạy CPU.
  - Bản 3B (`qwen2.5vl:3b`): Hoạt động tốt trên máy tính có 8 GB RAM trở lên hoặc chạy trực tiếp bằng CPU.

---

## 3. Cài đặt & Khởi chạy trên Linux (Ubuntu 24.04 LTS)

### Bước 1: Chuẩn bị mã nguồn
Mở terminal và di chuyển vào thư mục dự án:
```bash
cd ~/Documents/VLM4CNC
```

### Bước 2: Tạo và kích hoạt môi trường ảo (Virtual Environment)
```bash
python3 -m venv .venv
source .venv/bin/activate
```

### Bước 3: Nâng cấp pip và cài đặt các thư viện phụ thuộc
```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### Bước 4: Chạy bộ kiểm thử tự động để xác nhận toàn bộ hệ thống
```bash
QT_QPA_PLATFORM=offscreen pytest tests/ -v
```
Toàn bộ 27/27 bài kiểm thử phải đạt trạng thái `PASSED`.

### Bước 5: Khởi chạy ứng dụng giao diện đồ họa (Desktop GUI)
```bash
python main.py
```
Giao diện ứng dụng 3 cột kỹ thuật (nền trắng kẻ viền đen cổ điển) sẽ xuất hiện:
- **Cột 1**: Nạp ảnh bản vẽ, xem trước ảnh, chọn bộ phân tích AI và nhập khóa API.
- **Cột 2**: Bảng kiểm tra tọa độ Human-in-the-Loop với 3 tab tính năng: Lỗ khoan (Holes), Cạnh biên dạng bao ngoài (Outer Edges), và Rãnh phay (Slots), kèm checkbox tùy chọn phay cạnh bao ngoài.
- **Cột 3**: 
  - Form 10 thông số CAM tiêu chuẩn công nghiệp: `Cut depth Z`, `Plunge feed`, `Cut feed`, `Spindle RPM`, `Safe Z`, `Approach Z`, `Tool diameter Ø`, `Tool number (T)`, `Tool offset (H)`, `Program number (O)` và Chiều sâu cắt mỗi lớp.
  - Các nút xuất bản vẽ AutoCAD DXF và sinh chương trình CNC G-Code.
  - Phân hệ mô phỏng đường chạy dao CNC tương tác đồ họa 2D (Tab 0): Xem trước quỹ đạo dao cắt, vệt cắt dao (Tool Band), gốc tọa độ $O(0,0)$, điều khiển hoạt ảnh chạy dao (Chạy/Tạm dừng, Từng bước, Đặt lại, Tốc độ 1x-10x, Thanh trượt tua bước), bảng hiển thị thời gian thực tọa độ và thông số DRO ($X, Y, Z, F, S$, câu lệnh hiện hành) và thống kê chu trình gia công.
  - Tab 1: Xem trước mã chương trình G-Code chi tiết.
  - Tab 2: Nhật ký tiến trình đóng dấu thời gian.

### Bước 6: Khởi chạy chế độ FastMCP Server (Nếu cần tích hợp AI Agent)
Để chạy MCP Server cho các công cụ lập trình AI (Claude Desktop, Cursor, v.v.):
```bash
python main.py --server
```
Server sẽ chạy giao thức stdio và sẵn sàng cung cấp 2 tool: `export_dxf_tool` và `generate_gcode_tool`.

---

## 4. Thiết lập mô hình AI ngoại tuyến qua Ollama (Chạy Offline 100%)

Nếu bạn muốn xử lý bản vẽ hoàn toàn bảo mật trong mạng nội bộ mà không gửi dữ liệu ra ngoài:

### Bước 1: Cài đặt Ollama trên Ubuntu
Chạy lệnh cài đặt tự động từ trang chủ Ollama:
```bash
curl -fsSL https://ollama.com/install.sh | sh
```

### Bước 2: Tải mô hình thị giác Qwen2.5-VL
Chạy một trong hai lệnh sau tùy thuộc vào cấu hình phần cứng của bạn:

- **Bản 7B (Khuyến nghị cho độ chính xác cao)**:
  ```bash
  ollama run qwen2.5vl:7b
  ```
- **Bản 3B (Bản siêu nhẹ cho máy ít RAM / chạy CPU)**:
  ```bash
  ollama run qwen2.5vl:3b
  ```

*Ghi chú: Lệnh trên sẽ tự động tải các lớp trọng số của mô hình (dung lượng khoảng 3 GB - 4.7 GB). Sau khi tải xong, Ollama sẽ duy trì dịch vụ nền tại địa chỉ `http://localhost:11434`.*

### Bước 3: Sử dụng trên giao diện VLM4CNC
1. Khởi động ứng dụng: `python main.py`.
2. Tại Cột 1, dropdown **Bộ phân tích AI**, chọn `Local Ollama: Qwen2.5-VL 7B (qwen2.5vl:7b)` hoặc `3B`.
3. Ô nhập khóa API sẽ tự động vô hiệu hóa vì mô hình cục bộ không cần khóa truy cập.
4. Kéo thả file ảnh bản vẽ vào khung và bấm **"Bắt đầu phân tích AI"**.

---

## 5. Sử dụng Cloud API (Google Gemini & OpenAI)

Nếu bạn chưa cài Ollama hoặc muốn tận dụng sức mạnh tính toán đám mây:

### 1. Google Gemini API (Khuyến nghị - Tốc độ cao, có gói miễn phí)
1. Truy cập [Google AI Studio](https://aistudio.google.com/) để lấy khóa API miễn phí.
2. Bạn có thể thiết lập biến môi trường trước khi chạy:
   ```bash
   export GEMINI_API_KEY="AIzaSy..."
   ```
   Hoặc nhập trực tiếp vào ô **"Khóa API (API Key)"** trên giao diện ứng dụng.
3. Trong dropdown, chọn:
   - `Google Gemini: 3.8 Flash (Khuyến nghị)` (phiên bản mới nhất, xử lý thị giác và kích thước dóng siêu nhanh).

### 2. OpenAI API
1. Lấy khóa API tại [OpenAI Platform](https://platform.openai.com/).
2. Thiết lập biến môi trường:
   ```bash
   export OPENAI_API_KEY="sk-..."
   ```
   Hoặc nhập trực tiếp vào ô **"Khóa API (API Key)"** trên giao diện ứng dụng.
3. Trong dropdown, chọn:
   - `OpenAI: GPT-5.5 Pro` (suy luận hình học bản vẽ kỹ thuật nâng cao).

*Ghi chú: Ứng dụng tự động ghi nhớ riêng khóa API của từng nhà cung cấp trong phiên làm việc. Khi bạn chuyển đổi qua lại giữa OpenAI và Gemini, khóa của từng bên sẽ không bị ghi đè hoặc mất đi.*

---

## 6. Quy trình chuyển sang Windows & Đóng gói File `.exe` Độc Lập

Dự án đã được tích hợp sẵn file kịch bản tự động hóa hoàn chỉnh [`build_windows.bat`](build_windows.bat).

### Các bước thực hiện:
1. Copy toàn bộ thư mục dự án `VLM4CNC` sang máy tính chạy hệ điều hành Windows 10 hoặc Windows 11 (đảm bảo máy đã cài Python 3.10+ từ [python.org](https://www.python.org/downloads/) và đã tích chọn **"Add Python to PATH"**).
2. Nhấp đúp chuột vào file:
   ```cmd
   build_windows.bat
   ```
   *(hoặc mở Command Prompt gõ `build_windows.bat`)*.
3. Script sẽ tự động thực hiện:
   - Kiểm tra môi trường Python trên Windows.
   - Khởi tạo virtual environment tại `.venv`.
   - Cập nhật pip và cài đặt toàn bộ thư viện từ `requirements.txt` cùng `pyinstaller`.
   - Dọn dẹp thư mục build cũ và thực thi lệnh đóng gói:
     ```cmd
     pyinstaller --noconsole --onefile --name="CAD_CAM_AI_Tool" --add-data "core;core" --add-data "vision;vision" --add-data "ui;ui" --clean main.py
     ```
4. Khi quá trình hoàn tất, file thực thi độc lập sẽ nằm tại:
   ```cmd
   dist\CAD_CAM_AI_Tool.exe
   ```
5. Bạn có thể copy trực tiếp file `dist\CAD_CAM_AI_Tool.exe` sang bất kỳ máy tính Windows nào khác để sử dụng ngay mà không cần cài đặt Python.

---

## 7. Kiểm thử nhanh với dữ liệu mẫu có sẵn

Dự án có sẵn file ảnh bản vẽ cơ khí chuẩn kỹ thuật tại:
[`outputs/sample_mechanical_drawing.png`](outputs/sample_mechanical_drawing.png)
- Bản vẽ gồm phôi chữ nhật 100x100x10 mm.
- 3 lỗ khoan Ø10 tại tọa độ (25, 25), (25, 75), (75, 50).
- Đường rãnh phay bo cong rộng 8mm theo đường tâm (10, 50) -> (10, 10) -> (60, 10) -> (80, 30).

Bạn có thể kéo trực tiếp file ảnh này vào Cột 1 của giao diện để kiểm tra toàn trình từ khâu AI bóc tách đến khâu xuất bản vẽ DXF và G-Code.

---

## 8. Xử lý các sự cố thường gặp (Troubleshooting)

### 1. Lỗi hiển thị Qt trên môi trường Linux không có màn hình (Headless / SSH)
- **Hiện tượng**: `qt.qpa.xcb: could not connect to display` hoặc `Could not load the Qt platform plugin "xcb"`.
- **Khắc phục**: Khi chạy các bài kiểm thử tự động trên terminal không có giao diện, hãy thêm biến môi trường:
  ```bash
  QT_QPA_PLATFORM=offscreen pytest tests/ -v
  ```
- Nếu chạy giao diện thật, đảm bảo biến `DISPLAY` hợp lệ (ví dụ: `export DISPLAY=:0` hoặc `export DISPLAY=:1`).

### 2. Lỗi kết nối Ollama (`Cannot connect to local Ollama server`)
- **Hiện tượng**: Ứng dụng báo không thể kết nối tới `http://localhost:11434`.
- **Khắc phục**:
  - Kiểm tra xem Ollama service đã chạy chưa:
    ```bash
    curl http://localhost:11434
    ```
    (Nếu chạy đúng, kết quả sẽ trả về `Ollama is running`).
  - Nếu chưa chạy, khởi động bằng lệnh:
    ```bash
    ollama serve
    ```

### 3. Lỗi thiếu khóa API khi chọn Cloud Engine
- **Hiện tượng**: Khi bấm "Bắt đầu phân tích AI", ứng dụng báo hộp thoại cảnh báo `Thiếu khóa API`.
- **Khắc phục**: Nhập khóa tương ứng vào ô "Khóa API (API Key)" tại Cột 1 hoặc export biến môi trường `GEMINI_API_KEY` / `OPENAI_API_KEY` trong terminal trước khi khởi chạy ứng dụng.
