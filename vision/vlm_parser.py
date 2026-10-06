"""
VLM Parser Module for VLM4CNC.
Analyzes 2D mechanical milling/drilling drawings and extracts DrawingIR intermediate representation.
Implements the Adapter Pattern supporting:
  1. 'cloud': OpenAI / Gemini via instructor for direct Pydantic structured outputs.
  2. 'local': Local Ollama API running Qwen2.5-VL-7B-Instruct (Q4_K_M).
"""

from abc import ABC, abstractmethod
import base64
import json
import logging
import os
from pathlib import Path
import re
from typing import Any, Dict, Optional, Tuple, Union

import httpx
from pydantic import ValidationError

from vision.schemas import DrawingIR, DrillHole, Point2D, SlotContour

logger = logging.getLogger("vlm4cnc.vision")

# Optional SDK imports with graceful degradation
try:
    import instructor
    from openai import OpenAI
    HAS_OPENAI = True
except ImportError:
    instructor = None  # type: ignore
    OpenAI = None      # type: ignore
    HAS_OPENAI = False

try:
    from google import genai
    from google.genai import types
    HAS_GEMINI = True
except ImportError:
    genai = None       # type: ignore
    types = None       # type: ignore
    HAS_GEMINI = False


MECHANICAL_ENGINEERING_SYSTEM_PROMPT = """
Bạn là một chuyên gia cao cấp về đo lường hình học và lập trình gia công cơ khí chính xác (CAD/CAM).
Nhiệm vụ của bạn là đọc bản vẽ kỹ thuật gia công phay/khoan 2D và trích xuất cấu trúc dữ liệu phôi, lỗ tròn và rãnh phay theo schema DrawingIR.

CÁC NGUYÊN TẮC QUAN TRỌNG BẮT BUỘC TUÂN THỦ:
1. GỐC TỌA ĐỘ O(0,0):
   - Mặc định nằm ở góc DƯỚI - TRÁI (Bottom-Left) của phôi chữ nhật bao ngoài.
   - Trục X nằm ngang, hướng từ trái sang phải (X >= 0 tăng dần sang phải).
   - Trục Y thẳng đứng, hướng từ dưới lên trên (Y >= 0 tăng dần lên trên).
   - Toàn bộ kích thước hình học đều tính theo đơn vị milimét (mm).

2. KÍCH THƯỚC PHÔI CHỮ NHẬT (STOCK):
   - stock_width: Chiều rộng tổng thể theo phương trục X (mm).
   - stock_height: Chiều cao tổng thể theo phương trục Y (mm).
   - stock_thickness: Chiều dày tấm phôi theo phương trục Z (mm, mặc định 5.0 mm hoặc theo bản vẽ).

3. PHƯƠNG PHÁP SUY LUẬN TỌA ĐỘ CỘNG DỒN (DIMENSION CHAINING):
   - Các kích thước trên bản vẽ cơ khí thường được dóng từ cạnh chuẩn (Datum edges).
   - Tọa độ X tuyệt đối = Khoảng cách dóng từ mép chuẩn BÊN TRÁI tới tâm đối tượng (cộng dồn nếu dóng theo chuỗi).
   - Tọa độ Y tuyệt đối = Khoảng cách dóng từ mép chuẩn BÊN DƯỚI tới tâm đối tượng (cộng dồn nếu dóng theo chuỗi).
   - Tuyệt đối không nhầm lẫn trục Y ảnh (gốc trên-trái) với trục Y gia công cơ khí (gốc dưới-trái).

4. PHÂN BIỆT RÕ VÀ TRÍCH XUẤT ĐẦY ĐỦ HAI ĐẶC TRƯNG HÌNH HỌC (HOLES VÀ SLOTS):
   Bản vẽ cơ khí có thể có: (a) Lỗ tròn, HOẶC (b) Rãnh phay, HOẶC (c) Cả hai.
   Bạn BẮT BUỘC phải rà soát toàn bộ bề mặt phôi để nhận diện đầy đủ TẤT CẢ các đối tượng hình học bên trong:

   A. NHẬN DIỆN LỖ KHOAN (HOLES):
      - Chỉ ghi nhận vào "holes" khi có ký hiệu đường kính Ø hoặc "DIA".
      - Tọa độ tâm (center: {x, y}) tính từ gốc O(0,0) ở góc dưới-trái (dóng từ mép trái X và mép đáy Y).
      - Chiều sâu gia công (depth): Mặc định CỐ ĐỊNH là 5.0 mm cho mọi lỗ (depth = 5.0).
      - NẾU BẢN VẼ KHÔNG CÓ KÝ HIỆU Ø, mảng "holes" BẮT BUỘC để rỗng: [].

   B. NHẬN DIỆN RÃNH PHAY (SLOTS - OVAL / OBLONG / KEYWAY SLOTS):
      - Rãnh phay là các rãnh thẳng, rãnh xiên hoặc rãnh cong có 2 cạnh song song và 2 đầu bo tròn, ở giữa có đường nét gạch-chấm-gạch (centerline) biểu diễn quỹ đạo chạy dao.
      - Tọa độ đường tâm (centerline_path: [Point2D, Point2D]):
        * Gồm danh sách các điểm tâm cung tròn ở 2 đầu rãnh (hoặc các điểm đổi hướng) từ gốc O(0,0).
        * Lần theo từng đường dóng kích thước kéo thẳng xuống mép đáy để đọc tọa độ X của từng đầu rãnh.
        * Lần theo từng đường dóng kích thước kéo ngang sang mép trái (hoặc mép phải) để đọc tọa độ Y của từng đầu rãnh.
      - Bề rộng rãnh (width):
        * Nếu bản vẽ ghi kích thước giữa 2 cạnh song song (ví dụ số 12), bề rộng width = 12.0 mm.
        * Nếu bản vẽ ghi bán kính bo ở đầu rãnh là R (ví dụ R10, R4), bề rộng rãnh bằng hai lần bán kính: width = 2 * R (R10 -> width = 20.0 mm; R4 -> width = 8.0 mm).
      - Chiều sâu gia công rãnh (depth):
        * Đọc từ ghi chú t=... hoặc DP=... dọc theo rãnh (ví dụ t=3, t=4, t=2 -> depth tương ứng; nếu không ghi chú thì mặc định 5.0 mm).
      - Nếu bản vẽ KHÔNG có rãnh phay, trả về "slots": [].

5. NHẬN DIỆN CÁC CẠNH BIÊN DẠNG BAO NGOÀI CHI TIẾT (OUTER CONTOUR / EDGES):
   - Mọi chi tiết cơ khí đều có chu vi các cạnh bao ngoài để gia công phay biên dạng (outer_contour).
   - Với chi tiết hình vuông hoặc chữ nhật kích thước W x H, chuỗi tọa độ 4 cạnh khép kín từ gốc O(0,0) là:
     [{"x": 0.0, "y": 0.0}, {"x": W, "y": 0.0}, {"x": W, "y": H}, {"x": 0.0, "y": H}, {"x": 0.0, "y": 0.0}].
   - Nếu chi tiết có các cạnh vát (chamfer), bậc hoặc đa giác, ghi nhận tuần tự các đỉnh cạnh bao ngoài vào mảng outer_contour.

6. TẬP TRUNG TOÀN DIỆN VÀO HÌNH HỌC BIÊN DẠNG 2D (CHAIN-OF-THOUGHT QUA TRƯỜNG "reasoning"):
   - Trong schema JSON, trường "reasoning" là trường đầu tiên. Bạn PHẢI trình bày súc tích từng bước tính toán trong trường này:
     * Bước 1: Liệt kê kích thước phôi W, H, T.
     * Bước 2: Kiểm tra lỗ tròn: có ký hiệu Ø nào không? Nếu không có thì ghi rõ holes=[].
     * Bước 3: Rà soát tất cả các rãnh phay (slots): xác định đường tâm 2 đầu rãnh (tọa độ X, Y dóng từ mép chuẩn), bề rộng (số đo khoảng cách hoặc 2*R), chiều sâu t.
     * Bước 4: Xác định 4 cạnh bao ngoài chi tiết outer_contour.
     * Bước 5: Điền các số liệu chính xác vào JSON.

VÍ DỤ CẤU TRÚC JSON ĐẦU RA MẪU:
{
  "reasoning": "1. Phôi 100x100x5 mm. Gốc O(0,0) tại góc dưới-trái. 2. 4 cạnh bao ngoài: (0,0)->(100,0)->(100,100)->(0,100)->(0,0). 3. Bản vẽ có 3 rãnh phay: Rãnh 1 nằm ngang từ (10,80) đến (50,80), rộng 12mm, t=3; Rãnh 2 xiên từ (20,16) đến (80,64), bo đầu R10 -> rộng 20mm, t=4; Rãnh 3 xiên từ (65,28) đến (90,10), bo đầu R4 -> rộng 8mm, t=2. Không có lỗ tròn Ø nên holes=[].",
  "stock_width": 100.0,
  "stock_height": 100.0,
  "stock_thickness": 5.0,
  "holes": [],
  "slots": [
    {
      "width": 12.0,
      "centerline_path": [{"x": 10.0, "y": 80.0}, {"x": 50.0, "y": 80.0}],
      "depth": 3.0
    },
    {
      "width": 20.0,
      "centerline_path": [{"x": 20.0, "y": 16.0}, {"x": 80.0, "y": 64.0}],
      "depth": 4.0
    },
    {
      "width": 8.0,
      "centerline_path": [{"x": 65.0, "y": 28.0}, {"x": 90.0, "y": 10.0}],
      "depth": 2.0
    }
  ],
  "outer_contour": [
    {"x": 0.0, "y": 0.0},
    {"x": 100.0, "y": 0.0},
    {"x": 100.0, "y": 100.0},
    {"x": 0.0, "y": 100.0},
    {"x": 0.0, "y": 0.0}
  ]
}
"""

