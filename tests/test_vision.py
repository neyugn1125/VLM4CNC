"""
Tests for VLM drawing parser module (vision/vlm_parser.py).
Generates a realistic 2D mechanical drawing image, tests Adapter pattern for Cloud and Local (Ollama Qwen2.5-VL-7B-Instruct-Q4_K_M),
measures processing latency, and prints the resulting Pydantic DrawingIR object.
"""

from pathlib import Path
import json
import sys
import time
import pytest
from unittest.mock import patch, MagicMock

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from PIL import Image, ImageDraw, ImageFont

from vision.schemas import DrawingIR, DrillHole, Point2D, SlotContour
from vision.vlm_parser import (
    MECHANICAL_ENGINEERING_SYSTEM_PROMPT,
    BaseVLMAdapter,
    CloudVLMAdapter,
    OpenAIVLMAdapter,
    GeminiVLMAdapter,
    OllamaVLMAdapter,
    get_vlm_adapter,
    parse_drawing,
    encode_image_base64,
    preprocess_drawing_image,
)

OUTPUTS_DIR = Path(__file__).resolve().parent.parent / "outputs"


def generate_sample_drawing_image(filepath: Path) -> Path:
    """
    Generate a 2D mechanical engineering drawing image with:
      - 100 x 100 mm stock boundary
      - 3 drill holes (Ø10) at (25, 25), (25, 75), (75, 50)
      - A slot path with centerlines and dimension callouts
    """
    filepath.parent.mkdir(parents=True, exist_ok=True)
    width, height = 800, 800
    img = Image.new("RGB", (width, height), color="white")
    draw = ImageDraw.Draw(img)

    # Scale: 1 mm = 6 pixels, margin 100 px from bottom-left
    margin_x = 100
    margin_y = 700  # inverted Y for PIL (700 is bottom origin)
    scale = 6.0

    def to_img(x: float, y: float):
        return (int(margin_x + x * scale), int(margin_y - y * scale))

    # 1. Draw Stock Boundary (100 x 100 mm)
    p0 = to_img(0, 0)
    p1 = to_img(100, 100)
    draw.rectangle([p0[0], p1[1], p1[0], p0[1]], outline="black", width=3)

    # 2. Draw 3 Drill Holes (Ø10 -> radius 5mm = 30px)
    hole_coords = [(25.0, 25.0), (25.0, 75.0), (75.0, 50.0)]
    r_px = int(5.0 * scale)
    for hx, hy in hole_coords:
        cx, cy = to_img(hx, hy)
        draw.ellipse([cx - r_px, cy - r_px, cx + r_px, cy + r_px], outline="red", width=2)
        # Draw center cross mark
        draw.line([cx - 8, cy, cx + 8, cy], fill="red", width=1)
        draw.line([cx, cy - 8, cx, cy + 8], fill="red", width=1)

    # 3. Draw Centerline Slot Path: (10, 50) -> (10, 10) -> (60, 10) -> (80, 30)
    slot_path = [(10.0, 50.0), (10.0, 10.0), (60.0, 10.0), (80.0, 30.0)]
    slot_img_pts = [to_img(x, y) for x, y in slot_path]
    for i in range(len(slot_img_pts) - 1):
        # Draw dashed centerline
        draw.line([slot_img_pts[i], slot_img_pts[i + 1]], fill="green", width=2)

    # 4. Text Annotations & Dimension Labels
    draw.text((margin_x + 10, margin_y + 15), "Origin O(0,0)", fill="black")
    draw.text((margin_x + 220, margin_y + 15), "Stock Width: 100 mm", fill="black")
    draw.text((margin_x - 90, margin_y - 320), "Height: 100 mm", fill="black")
    draw.text((to_img(25, 75)[0] + 15, to_img(25, 75)[1] - 15), "3x Ø10 THRU", fill="red")
    draw.text((to_img(60, 10)[0] - 20, to_img(60, 10)[1] - 25), "SLOT W=8mm, DP=5mm", fill="green")
    draw.text((margin_x + 350, margin_y - 650), "MATERIAL: AL6061-T6 (T=10mm)", fill="blue")

    img.save(str(filepath))
    return filepath


