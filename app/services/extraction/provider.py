"""Gemini extraction provider with versioned prompt and Fake provider for testing (SPEC B5, AC-01)."""

from abc import ABC, abstractmethod
import io
import json
from pathlib import Path
from typing import Any, Dict, Optional
from PIL import Image
from app.domain.extraction_models import RawExtractionOutput
from app.infra.settings import settings

PROMPT_VERSION = "v1.0"
DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"

GEMINI_EXTRACTION_PROMPT = """You are reading a cropped picture from a 'DAILY GENERATION REPORT' of Sunpro Renewable Energy Private Limited.
The picture holds the report date, the table header row and ONE customer row.
Return only the JSON object that matches the schema.

1. Read the date as printed (DD/MM/YYYY) into date_raw.
2. Read only the customer row that is shown. Do not infer or mention any other row.
3. Copy each number exactly as printed. Remove thousands separators only. Keep decimals.
4. If a value is blurry, cut off or ambiguous, return null for it and a low confidence. Never guess or estimate.
"""


class ExtractionProvider(ABC):
    """Abstract interface for image extraction providers."""

    @abstractmethod
    def extract(self, image_path: Path) -> RawExtractionOutput:
        """Extract data from a cropped report image."""
        pass


class GeminiExtractionProvider(ExtractionProvider):
    """Google Gemini vision extraction using official GenAI SDK and structured JSON output."""

    def __init__(self, api_key: Optional[str] = None, model_name: str = DEFAULT_GEMINI_MODEL) -> None:
        self.api_key = api_key or settings.GEMINI_API_KEY
        self.model_name = model_name

    def extract(self, image_path: Path) -> RawExtractionOutput:
        """Call Gemini model with cropped image and response_schema."""
        try:
            from google import genai
        except ImportError:
            raise ImportError(
                "google-genai SDK not installed. Please install with `pip install google-genai`."
            )

        client = genai.Client(api_key=self.api_key)

        with open(image_path, "rb") as f:
            image_bytes = f.read()

        response = client.models.generate_content(
            model=self.model_name,
            contents=[
                GEMINI_EXTRACTION_PROMPT,
                genai.types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"),
            ],
            config={
                "response_mime_type": "application/json",
                "response_schema": RawExtractionOutput,
            },
        )

        if hasattr(response, "parsed") and response.parsed is not None:
            return response.parsed

        # Fallback parsing
        raw_text = response.text or "{}"
        return RawExtractionOutput.model_validate_json(raw_text)


class FakeGeminiExtractionProvider(ExtractionProvider):
    """Deterministic fake provider for automated testing and offline development."""

    def __init__(self, override_response: Optional[RawExtractionOutput] = None, should_fail: bool = False, fail_message: str = "") -> None:
        self.override_response = override_response
        self.should_fail = should_fail
        self.fail_message = fail_message

    def extract(self, image_path: Path) -> RawExtractionOutput:
        if self.should_fail:
            raise ValueError(self.fail_message or "Extraction failed: Image unreadable or blurry.")

        if self.override_response is not None:
            return self.override_response

        # Default golden response matching tests/golden/report_2026-05-22.jpeg (AC-01)
        # S.NO: 5, Customer: M/s. SRS KUMARAN INDIA PVT LTD, MW: 1, Inverter: 7625.00,
        # Monthly: 130428.00, Yearly: 565368.00, EB: 7452.00, 6-10am: 1584.00,
        # Inverter Avail: 100.0%, Grid Avail: 100.0%, Weather: sunny, Temp: 35
        # Must NOT return Prabhu Textiles (serial 6, 7640, 7476, 1608)
        return RawExtractionOutput(
            date_raw="22/05/2026",
            customer_name_raw="M/s. SRS KUMARAN INDIA PVT LTD",
            serial_no=5,
            capacity_mw=1.0,
            inverter_generation_today_kwh=7625.00,
            monthly_generated_kwh=130428.00,
            yearly_generated_kwh=565368.00,
            grid_export_kwh=7452.00,
            reading_6am_10am_kwh=1584.00,
            inverter_availability_pct=100.0,
            grid_availability_pct=100.0,
            fault_alarm_text="",
            weather_condition_text="sunny",
            temperature_c=35.0,
        )