PARSER_USER_PROMPT = (
    "Hãy phân tích bản vẽ cơ khí 2D này. Trước tiên, hãy suy luận chi tiết "
    "về mốc chuẩn và chuỗi kích thước dóng trong trường 'reasoning', "
    "sau đó xuất chính xác các tọa độ theo schema DrawingIR.\n"
    "LƯU Ý QUAN TRỌNG:\n"
    "1. Rà soát kỹ toàn bộ các lỗ tròn (holes - ký hiệu Ø) và các rãnh phay (slots - rãnh oval bo tròn 2 đầu có đường tâm gạch-chấm-gạch hoặc ký hiệu R ở đầu rãnh).\n"
    "2. Nếu bản vẽ không có lỗ tròn (không có ký hiệu Ø), bắt buộc để 'holes': [].\n"
    "3. Nếu bản vẽ có rãnh phay, phải trích xuất đầy đủ tất cả các rãnh vào mảng 'slots', "
    "lần theo từng đường dóng kích thước từ mép trái và mép đáy để xác định chính xác tọa độ tâm 2 đầu rãnh và bề rộng (chú ý: nếu ghi R ở đầu rãnh thì width = 2 * R)."
)

HOLES_PARSER_SYSTEM_PROMPT = """Bạn là một chuyên gia cao cấp về đo lường hình học và lập trình gia công cơ khí chính xác (CAD/CAM).
Nhiệm vụ của bạn là đọc bản vẽ kỹ thuật gia công LỖ KHOAN 2D và trích xuất cấu trúc dữ liệu theo schema DrawingIR.

CÁC NGUYÊN TẮC BẮT BUỘC:
1. GỐC TỌA ĐỘ O(0,0):
   - Mặc định nằm ở góc DƯỚI - TRÁI (Bottom-Left) của phôi chữ nhật bao ngoài.
   - Trục X nằm ngang (X >= 0 tăng dần sang phải).
   - Trục Y thẳng đứng (Y >= 0 tăng dần lên trên).
   - Đơn vị tính: milimét (mm).

2. TỌA ĐỘ TÂM LỖ KHOAN (HOLES):
   - Lỗ tròn có ký hiệu tâm (+) hoặc đường tròn nét liền. Ký hiệu đường kính Ø (ví dụ Ø10) áp dụng cho các lỗ tròn cùng nhóm kích thước.
   - Tọa độ X: Lần theo đường dóng thẳng đứng kéo xuống mép đáy (hoặc mép trên) để đọc số đo X dóng từ mép trái. Nếu kích thước dóng nối tiếp (chuỗi kích thước), tọa độ X = X_trước + khoảng_cách (ví dụ 25 + 50 = 75).
   - Tọa độ Y: Lần theo đường dóng nằm ngang kéo sang mép trái (hoặc mép phải) để đọc số đo Y dóng từ mép đáy.
   - Chiều sâu gia công: Mặc định cố định 5.0 mm cho mọi lỗ khoan (depth = 5.0).
   - Đếm đủ tất cả các lỗ tròn có trên bản vẽ.

3. RÃNH PHAY (SLOTS):
   - Bản vẽ này là bản vẽ khoan lỗ, KHÔNG CÓ rãnh phay bo tròn, mảng "slots" BẮT BUỘC để rỗng: [].

4. BIÊN DẠNG PHÔI (STOCK & OUTER CONTOUR):
   - Đọc kích thước bao ngoài stock_width x stock_height (ví dụ 100x100).
   - Chuỗi đỉnh khép kín của 4 cạnh outer_contour: [(0,0), (W,0), (W,H), (0,H), (0,0)].

5. SUY LUẬN TRONG TRƯỜNG "reasoning":
   - Trình bày súc tích: kích thước phôi, từng lỗ tròn và phép dóng kích thước X, Y, đường kính Ø, khẳng định slots=[].

VÍ DỤ ĐẦU RA MẪU CHO BẢN VẼ LỖ KHOAN:
{
  "reasoning": "Phôi 100x100x5mm, gốc O(0,0) góc dưới-trái. Bản vẽ có 3 lỗ tròn Ø10: Lỗ 1 tại X=25, Y=75; Lỗ 2 tại X=75 (25+50), Y=50; Lỗ 3 tại X=25, Y=25. Bản vẽ không có rãnh phay nên slots=[]. 4 cạnh bao ngoài khép kín.",
  "stock_width": 100.0,
  "stock_height": 100.0,
  "stock_thickness": 5.0,
  "holes": [
    {"center": {"x": 25.0, "y": 75.0}, "diameter": 10.0, "depth": 5.0},
    {"center": {"x": 75.0, "y": 50.0}, "diameter": 10.0, "depth": 5.0},
    {"center": {"x": 25.0, "y": 25.0}, "diameter": 10.0, "depth": 5.0}
  ],
  "slots": [],
  "outer_contour": [
    {"x": 0.0, "y": 0.0},
    {"x": 100.0, "y": 0.0},
    {"x": 100.0, "y": 100.0},
    {"x": 0.0, "y": 100.0},
    {"x": 0.0, "y": 0.0}
  ]
}
"""