@pytest.fixture(scope="session")
def sample_drawing_image(tmp_path_factory) -> Path:
    """Fixture providing a generated mechanical drawing image file."""
    temp_dir = tmp_path_factory.mktemp("drawings")
    img_path = temp_dir / "sample_test_drawing.png"
    return generate_sample_drawing_image(img_path)


def test_system_prompt_requirements():
    """Verify that system prompt enforces all mechanical engineering rules."""
    assert "DƯỚI - TRÁI" in MECHANICAL_ENGINEERING_SYSTEM_PROMPT
    assert "cộng dồn" in MECHANICAL_ENGINEERING_SYSTEM_PROMPT.lower()
    assert "Ø" in MECHANICAL_ENGINEERING_SYSTEM_PROMPT
    assert "gạch-chấm-gạch" in MECHANICAL_ENGINEERING_SYSTEM_PROMPT
    assert "chain-of-thought" in MECHANICAL_ENGINEERING_SYSTEM_PROMPT.lower()
    assert "DrawingIR" in MECHANICAL_ENGINEERING_SYSTEM_PROMPT


def test_vlm_adapter_factory():
    """Verify get_vlm_adapter instantiates correct adapter classes and models."""
    openai_adapter = get_vlm_adapter(provider="openai", api_key="sk-test-key", model="gpt-5.5-pro")
    assert isinstance(openai_adapter, OpenAIVLMAdapter)
    assert openai_adapter.model == "gpt-5.5-pro"

    gemini_adapter = get_vlm_adapter(provider="gemini", api_key="test-key", model="gemini-3.8-flash")
    assert isinstance(gemini_adapter, GeminiVLMAdapter)
    assert gemini_adapter.model == "gemini-3.8-flash"

    cloud_adapter = get_vlm_adapter(provider="cloud", api_key="sk-test-key", model="gpt-5.5-pro")
    assert isinstance(cloud_adapter, CloudVLMAdapter)
    assert cloud_adapter.model == "gpt-5.5-pro"

    local_adapter = get_vlm_adapter(provider="local")
    assert isinstance(local_adapter, OllamaVLMAdapter)
    assert local_adapter.model == "qwen2.5vl:7b"

    # Test custom quantization model string
    custom_local = get_vlm_adapter(provider="local", model="qwen2.5vl:3b")
    assert custom_local.model == "qwen2.5vl:3b"

    with pytest.raises(ValueError, match="Unsupported provider"):
        get_vlm_adapter(provider="unknown_provider")


def test_openai_and_gemini_missing_keys():
    """Verify ValueError is raised when API keys are missing."""
    with patch.dict("os.environ", {}, clear=True):
        adapter_oai = OpenAIVLMAdapter(api_key=None)
        with pytest.raises(ValueError, match="API key is missing for OpenAI"):
            adapter_oai.parse("dummy.png")

        adapter_gem = GeminiVLMAdapter(api_key=None)
        with pytest.raises(ValueError, match="API key is missing for Google Gemini"):
            adapter_gem.parse("dummy.png")


