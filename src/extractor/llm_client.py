"""
LLM client for invoice extraction using GPT-4o-mini vision.

Supports:
  - PDF with text layer   → rendered to image via pypdf + Pillow
  - PDF with scanned image → same rendering path
  - JPEG / PNG            → loaded directly

All pages are base64-encoded and sent to the OpenAI vision API.
The response is parsed into an ExtractionResult.
"""

from __future__ import annotations

import base64
import io
import json
import os
import re
from pathlib import Path
from typing import List

from dotenv import load_dotenv

load_dotenv()

from .prompts import SYSTEM_PROMPT, build_user_message
from .schema import ExtractionResult, RawInvoice, RawLineItem

# ---------------------------------------------------------------------------
# Lazy imports for optional heavy deps so tests can import without them
# ---------------------------------------------------------------------------

def _import_openai():
    import openai  # noqa: PLC0415
    return openai


def _pdf_to_images(pdf_path: Path) -> List[bytes]:
    """Render each page of a PDF to JPEG bytes using pypdf + Pillow."""
    try:
        from pypdf import PdfReader  # noqa: PLC0415
        from PIL import Image  # noqa: PLC0415
    except ImportError as exc:
        raise ImportError("pypdf and Pillow are required to process PDFs") from exc

    reader = PdfReader(str(pdf_path))
    images: List[bytes] = []

    for page in reader.pages:
        # Try to extract embedded images first (common for scanned PDFs)
        page_images = list(page.images)
        if page_images:
            for img_obj in page_images:
                buf = io.BytesIO(img_obj.data)
                pil_img = Image.open(buf).convert("RGB")
                out = io.BytesIO()
                pil_img.save(out, format="JPEG", quality=90)
                images.append(out.getvalue())
        else:
            # Text-layer PDF: render via pypdf's visitor approach
            # Fall back: create a white placeholder page and let text layer be read
            # For text-layer PDFs we still need a visual; use a simple render
            try:
                import pypdf  # noqa: PLC0415
                # pypdf doesn't render; use a minimal approach: extract text as an image
                # We'll create a text annotation image
                text = page.extract_text() or ""
                pil_img = _text_to_image(text)
                out = io.BytesIO()
                pil_img.save(out, format="JPEG", quality=90)
                images.append(out.getvalue())
            except Exception:
                pass

    return images if images else []


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


def _parse_llm_response(raw_text: str, source_file: str) -> ExtractionResult:
    """Parse the JSON returned by GPT-4o-mini into an ExtractionResult."""
    # Strip code fences if present (defensive)
    text = raw_text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        return ExtractionResult(
            source_file=source_file,
            raw=None,
            success=False,
            error=f"JSON parse error: {exc}",
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
    """Extracts structured data from invoice files using GPT-4o-mini."""

    def __init__(self, api_key: str | None = None, model: str = "gpt-4o-mini"):
        openai = _import_openai()
        self.client = openai.OpenAI(api_key=api_key or os.environ["OPENAI_API_KEY"])
        self.model = model

    def extract(self, file_path: str | Path) -> ExtractionResult:
        """Extract invoice data from a PDF or image file."""
        path = Path(file_path)
        source = path.name

        # Load image bytes
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

        # Build content parts: text + image(s)
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

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": content_parts},
                ],
                max_tokens=2000,
                temperature=0,
            )
            raw_text = response.choices[0].message.content or ""
        except Exception as exc:
            return ExtractionResult(
                source_file=source, raw=None, success=False,
                error=f"API call error: {exc}"
            )

        result = _parse_llm_response(raw_text, source)
        return result