SLOTS_PARSER_SYSTEM_PROMPT = """Bạn là một chuyên gia cao cấp về đo lường hình học và lập trình gia công cơ khí chính xác (CAD/CAM).
Nhiệm vụ của bạn là đọc bản vẽ kỹ thuật gia công RÃNH PHAY (SLOTS) 2D và trích xuất cấu trúc dữ liệu theo schema DrawingIR.

CÁC NGUYÊN TẮC BẮT BUỘC:
1. GỐC TỌA ĐỘ O(0,0):
   - Mặc định nằm ở góc DƯỚI - TRÁI (Bottom-Left) của phôi chữ nhật bao ngoài.
   - Trục X nằm ngang (X >= 0 tăng dần sang phải).
   - Trục Y thẳng đứng (Y >= 0 tăng dần lên trên).
   - Đơn vị tính: milimét (mm).

2. LỖ KHOAN (HOLES):
   - Bản vẽ này là bản vẽ phay rãnh, KHÔNG CÓ lỗ khoan Ø, mảng "holes" BẮT BUỘC để rỗng: [].

3. NHẬN DIỆN VÀ TRÍCH XUẤT RÃNH PHAY (SLOTS):
   - Rãnh phay bo tròn 2 đầu có đường tâm gạch-chấm-gạch (centerline) biểu diễn quỹ đạo chạy dao.
   - Tọa độ tâm 2 đầu rãnh centerline_path: Lần theo đường dóng kích thước xuống mép đáy để đọc X, dóng sang mép trái/phải để đọc Y.
   - Bề rộng rãnh width: Đọc số đo khoảng cách giữa 2 cạnh (ví dụ 12) hoặc 2 lần bán kính bo R (R10 -> width = 20.0 mm; R4 -> width = 8.0 mm).
   - Chiều sâu gia công rãnh: Đọc từ ký hiệu t=... hoặc DP=... (mặc định 5.0 mm).
   - Trích xuất đầy đủ tất cả các rãnh phay có trên bản vẽ.

4. BIÊN DẠNG PHÔI (STOCK & OUTER CONTOUR):
   - Đọc kích thước bao ngoài stock_width x stock_height (ví dụ 100x100).
   - Chuỗi đỉnh khép kín của 4 cạnh outer_contour: [(0,0), (W,0), (W,H), (0,H), (0,0)].

VÍ DỤ ĐẦU RA MẪU CHO BẢN VẼ RÃNH PHAY:
{
  "reasoning": "Phôi 100x100x5mm, gốc O(0,0) góc dưới-trái. Bản vẽ không có lỗ tròn Ø nên holes=[]. Có 3 rãnh phay: Rãnh 1 từ (10,80) đến (50,80) W=12 t=3; Rãnh 2 từ (20,16) đến (80,64) bo R10 -> W=20 t=4; Rãnh 3 từ (65,28) đến (90,10) bo R4 -> W=8 t=2. 4 cạnh bao ngoài khép kín.",
  "stock_width": 100.0,
  "stock_height": 100.0,
  "stock_thickness": 5.0,
  "holes": [],
  "slots": [
    {
      "width": 12.0,
      "centerline_path": [{"x": 10.0, "y": 80.0}, {"x": 50.0, "y": 80.0}],
      "depth": 3.0
    },
    {
      "width": 20.0,
      "centerline_path": [{"x": 20.0, "y": 16.0}, {"x": 80.0, "y": 64.0}],
      "depth": 4.0
    },
    {
      "width": 8.0,
      "centerline_path": [{"x": 65.0, "y": 28.0}, {"x": 90.0, "y": 10.0}],
      "depth": 2.0
    }
  ],
  "outer_contour": [
    {"x": 0.0, "y": 0.0},
    {"x": 100.0, "y": 0.0},
    {"x": 100.0, "y": 100.0},
    {"x": 0.0, "y": 100.0},
    {"x": 0.0, "y": 0.0}
  ]
}
"""


