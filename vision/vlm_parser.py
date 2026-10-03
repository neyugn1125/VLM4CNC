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
from typing import Any, Dict, Optional, Union

import httpx
from pydantic import ValidationError

from vision.schemas import DrawingIR, DrillHole, Point2D, SlotContour

logger = logging.getLogger("vlm4cnc.vlm_parser")


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
   - stock_thickness: Chiều dày tấm phôi theo phương trục Z (mm).

3. PHƯƠNG PHÁP SUY LUẬN TỌA ĐỘ CỘNG DỒN (DIMENSION CHAINING):
   - Các kích thước trên bản vẽ cơ khí thường được dóng từ cạnh chuẩn (Datum edges).
   - Tọa độ X tuyệt đối = Khoảng cách dóng từ mép chuẩn BÊN TRÁI tới tâm đối tượng (cộng dồn nếu dóng theo chuỗi).
   - Tọa độ Y tuyệt đối = Khoảng cách dóng từ mép chuẩn BÊN DƯỚI tới tâm đối tượng (cộng dồn nếu dóng theo chuỗi).
   - Tuyệt đối không nhầm lẫn trục Y ảnh (gốc trên-trái) với trục Y gia công cơ khí (gốc dưới-trái).

4. NHẬN DIỆN LỖ KHOAN (HOLES):
   - Nhận diện ký hiệu Ø hoặc "DIA" là đường kính danh nghĩa của lỗ tròn.
   - Tọa độ tâm (center: {x, y}) tính từ gốc O(0,0) ở góc dưới-trái.
   - Chiều sâu lỗ (depth): Lấy theo ghi chú (ví dụ: "Ø10 THRU" -> depth = stock_thickness, hoặc "Ø10 x 15 DP" -> depth = 15).

5. NHẬN DIỆN RÃNH PHAY (SLOTS):
   - Nhận diện đường nét gạch-chấm-gạch (centerline) là đường tâm chạy dao của rãnh phay (centerline_path).
   - Xác định tuần tự tọa độ các điểm uốn, đổi hướng, điểm đầu và điểm cuối của đường tâm từ gốc O(0,0).
   - Bề rộng rãnh (width): Khoảng cách giữa 2 thành rãnh song song.
   - Chiều sâu rãnh (depth): Chiều sâu cắt phay.
   - Nếu bản vẽ không có rãnh phay (slots), trả về mảng rỗng "slots": [].

6. NHẬN DIỆN CÁC CẠNH BIÊN DẠNG BAO NGOÀI CHI TIẾT (OUTER CONTOUR / EDGES):
   - Mọi chi tiết cơ khí đều có chu vi các cạnh bao ngoài để gia công phay biên dạng (outer_contour).
   - Với chi tiết hình vuông hoặc chữ nhật kích thước W x H, chuỗi tọa độ 4 cạnh khép kín từ gốc O(0,0) là:
     [{"x": 0.0, "y": 0.0}, {"x": W, "y": 0.0}, {"x": W, "y": H}, {"x": 0.0, "y": H}, {"x": 0.0, "y": 0.0}].
   - Nếu chi tiết có các cạnh vát (chamfer), bậc hoặc đa giác, ghi nhận tuần tự các đỉnh cạnh bao ngoài vào mảng outer_contour.

7. BẮT BUỘC SUY LUẬN NỘI BỘ (CHAIN-OF-THOUGHT QUA TRƯỜNG "reasoning"):
   - Trong schema JSON, trường "reasoning" là trường đầu tiên. Bạn PHẢI trình bày súc tích từng bước tính toán trong trường này:
     * Bước 1: Liệt kê kích thước phôi W, H, T.
     * Bước 2: Xác định cạnh chuẩn (Datum A bên trái, Datum B bên dưới).
     * Bước 3: Xác định tọa độ 4 cạnh bao ngoài chi tiết.
     * Bước 4: Lần theo từng đường dóng kích thước cho từng lỗ và rãnh (ghi rõ: Lỗ 1 cách mép trái bao nhiêu mm -> X = ..., cách mép dưới bao nhiêu mm -> Y = ...).
     * Bước 5: Điền các số liệu vào các trường còn lại.

