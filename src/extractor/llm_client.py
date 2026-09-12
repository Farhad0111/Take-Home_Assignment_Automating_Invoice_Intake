"""
LLM client for invoice extraction using GPT-4o-mini vision.

Supports:
  - PDF with text layer   → rendered to image via pypdf + Pillow
  - PDF with scanned image → same rendering path
  - JPEG / PNG            → loaded directly

All pages are base64-encoded and sent to the OpenAI vision API.
The response is parsed into an ExtractionResult.

Resilience:
  - Retries up to MAX_RETRIES times on API errors or JSON parse failures.
  - _repair_json() fixes the most common GPT malformed-JSON patterns
    (trailing commas, unescaped control chars, truncated objects) before
    falling back to a retry.
"""

from __future__ import annotations

import base64
import io
import json
import os
import re
import time
from pathlib import Path
from typing import List

from dotenv import load_dotenv

load_dotenv()

from .prompts import SYSTEM_PROMPT, build_user_message
from .schema import ExtractionResult, RawInvoice, RawLineItem

# ---------------------------------------------------------------------------
# Retry / resilience settings
# ---------------------------------------------------------------------------

MAX_RETRIES = 3          # total attempts (1 original + 2 retries)
RETRY_DELAY_S = 2.0      # base delay in seconds; doubles each retry

# ---------------------------------------------------------------------------
# Lazy imports for optional heavy deps so tests can import without them
# ---------------------------------------------------------------------------

def _import_openai():
    import openai  # noqa: PLC0415
    return openai


def _pdf_to_images(pdf_path: Path) -> List[bytes]:
    """Render each page of a PDF to JPEG bytes using pymupdf (fitz).

    pymupdf renders both text-layer and scanned PDFs faithfully, preserving
    layout, tables and fonts — unlike the old pypdf+Pillow text-extraction
    fallback which silently returned an empty list for text-layer PDFs.
    """
    try:
        import pymupdf  # noqa: PLC0415
    except ImportError as exc:
        raise ImportError(
            "pymupdf is required to process PDFs: pip install pymupdf"
        ) from exc

    doc = pymupdf.open(str(pdf_path))
    images: List[bytes] = []

    for page in doc:
        # Render at 150 DPI (scale=1.5×72 dpi default → ~150 dpi).
        # High enough for the vision model; low enough to stay under API limits.
        mat = pymupdf.Matrix(2.0, 2.0)  # 2× = 144 dpi — good balance
        pix = page.get_pixmap(matrix=mat, colorspace=pymupdf.csRGB)
        jpeg_bytes = pix.tobytes("jpeg", jpg_quality=90)
        images.append(jpeg_bytes)

    doc.close()
    return images


def _text_to_image(text: str):
    """Convert extracted text to a Pillow image for the vision model."""
    from PIL import Image, ImageDraw, ImageFont  # noqa: PLC0415

    width = 800
    font_size = 14
    line_height = font_size + 4
    lines = text.splitlines()
    height = max(200, len(lines) * line_height + 40)

    img = Image.new("RGB", (width, height), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)

    try:
        # Try to use a system font that supports Japanese
        font = ImageFont.truetype("C:/Windows/Fonts/msgothic.ttc", font_size)
    except Exception:
        try:
            font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", font_size)
        except Exception:
            font = ImageFont.load_default()

    y = 20
    for line in lines:
        draw.text((10, y), line, fill=(0, 0, 0), font=font)
        y += line_height
        if y > height - 20:
            break

    return img


def _image_file_to_bytes(path: Path) -> bytes:
    """Load an image file and return JPEG bytes."""
    from PIL import Image  # noqa: PLC0415

    with Image.open(str(path)) as img:
        img = img.convert("RGB")
        out = io.BytesIO()
        img.save(out, format="JPEG", quality=90)
        return out.getvalue()


def _to_base64(data: bytes) -> str:
    return base64.b64encode(data).decode("utf-8")


def _repair_json(text: str) -> str:
    """
    Apply lightweight heuristic fixes to common GPT JSON output problems.

    Patterns fixed:
      1. Trailing commas before ] or }  e.g. {"a": 1,}  →  {"a": 1}
      2. Unescaped ASCII control characters (\x00-\x1f) inside strings
      3. Truncated JSON — append missing closing brackets so json.loads
         can at least partially succeed.
    """
    # 1. Strip trailing commas before closing brace/bracket
    text = re.sub(r",\s*([}\]])", r"\1", text)

    # 2. Remove unescaped control characters (except \t \n \r which are valid)
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)

    # 3. If the JSON is truncated, try to close open structures
    #    Count unmatched { and [ and append the missing closers.
    depth_curly = 0
    depth_square = 0
    in_string = False
    escape_next = False
    for ch in text:
        if escape_next:
            escape_next = False
            continue
        if ch == "\\" and in_string:
            escape_next = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth_curly += 1
        elif ch == "}":
            depth_curly -= 1
        elif ch == "[":
            depth_square += 1
        elif ch == "]":
            depth_square -= 1

    # Close any unclosed strings first (best-effort)
    if in_string:
        text += '"'
    # Close unclosed arrays then objects
    text += "]" * max(0, depth_square)
    text += "}" * max(0, depth_curly)

    return text