def preprocess_drawing_image(image_path: Union[str, Path]) -> bytes:
    """
    Preprocess mechanical drawing image for optimal VLM recognition:
    1. Converts transparent background (RGBA / palette) to solid white background (#FFFFFF).
    2. Ensures high-resolution sharpness for thin CAD lines and small dimension texts.
    3. Exports as uncompressed/lossless PNG bytes to avoid JPEG compression artifacts.
    """
    path = Path(image_path)
    if not path.is_file():
        raise FileNotFoundError(f"Image not found at path: {path}")

    import io
    from PIL import Image

    with Image.open(path) as img:
        # Convert RGBA, LA, or palette with transparency to pure RGB on white background
        if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
            img_rgba = img.convert("RGBA")
            white_bg = Image.new("RGBA", img_rgba.size, (255, 255, 255, 255))
            composite = Image.alpha_composite(white_bg, img_rgba)
            rgb_img = composite.convert("RGB")
        else:
            rgb_img = img.convert("RGB")

        # Ensure optimal resolution: if image is too small (e.g. min dimension < 768),
        # upscale with Lanczos filter to preserve legible dimension texts and line arrows
        w, h = rgb_img.size
        min_dim = min(w, h)
        if min_dim < 768:
            scale = 768.0 / min_dim
            new_w = int(w * scale)
            new_h = int(h * scale)
            rgb_img = rgb_img.resize((new_w, new_h), Image.Resampling.LANCZOS)

        buffer = io.BytesIO()
        rgb_img.save(buffer, format="PNG", optimize=True)
        return buffer.getvalue()