def test_gemini_adapter_mock_inference(sample_drawing_image):
    """Test GeminiVLMAdapter inference with mocked google-genai client."""
    adapter = GeminiVLMAdapter(api_key="mock-key", model="gemini-3.8-flash")
    sample_data = {
        "stock_width": 100.0,
        "stock_height": 100.0,
        "stock_thickness": 10.0,
        "holes": [{"center": {"x": 25.0, "y": 25.0}, "diameter": 10.0, "depth": 10.0}],
        "slots": [],
    }

    mock_resp = MagicMock()
    mock_resp.text = json.dumps(sample_data)

    with patch("google.genai.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = mock_resp
        mock_client_cls.return_value = mock_client

        res = adapter.parse(sample_drawing_image)

    assert isinstance(res, DrawingIR)
    assert res.stock_width == 100.0
    assert len(res.holes) == 1
    assert res.holes[0].diameter == 10.0


def test_drawing_ir_gemini_schema_compatibility():
    """Verify that DrawingIR schema translates cleanly to google.genai types.Schema without extra_forbidden errors."""
    from google.genai._transformers import t_schema
    from google.genai import types

    # This will raise pydantic_core.ValidationError if exclusiveMinimum or unsupported fields are present
    schema = t_schema(None, DrawingIR)
    assert schema is not None
    assert isinstance(schema, types.Schema)
    assert "reasoning" in schema.properties
    assert "stock_width" in schema.properties
    assert "holes" in schema.properties
    assert "slots" in schema.properties


def test_image_preprocessing_pipeline(tmp_path):
    """Verify preprocess_drawing_image converts transparent RGBA to white background RGB and scales."""
    # Create an RGBA image with transparent parts and black lines
    img = Image.new("RGBA", (200, 200), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rectangle([20, 20, 180, 180], outline=(0, 0, 0, 255), width=2)
    test_img_path = tmp_path / "test_transparent.png"
    img.save(test_img_path)

    # Process
    png_bytes = preprocess_drawing_image(test_img_path)
    assert png_bytes.startswith(b"\x89PNG\r\n\x1a\n")

    # Load resulting image
    import io
    result_img = Image.open(io.BytesIO(png_bytes))
    assert result_img.mode == "RGB"
    # Minimum dimension upscale check (scaled to at least 768px)
    assert min(result_img.size) >= 768
    # Background pixel (0, 0) should be white (255, 255, 255)
    assert result_img.getpixel((0, 0)) == (255, 255, 255)


def test_ollama_json_cleaning():
    """Verify that OllamaVLMAdapter cleans markdown codeblocks before parsing JSON."""
    raw_markdown = """
    Sau khi phân tích bản vẽ, tôi suy luận:
    - Gốc O(0,0) tại góc dưới trái.
    - 3 lỗ khoan Ø10 tại các vị trí cộng dồn.
    ```json
    {
      "stock_width": 100.0,
      "stock_height": 100.0,
      "stock_thickness": 10.0,
      "holes": [
        {"center": {"x": 25.0, "y": 25.0}, "diameter": 10.0, "depth": 10.0}
      ],
      "slots": []
    }
    ```
    Hy vọng kết quả giúp ích cho quá trình gia công.
    """
    cleaned = OllamaVLMAdapter._clean_json_text(raw_markdown)
    parsed = DrawingIR.model_validate_json(cleaned)
    assert parsed.stock_width == 100.0
    assert len(parsed.holes) == 1
    assert parsed.holes[0].diameter == 10.0


def test_ollama_adapter_mock_inference(sample_drawing_image):
    """
    Test OllamaVLMAdapter with qwen2.5vl:7b payload,
    simulating inference and measuring performance latency.
    """
    adapter = OllamaVLMAdapter(model="qwen2.5vl:7b")
    expected_ir = {
        "reasoning": "Reasoning steps for 100x100mm stock with 3 holes and 1 slot",
        "stock_width": 100.0,
        "stock_height": 100.0,
        "stock_thickness": 10.0,
        "holes": [
            {"center": {"x": 25.0, "y": 25.0}, "diameter": 10.0, "depth": 10.0},
            {"center": {"x": 25.0, "y": 75.0}, "diameter": 10.0, "depth": 10.0},
            {"center": {"x": 75.0, "y": 50.0}, "diameter": 10.0, "depth": 10.0},
        ],
        "slots": [
            {
                "width": 8.0,
                "depth": 5.0,
                "centerline_path": [
                    {"x": 10.0, "y": 50.0},
                    {"x": 10.0, "y": 10.0},
                    {"x": 60.0, "y": 10.0},
                    {"x": 80.0, "y": 30.0},
                ],
            }
        ],
    }

    mock_response_data = {
        "message": {
            "role": "assistant",
            "content": f"```json\n{json.dumps(expected_ir, indent=2)}\n```",
        }
    }

    # Measure execution time
    start_time = time.perf_counter()
    with patch("httpx.Client.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = mock_response_data
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        result = adapter.parse(sample_drawing_image)

    elapsed_ms = (time.perf_counter() - start_time) * 1000

    # Verify DrawingIR output
    assert isinstance(result, DrawingIR)
    assert result.reasoning == "Reasoning steps for 100x100mm stock with 3 holes and 1 slot"
    assert result.stock_width == 100.0
    assert result.stock_height == 100.0
    assert len(result.holes) == 3
    assert len(result.slots) == 1
    assert result.slots[0].width == 8.0
    assert len(result.slots[0].centerline_path) == 4

    print(f"\n[BENCHMARK] Local Ollama ({adapter.model}) parsed drawing in: {elapsed_ms:.2f} ms")
    print(f"[RESULT] Parsed DrawingIR:\n{result.model_dump_json(indent=2)}")


def run_standalone_benchmark():
    """Standalone runner for manual testing and latency measurement."""
    drawing_file = OUTPUTS_DIR / "sample_mechanical_drawing.png"
    print(f"\n1. Generating synthetic mechanical drawing at: {drawing_file} ...")
    generate_sample_drawing_image(drawing_file)
    print("   Image successfully created.")

    print("\n2. Testing parse_drawing with OllamaVLMAdapter (Qwen2.5-VL-7B-Instruct-Q4_K_M) ...")
    start = time.perf_counter()

    # If Ollama is running locally, attempt real call, otherwise fallback to mocked run
    try:
        result = parse_drawing(drawing_file, provider="local", model="qwen2.5-vl:7b-instruct-q4_k_m")
        elapsed = time.perf_counter() - start
        print(f"   [REAL INFERENCE] Latency: {elapsed:.3f} s")
    except Exception as e:
        print(f"   [NOTICE] Local Ollama service not reachable ({e}). Running simulated test:")
        with patch("httpx.Client.post") as mock_post:
            expected_data = {
                "stock_width": 100.0,
                "stock_height": 100.0,
                "stock_thickness": 10.0,
                "holes": [
                    {"center": {"x": 25.0, "y": 25.0}, "diameter": 10.0, "depth": 10.0},
                    {"center": {"x": 25.0, "y": 75.0}, "diameter": 10.0, "depth": 10.0},
                    {"center": {"x": 75.0, "y": 50.0}, "diameter": 10.0, "depth": 10.0},
                ],
                "slots": [
                    {
                        "width": 8.0,
                        "depth": 5.0,
                        "centerline_path": [
                            {"x": 10.0, "y": 50.0},
                            {"x": 10.0, "y": 10.0},
                            {"x": 60.0, "y": 10.0},
                            {"x": 80.0, "y": 30.0},
                        ],
                    }
                ],
            }
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"message": {"content": json.dumps(expected_data)}}
            mock_post.return_value = mock_resp

            start = time.perf_counter()
            result = parse_drawing(drawing_file, provider="local", model="qwen2.5-vl:7b-instruct-q4_k_m")
            elapsed = time.perf_counter() - start
            print(f"   [SIMULATED INFERENCE] Execution time: {elapsed*1000:.2f} ms")

    print(f"\n3. Extracted DrawingIR Pydantic Object:")
    print(f"   - Stock Dimensions: {result.stock_width} x {result.stock_height} x {result.stock_thickness} mm")
    print(f"   - Holes Count: {len(result.holes)}")
    for idx, h in enumerate(result.holes, 1):
        print(f"     Hole #{idx}: Center=({h.center.x}, {h.center.y}), Diameter=Ø{h.diameter}mm, Depth={h.depth}mm")
    print(f"   - Slots Count: {len(result.slots)}")
    for idx, s in enumerate(result.slots, 1):
        print(f"     Slot #{idx}: Width={s.width}mm, Depth={s.depth}mm, Vertices={len(s.centerline_path)} pts")
    print(f"\nComplete JSON:\n{result.model_dump_json(indent=2)}")


if __name__ == "__main__":
    run_standalone_benchmark()