def _parse_llm_response(raw_text: str, source_file: str) -> ExtractionResult:
    """Parse the JSON returned by GPT-4o-mini into an ExtractionResult.

    Attempts plain json.loads first; on failure applies _repair_json and
    retries once before giving up with a descriptive error.
    """
    # Strip code fences if present (defensive)
    text = raw_text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)

    # Try to parse; if it fails, apply repair and try once more
    data = None
    parse_error: str | None = None
    for attempt_text in (text, _repair_json(text)):
        try:
            data = json.loads(attempt_text)
            parse_error = None
            break
        except json.JSONDecodeError as exc:
            parse_error = f"JSON parse error: {exc}"

    if data is None:
        return ExtractionResult(
            source_file=source_file,
            raw=None,
            success=False,
            error=parse_error,
        )

    try:
        lines = []
        for item in data.get("lines", []):
            lines.append(
                RawLineItem(
                    description=str(item.get("description", "")),
                    quantity=item.get("quantity"),
                    unit=str(item.get("unit", "式")),
                    unit_price=item.get("unit_price"),
                    amount=int(item.get("amount", 0)),
                    tax_rate_hint=item.get("tax_rate_hint"),
                )
            )

        raw = RawInvoice(
            supplier_name=str(data.get("supplier_name", "")),
            registration_no=data.get("registration_no"),
            invoice_number=str(data.get("invoice_number", "")),
            issue_date_raw=str(data.get("issue_date_raw", "")),
            due_date_raw=data.get("due_date_raw"),
            subtotal_raw=str(data.get("subtotal_raw", "0")),
            tax_amount_raw=str(data.get("tax_amount_raw", "0")),
            total_amount_raw=str(data.get("total_amount_raw", "0")),
            lines=lines,
            confidence=data.get("confidence", {}),
            source_file=source_file,
        )
        return ExtractionResult(source_file=source_file, raw=raw, success=True)

    except Exception as exc:
        return ExtractionResult(
            source_file=source_file,
            raw=None,
            success=False,
            error=f"Data mapping error: {exc}",
        )


class InvoiceExtractor:
    """Extracts structured data from invoice files using GPT-4o-mini.

    Retries up to MAX_RETRIES times on transient API errors or JSON parse
    failures, with exponential back-off (RETRY_DELAY_S * 2^attempt).
    """

    def __init__(self, api_key: str | None = None, model: str = "gpt-4o-mini"):
        openai = _import_openai()
        self.client = openai.OpenAI(api_key=api_key or os.environ["OPENAI_API_KEY"])
        self.model = model

    def extract(self, file_path: str | Path) -> ExtractionResult:
        """Extract invoice data from a PDF or image file.

        Retries on API errors and JSON parse failures up to MAX_RETRIES times.
        Returns the last ExtractionResult (success or failure) after all attempts.
        """
        path = Path(file_path)
        source = path.name

        # ------------------------------------------------------------------ #
        # Step 1: Load image bytes (no retry — file errors are permanent)
        # ------------------------------------------------------------------ #
        try:
            if path.suffix.lower() == ".pdf":
                image_bytes_list = _pdf_to_images(path)
            else:
                image_bytes_list = [_image_file_to_bytes(path)]
        except Exception as exc:
            return ExtractionResult(
                source_file=source, raw=None, success=False,
                error=f"File loading error: {exc}"
            )

        if not image_bytes_list:
            return ExtractionResult(
                source_file=source, raw=None, success=False,
                error="Could not extract any images from file"
            )

        # ------------------------------------------------------------------ #
        # Step 2: Build the vision content parts (built once, reused per try)
        # ------------------------------------------------------------------ #
        content_parts = [
            {"type": "text", "text": build_user_message(len(image_bytes_list))}
        ]
        for img_bytes in image_bytes_list:
            content_parts.append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/jpeg;base64,{_to_base64(img_bytes)}",
                    "detail": "high",
                },
            })

        # ------------------------------------------------------------------ #
        # Step 3: Call the API with retry logic
        # ------------------------------------------------------------------ #
        last_result: ExtractionResult | None = None
        all_errors: list[str] = []

        for attempt in range(1, MAX_RETRIES + 1):
            # --- API call ---
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": content_parts},
                    ],
                    max_tokens=4096,
                    temperature=0,
                )
                raw_text = response.choices[0].message.content or ""
            except Exception as exc:
                err = f"API call error (attempt {attempt}/{MAX_RETRIES}): {exc}"
                print(f"    [WARN] {err}")
                all_errors.append(err)
                last_result = ExtractionResult(
                    source_file=source, raw=None, success=False, error=err
                )
                if attempt < MAX_RETRIES:
                    delay = RETRY_DELAY_S * (2 ** (attempt - 1))
                    print(f"    [RETRY] Waiting {delay:.1f}s before attempt {attempt + 1}...")
                    time.sleep(delay)
                continue

            # --- Parse response ---
            last_result = _parse_llm_response(raw_text, source)

            if last_result.success:
                if attempt > 1:
                    print(f"    [OK] Extraction succeeded on attempt {attempt}/{MAX_RETRIES}.")
                return last_result

            # Parse failed — record and decide whether to retry
            err = f"Parse error (attempt {attempt}/{MAX_RETRIES}): {last_result.error}"
            print(f"    [WARN] {err}")
            all_errors.append(err)

            if attempt < MAX_RETRIES:
                delay = RETRY_DELAY_S * (2 ** (attempt - 1))
                print(f"    [RETRY] Waiting {delay:.1f}s before attempt {attempt + 1}...")
                time.sleep(delay)

        # All retries exhausted
        combined_error = " | ".join(all_errors)
        print(f"    [FAIL] All {MAX_RETRIES} attempts failed for {source}: {combined_error}")
        return ExtractionResult(
            source_file=source,
            raw=None,
            success=False,
            error=f"Extraction failed after {MAX_RETRIES} attempts. Last error: {last_result.error if last_result else 'unknown'}",
        )