def encode_image_base64(image_path: Union[str, Path]) -> str:
    """Encode preprocessed drawing image to base64 string."""
    image_bytes = preprocess_drawing_image(image_path)
    return base64.b64encode(image_bytes).decode("utf-8")


def post_process_drawing_ir(
    ir: DrawingIR,
    has_holes: bool = True,
    has_slots: bool = True,
) -> DrawingIR:
    """
    Chuẩn hóa và hoàn thiện kết quả DrawingIR sau phân tích VLM:
    1. Lọc cứng (hard filtering): Nếu bản vẽ không có lỗ/rãnh theo kết quả phân loại,
       cưỡng chế làm rỗng mảng tương ứng để triệt tiêu 100% ảo giác (hallucination).
    2. Đảm bảo outer_contour luôn đầy đủ và khép kín (fallback theo stock_width x stock_height nếu thiếu).
    3. Cố định chiều sâu gia công (depth = 5.0 mm) cho mọi lỗ và rãnh theo yêu cầu người dùng,
       giúp người dùng và hệ thống tập trung hoàn toàn vào độ chính xác của biên dạng 2D.
    4. Đảm bảo stock_thickness >= 5.0 mm (mặc định 5.0 mm nếu không có thông số hợp lệ).
    """
    if not has_holes:
        if ir.holes:
            logger.info(f"Hard filtering: removed {len(ir.holes)} hallucinated holes (drawing classified with no holes)")
        ir.holes = []
    if not has_slots:
        if ir.slots:
            logger.info(f"Hard filtering: removed {len(ir.slots)} hallucinated slots (drawing classified with no slots)")
        ir.slots = []

    if not ir.outer_contour or len(ir.outer_contour) < 3:
        ir.outer_contour = ir.get_effective_outer_contour()
    else:
        pts = list(ir.outer_contour)
        if abs(pts[0].x - pts[-1].x) > 1e-4 or abs(pts[0].y - pts[-1].y) > 1e-4:
            pts.append(Point2D(x=pts[0].x, y=pts[0].y))
        ir.outer_contour = pts

    if ir.stock_thickness <= 0.0:
        ir.stock_thickness = 5.0

    # Cố định chiều sâu phay / khoan 5.0 mm cho mọi lỗ và rãnh
    for hole in ir.holes:
        hole.depth = 5.0

    for slot in ir.slots:
        slot.depth = 5.0

    return ir