VÍ DỤ CẤU TRÚC JSON ĐẦU RA MẪU:
{
  "reasoning": "1. Phôi kích thước 100x100x10 mm (W=100, H=100, T=10). Gốc O(0,0) tại góc dưới-trái. Cạnh trái là chuẩn X, cạnh đáy là chuẩn Y. 2. 4 cạnh bao ngoài chi tiết khép kín: (0,0) -> (100,0) -> (100,100) -> (0,100) -> (0,0). 3. Lỗ 1: dóng từ mép trái 25mm -> X=25.0; dóng từ mép đáy 25mm -> Y=25.0; Ø10 THRU -> dia=10.0, depth=10.0. 4. Lỗ 2: dóng từ mép trái 75mm -> X=75.0, mép đáy 50mm -> Y=50.0...",
  "stock_width": 100.0,
  "stock_height": 100.0,
  "stock_thickness": 10.0,
  "holes": [
    {"center": {"x": 25.0, "y": 25.0}, "diameter": 10.0, "depth": 10.0},
    {"center": {"x": 75.0, "y": 50.0}, "diameter": 10.0, "depth": 10.0},
    {"center": {"x": 25.0, "y": 75.0}, "diameter": 10.0, "depth": 10.0}
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
        import instructor
        from openai import OpenAI

        if not self.api_key:
            raise ValueError(
                "API key is missing for OpenAI VLM. Please provide api_key or set OPENAI_API_KEY environment variable."
            )

        client_kwargs: Dict[str, Any] = {"api_key": self.api_key}
        if self.base_url:
            client_kwargs["base_url"] = self.base_url

        client = instructor.from_openai(OpenAI(**client_kwargs))
        base64_img = encode_image_base64(image_path)

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
                            "text": (
                                "Hãy suy luận nội bộ về mốc chuẩn và chuỗi kích thước trong trường 'reasoning' "
                                "và trích xuất cấu trúc DrawingIR từ bản vẽ cơ khí 2D này."
                            ),
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
        if not result.outer_contour:
            result.outer_contour = result.get_effective_outer_contour()
        return result


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
        from google import genai
        from google.genai import types
        from PIL import Image

        if not self.api_key:
            raise ValueError(
                "API key is missing for Google Gemini VLM. Please provide api_key or set GEMINI_API_KEY environment variable."
            )

        client = genai.Client(api_key=self.api_key)
        img_path = Path(image_path)
        if not img_path.is_file():
            raise FileNotFoundError(f"Image not found at path: {img_path}")

        # Preprocess drawing image (handles transparent background and ensures high contrast)
        pil_img = Image.open(io.BytesIO(preprocess_drawing_image(img_path)))

        prompt = (
            "Hãy suy luận nội bộ về mốc chuẩn và chuỗi kích thước trong trường 'reasoning' "
            "và trích xuất cấu trúc DrawingIR từ bản vẽ cơ khí 2D này."
        )

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
        if not ir.outer_contour:
            ir.outer_contour = ir.get_effective_outer_contour()
        return ir


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

    def parse(self, image_path: Union[str, Path]) -> DrawingIR:
        """Send image and prompt to local Ollama server and parse JSON into DrawingIR."""
        base64_img = encode_image_base64(image_path)

        url = f"{self.base_url}/api/chat"
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": MECHANICAL_ENGINEERING_SYSTEM_PROMPT,
                },
                {
                    "role": "user",
                    "content": (
                        "Hãy phân tích bản vẽ cơ khí 2D này. Trước tiên, hãy suy luận chi tiết "
                        "về mốc chuẩn và chuỗi kích thước dóng trong trường 'reasoning', "
                        "sau đó xuất chính xác các tọa độ theo schema DrawingIR."
                    ),
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

        try:
            with httpx.Client(timeout=self.timeout) as client:
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

        if not ir.outer_contour:
            ir.outer_contour = ir.get_effective_outer_contour()
        return ir


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