class BaseVLMAdapter(ABC):
    """Abstract Base Class for VLM Drawing Parser Adapters."""

    @abstractmethod
    def parse(self, image_path: Union[str, Path]) -> DrawingIR:
        """Parse 2D mechanical drawing image and return DrawingIR."""
        pass


class OpenAIVLMAdapter(BaseVLMAdapter):
    """OpenAI VLM Adapter using instructor with OpenAI API."""

    DEFAULT_MODEL = "gpt-5.5-pro"

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
    ):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.model = model or self.DEFAULT_MODEL
        self.base_url = base_url

    def parse(self, image_path: Union[str, Path]) -> DrawingIR:
        """Call OpenAI VLM via instructor with structured output enforcement."""
        if not self.api_key:
            raise ValueError(
                "API key is missing for OpenAI VLM. Please provide api_key or set OPENAI_API_KEY environment variable."
            )

        if not HAS_OPENAI:
            raise ImportError(
                "OpenAI VLM dependencies ('openai', 'instructor') are not installed. "
                "Please run 'pip install openai instructor'."
            )

        client_kwargs: Dict[str, Any] = {"api_key": self.api_key}
        if self.base_url:
            client_kwargs["base_url"] = self.base_url

        client = instructor.from_openai(OpenAI(**client_kwargs))
        base64_img = encode_image_base64(image_path)

        logger.info(f"Calling OpenAI VLM ({self.model}) for drawing: {image_path}")
        result: DrawingIR = client.chat.completions.create(
            model=self.model,
            response_model=DrawingIR,
            messages=[
                {"role": "system", "content": MECHANICAL_ENGINEERING_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": PARSER_USER_PROMPT,
                        },
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{base64_img}"},
                        },
                    ],
                },
            ],
            temperature=0.0,
        )
        return post_process_drawing_ir(result)


class GeminiVLMAdapter(BaseVLMAdapter):
    """Google Gemini VLM Adapter using official google-genai SDK with structured outputs."""

    DEFAULT_MODEL = "gemini-3.8-flash"

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
    ):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        self.model = model or self.DEFAULT_MODEL

    def parse(self, image_path: Union[str, Path]) -> DrawingIR:
        """Call Gemini VLM via google-genai with response_schema=DrawingIR."""
        import io
        from PIL import Image

        if not self.api_key:
            raise ValueError(
                "API key is missing for Google Gemini VLM. Please provide api_key or set GEMINI_API_KEY environment variable."
            )

        if not HAS_GEMINI:
            raise ImportError(
                "Google GenAI SDK ('google-genai') is not installed. "
                "Please run 'pip install google-genai'."
            )

        client = genai.Client(api_key=self.api_key)
        img_path = Path(image_path)
        if not img_path.is_file():
            raise FileNotFoundError(f"Image not found at path: {img_path}")

        # Preprocess drawing image (handles transparent background and ensures high contrast)
        pil_img = Image.open(io.BytesIO(preprocess_drawing_image(img_path)))

        prompt = PARSER_USER_PROMPT

        config = types.GenerateContentConfig(
            system_instruction=MECHANICAL_ENGINEERING_SYSTEM_PROMPT,
            response_mime_type="application/json",
            response_schema=DrawingIR,
            temperature=0.0,
        )

        response = client.models.generate_content(
            model=self.model,
            contents=[pil_img, prompt],
            config=config,
        )

        content = response.text
        if not content:
            raise ValueError(f"Empty response received from Gemini model '{self.model}'.")

        ir = DrawingIR.model_validate_json(content)
        return post_process_drawing_ir(ir)


# Backward-compatible adapter alias for CloudVLMAdapter
CloudVLMAdapter = OpenAIVLMAdapter


class OllamaVLMAdapter(BaseVLMAdapter):
    """
    Local VLM Adapter using Ollama API calling Qwen2.5-VL (qwen2.5vl:7b).
    Endpoint: http://localhost:11434/api/chat
    """

    DEFAULT_MODEL = "qwen2.5vl:7b"

    def __init__(
        self,
        model: Optional[str] = None,
        base_url: str = "http://localhost:11434",
        timeout: float = 120.0,
    ):
        self.model = model or os.getenv("OLLAMA_MODEL") or self.DEFAULT_MODEL
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    @staticmethod
    def _clean_json_text(text: str) -> str:
        """Extract and clean raw JSON from LLM response (strips markdown code blocks)."""
        # Match ```json ... ``` or ``` ... ```
        code_block = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if code_block:
            return code_block.group(1).strip()

        # Match outermost curly braces
        json_match = re.search(r"(\{.*\})", text, re.DOTALL)
        if json_match:
            return json_match.group(1).strip()

        return text.strip()

    def _classify_drawing_features(self, client: httpx.Client, base64_img: str) -> Tuple[bool, bool]:
        """
        Phân loại nhanh đặc trưng của bản vẽ (Lỗ khoan vs Rãnh phay) để chọn prompt chuyên biệt
        và loại bỏ triệt để hiện tượng ảo giác (hallucination) do few-shot bias trên mô hình 7B/8B.
        """
        url = f"{self.base_url}/api/chat"
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": (
                        "Quan sát bản vẽ và trả lời đúng 2 dòng sau:\n"
                        "HOLES: [CÓ hoặc KHÔNG nếu có ký hiệu Ø đường kính lỗ tròn]\n"
                        "SLOTS: [CÓ hoặc KHÔNG nếu có ký hiệu R bán kính bo hoặc t= chiều sâu rãnh]"
                    ),
                    "images": [base64_img],
                }
            ],
            "stream": False,
            "options": {
                "temperature": 0.0,
                "num_predict": 64,
            },
        }
        try:
            response = client.post(url, json=payload)
            response.raise_for_status()
            data = response.json()
            content = data.get("message", {}).get("content", "").upper()
            has_holes = "HOLES: CÓ" in content or "HOLES: CO" in content
            has_slots = "SLOTS: CÓ" in content or "SLOTS: CO" in content
            # Nếu cả hai đều không được phát hiện rõ (hoặc trong trường hợp mock test trả về JSON chung)
            if not has_holes and not has_slots:
                return True, True
            return has_holes, has_slots
        except Exception as exc:
            logger.warning(f"Feature pre-classification failed, falling back to all features: {exc}")
            return True, True

    def parse(self, image_path: Union[str, Path]) -> DrawingIR:
        """Send image and prompt to local Ollama server and parse JSON into DrawingIR."""
        base64_img = encode_image_base64(image_path)

        url = f"{self.base_url}/api/chat"

        try:
            with httpx.Client(timeout=self.timeout) as client:
                # Bước 1: Phân loại đặc trưng trước
                has_holes, has_slots = self._classify_drawing_features(client, base64_img)

                # Bước 2: Định tuyến prompt chuyên biệt
                if has_holes and not has_slots:
                    system_prompt = HOLES_PARSER_SYSTEM_PROMPT
                elif has_slots and not has_holes:
                    system_prompt = SLOTS_PARSER_SYSTEM_PROMPT
                else:
                    system_prompt = MECHANICAL_ENGINEERING_SYSTEM_PROMPT

                payload = {
                    "model": self.model,
                    "messages": [
                        {
                            "role": "system",
                            "content": system_prompt,
                        },
                        {
                            "role": "user",
                            "content": PARSER_USER_PROMPT,
                            "images": [base64_img],
                        },
                    ],
                    "format": DrawingIR.model_json_schema(),
                    "stream": False,
                    "options": {
                        "temperature": 0.0,
                        "num_ctx": 8192,
                        "num_predict": 4096,
                    },
                }

                response = client.post(url, json=payload)
                response.raise_for_status()
                data = response.json()
        except httpx.ConnectError as conn_err:
            raise ConnectionError(
                f"Cannot connect to local Ollama server at {self.base_url}. "
                f"Make sure Ollama is running ('ollama serve') and model '{self.model}' is available."
            ) from conn_err
        except httpx.HTTPStatusError as http_err:
            raise RuntimeError(
                f"Ollama API returned HTTP error {http_err.response.status_code}: {http_err.response.text}"
            ) from http_err

        # Extract model response text
        content = data.get("message", {}).get("content", "")
        if not content:
            raise ValueError(f"Empty response received from Ollama model '{self.model}'.")

        cleaned_json = self._clean_json_text(content)

        try:
            ir = DrawingIR.model_validate_json(cleaned_json)
        except ValidationError as val_err:
            logger.error(f"Failed to validate DrawingIR from Ollama response: {cleaned_json}")
            raise ValueError(f"Ollama response failed DrawingIR schema validation:\n{val_err}") from val_err

        return post_process_drawing_ir(ir, has_holes=has_holes, has_slots=has_slots)


def get_vlm_adapter(
    provider: str = "cloud",
    api_key: Optional[str] = None,
    model: Optional[str] = None,
    base_url: Optional[str] = None,
    **kwargs,
) -> BaseVLMAdapter:
    """
    Factory function to instantiate the appropriate VLM adapter.

    Args:
        provider: 'cloud' (OpenAI/Gemini via instructor) or 'local' (Ollama).
        api_key: API key for cloud providers.
        model: Specific model name (e.g., 'gpt-4o' or 'qwen2.5-vl:7b-instruct-q4_k_m').
        base_url: Base URL endpoint for local or custom providers.
    """
    prov = provider.lower().strip()
    if prov in ("local", "ollama"):
        return OllamaVLMAdapter(
            model=model or OllamaVLMAdapter.DEFAULT_MODEL,
            base_url=base_url or "http://localhost:11434",
            **kwargs,
        )
    elif prov in ("gemini", "google"):
        return GeminiVLMAdapter(
            api_key=api_key,
            model=model or GeminiVLMAdapter.DEFAULT_MODEL,
        )
    elif prov in ("cloud", "openai"):
        return OpenAIVLMAdapter(
            api_key=api_key,
            model=model or OpenAIVLMAdapter.DEFAULT_MODEL,
            base_url=base_url,
        )
    else:
        raise ValueError(
            f"Unsupported provider: '{provider}'. Choose 'local', 'openai', or 'gemini'."
        )


def parse_drawing(
    image_path: Union[str, Path],
    provider: str = "cloud",
    api_key: Optional[str] = None,
    model: Optional[str] = None,
    **kwargs,
) -> DrawingIR:
    """
    High-level entrypoint to analyze a 2D mechanical drawing image and produce a DrawingIR object.

    Args:
        image_path: Path to the image file (.png, .jpg, etc.).
        provider: 'cloud' (default) or 'local'.
        api_key: API key for cloud provider (optional if set in environment).
        model: Specific model identifier. Defaults to:
               - 'gpt-4o' for cloud
               - 'qwen2.5-vl:7b-instruct-q4_k_m' for local
        **kwargs: Additional parameters forwarded to the adapter.

    Returns:
        DrawingIR: Validated intermediate representation with stock dimensions, holes, and slots.
    """
    adapter = get_vlm_adapter(provider=provider, api_key=api_key, model=model, **kwargs)
    return adapter.parse(image_path)


# Backward-compatible wrapper class
class VLMParser:
    """Wrapper class retained for backward compatibility with earlier code."""

    def __init__(self, provider: str = "cloud", model_name: Optional[str] = None):
        self.provider = provider
        self.model_name = model_name

    def parse(self, image_path: Union[str, Path], api_key: Optional[str] = None) -> DrawingIR:
        return parse_drawing(image_path, provider=self.provider, api_key=api_key, model=self.model_name)
