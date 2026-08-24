"""Prescription & lab report OCR ingestion (Module B) for PrakritiDesk.

Three-tier cascade for a single uploaded document, each tier only reached
if the one before it is unavailable or fails:

    1. Native OCR       cv2 image(s) -> PaddleOCR (pytesseract fallback)
                         -> raw text -> Groq text model -> structured JSON
    2. Groq Vision       raw image bytes -> Groq vision-language model
                         (OCR + structuring combined in one call)
    3. Structured fallback   a fixed "please review manually" JSON payload

This module only transcribes and structures what is printed/written on the
document -- it never diagnoses, recommends medication, or alters what a
clinician wrote.

ZERO-CRASH GUARANTEE: `process_prescription_image()` NEVER raises. A
missing native dependency (PaddleOCR/pytesseract/PyMuPDF), a missing
Tesseract binary, a missing/invalid GROQ_API_KEY, a network failure, or any
other internal error all degrade to the next tier instead of propagating an
exception -- the worst case is tier 3's fallback payload, still a normal
return value. `POST /prescription/upload` (app/main.py) can therefore never
500 "merely because" some optional OCR dependency isn't installed in this
environment; every response carries `ocr_status`/`confidence_score`/
`needs_review` so the caller always knows how much to trust it.
(The lower-level `decode_images_from_bytes()` / `extract_raw_text()`
primitives below still raise on failure, by design -- they're reused
building blocks for anyone who wants strict behavior; the guarantee applies
to the public `process_prescription_image()` entry point.)

Optional dependencies:
    pip install paddleocr paddlepaddle   # primary OCR engine (imported lazily, at first use)
    pip install pytesseract              # fallback OCR engine -- imported at module load
                                          # (it's a lightweight pure-Python wrapper, unlike
                                          # PaddleOCR), but still needs the actual Tesseract
                                          # binary installed on the host OS to do anything;
                                          # see TESSERACT_CMD below for how that's located
    pip install pymupdf                  # rasterizes PDF pages to images (imported lazily)
    pip install pillow numpy opencv-python-headless  # image handling
                                          # (numpy/opencv are hard deps --
                                          # see requirements.txt)
"""
import asyncio
import base64
import json
import logging
import os
import threading
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np
from dotenv import load_dotenv
from groq import AsyncGroq
from PIL import Image

load_dotenv()

logger = logging.getLogger("prakritidesk.ocr_engine")

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
DEFAULT_MODEL = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
# NOTE: hosted vision-model IDs on Groq change over time -- if this one 404s,
# check https://console.groq.com/docs/models for the current vision model
# name and set GROQ_VISION_MODEL in .env. A wrong/outdated model ID here
# just means the vision tier fails and falls through to the structured
# fallback (tier 3) -- it does not crash anything, per the zero-crash
# guarantee above.
GROQ_VISION_MODEL = os.getenv("GROQ_VISION_MODEL", "llama-3.2-11b-vision-instruct")
OCR_LANG = os.getenv("OCR_LANG", "en")  # PaddleOCR language code, e.g. "en", "hi"
# Prescriptions in this project's target deployment (Indian OPD) are
# routinely a mix of English drug names and Hindi handwriting/notes, so
# both language packs are requested by default rather than English alone.
TESSERACT_LANG = os.getenv("TESSERACT_LANG", "eng+hin")

# --------------------------------------------------------------------------
# pytesseract executable path -- configured at import time (not inside a
# function called later) since pytesseract.pytesseract.tesseract_cmd must be
# set before the first image_to_string() call, and it's a module-global on
# the pytesseract package itself.
#
# TESSERACT_CMD lets any deployment override this explicitly. Failing that,
# on Windows only, we check the standard Tesseract installer's default path
# and use it automatically if the binary is actually there -- this is what
# fixes the "tesseract is not installed or it's not in your PATH" error on a
# machine that has Tesseract installed but never added it to PATH (a very
# common state after running the official Windows installer). On any other
# OS, or if that path doesn't exist, pytesseract's own default (rely on
# PATH) is left alone -- e.g. a Linux/Docker deployment (see Dockerfile)
# that installs `tesseract-ocr` via apt already has it on PATH correctly.
#
# pytesseract itself is imported here, at module load, rather than lazily
# inside a function -- unlike PaddleOCR/PaddlePaddle it is a lightweight
# pure-Python wrapper with no heavy native build, so importing it eagerly
# doesn't reintroduce the slow-import problem PaddleOCR's lazy loading
# avoids. Still guarded by try/except so a deployment that genuinely
# doesn't have the `pytesseract` package installed doesn't fail to import
# this whole module -- see the ZERO-CRASH GUARANTEE note above.
_DEFAULT_WINDOWS_TESSERACT_CMD = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
TESSERACT_CMD = os.getenv("TESSERACT_CMD")
if not TESSERACT_CMD and os.name == "nt" and os.path.exists(_DEFAULT_WINDOWS_TESSERACT_CMD):
    TESSERACT_CMD = _DEFAULT_WINDOWS_TESSERACT_CMD

try:
    import pytesseract

    if TESSERACT_CMD:
        pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD
    _PYTESSERACT_IMPORTABLE = True
except ImportError:
    _PYTESSERACT_IMPORTABLE = False

# Below this, a result is flagged for a human to double check.
CONFIDENCE_REVIEW_THRESHOLD = 0.75
# pytesseract's image_to_string gives no per-line confidence signal, and the
# Groq Vision tier has no OCR-engine confidence at all -- both get a fixed,
# clearly-below-threshold estimate rather than pretending to a precision
# neither path actually has.
PYTESSERACT_DEFAULT_CONFIDENCE = 0.6
VISION_FALLBACK_DEFAULT_CONFIDENCE = 0.55

_groq_client: Optional[AsyncGroq] = None
_paddle_ocr_instance = None
_paddle_lock = threading.Lock()


def get_groq_client() -> AsyncGroq:
    global _groq_client
    if _groq_client is None:
        if not GROQ_API_KEY:
            raise RuntimeError("GROQ_API_KEY is not set")
        _groq_client = AsyncGroq(api_key=GROQ_API_KEY)
    return _groq_client


# --------------------------------------------------------------------------
# Step 1: decode the uploaded bytes into one or more OpenCV (BGR) images
# --------------------------------------------------------------------------

def _is_pdf(raw_bytes: bytes) -> bool:
    return raw_bytes[:5] == b"%PDF-"


def _pil_to_cv2(image: Image.Image) -> np.ndarray:
    """RGB PIL.Image -> BGR OpenCV ndarray (the channel order cv2/PaddleOCR expect)."""
    return cv2.cvtColor(np.array(image.convert("RGB")), cv2.COLOR_RGB2BGR)


def _decode_pdf_pages(raw_bytes: bytes) -> List[np.ndarray]:
    try:
        import fitz  # PyMuPDF
    except ImportError as exc:
        raise RuntimeError(
            "Received a PDF but PyMuPDF is not installed. Install it with `pip install pymupdf`."
        ) from exc

    pages: List[np.ndarray] = []
    with fitz.open(stream=raw_bytes, filetype="pdf") as doc:
        for page in doc:
            # 2x zoom gives OCR engines noticeably better accuracy on
            # typical prescription-scan resolutions than the default 72dpi.
            pixmap = page.get_pixmap(matrix=fitz.Matrix(2, 2))
            pil_image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
            pages.append(_pil_to_cv2(pil_image))

    if not pages:
        raise ValueError("PDF has no pages to OCR")
    return pages


def decode_images_from_bytes(image_bytes: bytes) -> List[np.ndarray]:
    """Turn raw upload bytes (JPG/PNG/PDF) into a list of BGR OpenCV images.

    Raises ValueError if the bytes cannot be decoded as an image at all.
    (This low-level primitive still raises by design -- see the module
    docstring's ZERO-CRASH GUARANTEE note for how process_prescription_image
    handles that.)
    """
    if not image_bytes:
        raise ValueError("image_bytes is empty")

    if _is_pdf(image_bytes):
        return _decode_pdf_pages(image_bytes)

    file_bytes = np.frombuffer(image_bytes, dtype=np.uint8)
    image = cv2.imdecode(file_bytes, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(
            "Could not decode image_bytes as a JPG/PNG image (cv2.imdecode returned None) -- "
            "the upload is either corrupted or not a supported image format."
        )
    return [image]


# --------------------------------------------------------------------------
# Step 2 (tier 1): OCR the page images (PaddleOCR primary, pytesseract fallback)
# --------------------------------------------------------------------------

class OcrLine:
    """One detected line of text plus where PaddleOCR found it and how
    confident it was -- confidence feeds process_prescription_image's
    confidence_score; box is kept for a possible future overlay UI."""

    __slots__ = ("text", "confidence", "box")

    def __init__(self, text: str, confidence: float, box: List[List[float]]):
        self.text = text
        self.confidence = confidence
        self.box = box


def _get_paddle_ocr():
    global _paddle_ocr_instance
    if _paddle_ocr_instance is None:
        with _paddle_lock:
            if _paddle_ocr_instance is None:
                from paddleocr import PaddleOCR  # heavy import, done lazily

                try:
                    _paddle_ocr_instance = PaddleOCR(use_angle_cls=True, lang=OCR_LANG, show_log=False)
                except TypeError:
                    # Newer PaddleOCR releases dropped the `show_log` kwarg.
                    _paddle_ocr_instance = PaddleOCR(use_angle_cls=True, lang=OCR_LANG)
    return _paddle_ocr_instance


def _run_paddle_ocr(images: List[np.ndarray]) -> Tuple[str, List[OcrLine]]:
    ocr = _get_paddle_ocr()
    all_lines: List[OcrLine] = []

    for image in images:
        result = ocr.ocr(image, cls=True)
        for page_result in result or []:
            for detection in page_result or []:
                # detection = [box_points, (text, confidence)]
                box, (text, confidence) = detection
                if text:
                    all_lines.append(OcrLine(text=text, confidence=float(confidence), box=box))

    raw_text = "\n".join(line.text for line in all_lines)
    return raw_text, all_lines


def _run_pytesseract_ocr(images: List[np.ndarray]) -> str:
    if not _PYTESSERACT_IMPORTABLE:
        raise ImportError("pytesseract is not installed")

    lines: List[str] = []
    for image in images:
        pil_image = Image.fromarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
        text = pytesseract.image_to_string(pil_image, lang=TESSERACT_LANG)
        if text and text.strip():
            lines.append(text.strip())
    return "\n".join(lines)


def _run_ocr_sync_detailed(images: List[np.ndarray]) -> Tuple[str, Optional[float], str]:
    """Blocking OCR call: PaddleOCR first, pytesseract as a fallback.

    Returns (raw_text, avg_confidence_or_None, engine_used). Raises
    RuntimeError if no OCR engine is usable at all -- callers that want the
    zero-crash guarantee (process_prescription_image) catch this and
    degrade to the next tier; extract_raw_text()/extract_raw_text_with_confidence()
    intentionally let it propagate for callers that want strict behavior.
    """
    paddle_error: Optional[Exception] = None
    try:
        raw_text, lines = _run_paddle_ocr(images)
        if raw_text.strip():
            logger.debug("PaddleOCR detected %d line(s) across %d page(s)", len(lines), len(images))
            avg_confidence = sum(line.confidence for line in lines) / len(lines) if lines else None
            return raw_text, avg_confidence, "paddleocr"
        logger.warning("PaddleOCR returned no text, falling back to pytesseract")
    except ImportError:
        logger.warning("PaddleOCR is not installed, falling back to pytesseract")
    except Exception as exc:
        logger.exception("PaddleOCR failed, falling back to pytesseract")
        paddle_error = exc

    try:
        text = _run_pytesseract_ocr(images)
        return text, None, "pytesseract"
    except ImportError as exc:
        detail = f" (PaddleOCR also failed: {paddle_error})" if paddle_error else ""
        raise RuntimeError(
            "Neither PaddleOCR nor pytesseract is available. "
            "Install one with `pip install paddleocr paddlepaddle` or `pip install pytesseract` "
            f"(the latter also needs the Tesseract binary on the host).{detail}"
        ) from exc
    except Exception as exc:
        raise RuntimeError(f"pytesseract OCR failed: {exc}") from exc


def _run_ocr_sync(images: List[np.ndarray]) -> str:
    text, _confidence, _engine = _run_ocr_sync_detailed(images)
    return text


async def extract_raw_text(image_bytes: bytes) -> str:
    """Decode the upload and run OCR on it without blocking the event loop.
    Raises on failure -- see decode_images_from_bytes()'s docstring."""
    images = await asyncio.to_thread(decode_images_from_bytes, image_bytes)
    return await asyncio.to_thread(_run_ocr_sync, images)


async def extract_raw_text_with_confidence(image_bytes: bytes) -> Tuple[str, Optional[float], str]:
    """Like extract_raw_text(), but also returns (avg_confidence_or_None,
    engine_used). Raises on failure, same as extract_raw_text()."""
    images = await asyncio.to_thread(decode_images_from_bytes, image_bytes)
    return await asyncio.to_thread(_run_ocr_sync_detailed, images)


# --------------------------------------------------------------------------
# Step 3 (tier 1 continued): structure raw OCR text into clinical JSON via Groq
# --------------------------------------------------------------------------

STRUCTURING_SYSTEM_PROMPT = """You structure raw OCR text from a scanned/photographed medical prescription into clinical JSON.

You are NOT a doctor. Never diagnose, never invent a medicine, dosage, or instruction that is not present in the text, and never suggest a treatment. Your only job is to transcribe and organize what is already written in the OCR text, which may contain OCR noise (misread characters, broken words, garbled lines) -- do your best to interpret it, but if a field truly cannot be determined, use null (or an empty list/object) rather than guessing.

Extract:
- patient_name: the patient's name if written on the prescription, else null.
- prescribed_medicines: a list of conventional/allopathic medicines mentioned, each as {"name": string, "dosage": string or null, "frequency": string or null, "duration": string or null}. Empty list if none found.
- ayush_formulations: a list of Ayurvedic/AYUSH formulations mentioned (e.g. churna, kwatha, vati, taila, rasayana), each as {"herb_or_churn": string, "anupana": string or null (the vehicle/adjuvant it should be taken with, e.g. warm water, honey), "timing": string or null (e.g. before/after food, morning/night)}. Empty list if none found.
- vitals_noted: any vitals or measurements written on the document (e.g. blood pressure, pulse, temperature, weight, blood sugar) as a flat JSON object of label -> value strings. Empty object if none found.

Respond with STRICT JSON only, no markdown, no extra commentary, matching exactly this shape:
{"patient_name": "..." or null, "prescribed_medicines": [{"name": "...", "dosage": "..." or null, "frequency": "..." or null, "duration": "..." or null}], "ayush_formulations": [{"herb_or_churn": "...", "anupana": "..." or null, "timing": "..." or null}], "vitals_noted": {}}
"""


def _empty_structured_result(raw_text: str) -> Dict[str, Any]:
    return {
        "patient_name": None,
        "prescribed_medicines": [],
        "ayush_formulations": [],
        "vitals_noted": {},
        "raw_text_extracted": raw_text,
    }


async def structure_prescription_text(raw_text: str) -> Dict[str, Any]:
    """Send OCR'd text to Groq and parse it into the clinical JSON shape.

    A Groq failure here degrades gracefully to raw-text-only rather than
    raising: the OCR step already succeeded, so a staff member can still
    read the prescription even if the LLM structuring step is temporarily
    unavailable.
    """
    if not raw_text.strip():
        return _empty_structured_result(raw_text)

    try:
        client = get_groq_client()
        completion = await client.chat.completions.create(
            model=DEFAULT_MODEL,
            messages=[
                {"role": "system", "content": STRUCTURING_SYSTEM_PROMPT},
                {"role": "user", "content": f"OCR text extracted from the prescription:\n\n{raw_text}"},
            ],
            temperature=0,
            max_tokens=1000,
            response_format={"type": "json_object"},
        )
        parsed = json.loads(completion.choices[0].message.content)
    except Exception:
        logger.exception("Groq prescription structuring failed")
        return _empty_structured_result(raw_text)

    return {
        "patient_name": parsed.get("patient_name"),
        "prescribed_medicines": parsed.get("prescribed_medicines") or [],
        "ayush_formulations": parsed.get("ayush_formulations") or [],
        "vitals_noted": parsed.get("vitals_noted") or {},
        "raw_text_extracted": raw_text,
    }


# --------------------------------------------------------------------------
# Tier 2: Groq Vision fallback -- OCR + structuring in a single multimodal
# call, used only when the native tier is unavailable or fails. Needs only
# `groq` (already a hard dependency); a plain JPG/PNG upload doesn't even
# need PaddleOCR/pytesseract/cv2-pixel-processing to reach this tier. A PDF
# upload still needs PyMuPDF to rasterize a page first, since vision models
# take images, not raw PDF bytes.
# --------------------------------------------------------------------------

VISION_STRUCTURING_SYSTEM_PROMPT = """You read a scanned/photographed medical prescription image directly and structure what you see into clinical JSON.

You are NOT a doctor. Never diagnose, never invent a medicine, dosage, or instruction that is not visibly present in the image, and never suggest a treatment. Transcribe and organize only what you can actually read -- handwriting or scan quality may be poor, so if a field truly cannot be determined, use null (or an empty list/object) rather than guessing.

Extract:
- patient_name: the patient's name if visible, else null.
- prescribed_medicines: conventional/allopathic medicines, each as {"name": string, "dosage": string or null, "frequency": string or null, "duration": string or null}. Empty list if none found.
- ayush_formulations: Ayurvedic/AYUSH formulations (e.g. churna, kwatha, vati, taila, rasayana), each as {"herb_or_churn": string, "anupana": string or null, "timing": string or null}. Empty list if none found.
- vitals_noted: any vitals/measurements visible (blood pressure, pulse, temperature, weight, blood sugar) as a flat JSON object of label -> value strings. Empty object if none found.
- raw_text_extracted: your best-effort transcription of all the visible text on the document, in reading order.

Respond with STRICT JSON only, no markdown, no extra commentary, matching exactly this shape:
{"patient_name": "..." or null, "prescribed_medicines": [{"name": "...", "dosage": "..." or null, "frequency": "..." or null, "duration": "..." or null}], "ayush_formulations": [{"herb_or_churn": "...", "anupana": "..." or null, "timing": "..." or null}], "vitals_noted": {}, "raw_text_extracted": "..."}
"""


def _infer_image_mime_type(image_bytes: bytes) -> str:
    if image_bytes[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if image_bytes[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    return "image/jpeg"  # reasonable default -- a wrong guess just fails this tier cleanly


async def _structure_via_groq_vision(image_bytes: bytes) -> Dict[str, Any]:
    if not GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY is not set; cannot use the Groq Vision fallback")

    if _is_pdf(image_bytes):
        # Rasterize only the first page -- a full multi-page vision pass
        # would multiply token cost for comparatively little benefit on a
        # single prescription document, and this is already the fallback
        # of a fallback.
        pages = await asyncio.to_thread(_decode_pdf_pages, image_bytes)
        success, encoded = cv2.imencode(".png", pages[0])
        if not success:
            raise RuntimeError("Failed to re-encode the rasterized PDF page for Groq Vision")
        page_bytes = encoded.tobytes()
        mime_type = "image/png"
    else:
        page_bytes = image_bytes
        mime_type = _infer_image_mime_type(image_bytes)

    b64_image = base64.b64encode(page_bytes).decode("ascii")

    client = get_groq_client()
    completion = await client.chat.completions.create(
        model=GROQ_VISION_MODEL,
        messages=[
            {"role": "system", "content": VISION_STRUCTURING_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Read this prescription/document image and extract the clinical data."},
                    {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{b64_image}"}},
                ],
            },
        ],
        temperature=0,
        max_tokens=1200,
        response_format={"type": "json_object"},
    )
    parsed = json.loads(completion.choices[0].message.content)

    return {
        "patient_name": parsed.get("patient_name"),
        "prescribed_medicines": parsed.get("prescribed_medicines") or [],
        "ayush_formulations": parsed.get("ayush_formulations") or [],
        "vitals_noted": parsed.get("vitals_noted") or {},
        "raw_text_extracted": parsed.get("raw_text_extracted") or "",
    }


# --------------------------------------------------------------------------
# Tier 3: structured fallback (never fails, no external calls)
# --------------------------------------------------------------------------

def _fallback_mode_result(reason: str) -> Dict[str, Any]:
    logger.warning("OCR fully degraded to fallback_mode: %s", reason)
    return {
        "ocr_status": "fallback_mode",
        "patient_name": None,
        "prescribed_medicines": [],
        "ayush_formulations": [],
        "vitals_noted": {},
        "raw_text_extracted": "[OCR Engine in Fallback Mode: Please review document manually]",
        "confidence_score": 0.0,
        "needs_review": True,
        "needs_human_review": True,
    }


def _finalize_result(structured: Dict[str, Any], ocr_status: str, confidence_score: float) -> Dict[str, Any]:
    result = dict(structured)
    result["ocr_status"] = ocr_status
    result["confidence_score"] = round(max(0.0, min(1.0, confidence_score)), 2)
    result["needs_review"] = result["confidence_score"] < CONFIDENCE_REVIEW_THRESHOLD
    return result


# --------------------------------------------------------------------------
# Public entry point
# --------------------------------------------------------------------------

async def _process_prescription_image_inner(image_bytes: bytes) -> Dict[str, Any]:
    if not image_bytes:
        return _fallback_mode_result("image_bytes is empty")

    # Tier 1: native OCR (PaddleOCR/pytesseract) + Groq text structuring.
    try:
        raw_text, confidence, engine = await extract_raw_text_with_confidence(image_bytes)
        structured = await structure_prescription_text(raw_text)
        score = confidence if confidence is not None else PYTESSERACT_DEFAULT_CONFIDENCE
        return _finalize_result(structured, f"native_ocr_{engine}", score)
    except Exception as exc:
        logger.warning("Native OCR pipeline unavailable/failed (%s); trying Groq Vision fallback", exc)

    # Tier 2: Groq Vision (OCR + structuring combined).
    try:
        structured = await _structure_via_groq_vision(image_bytes)
        return _finalize_result(structured, "vision_fallback", VISION_FALLBACK_DEFAULT_CONFIDENCE)
    except Exception as exc:
        logger.warning("Groq Vision fallback also failed (%s)", exc)

    # Tier 3: fixed structured payload -- always succeeds.
    return _fallback_mode_result("native OCR and Groq Vision fallback both unavailable/failed")


async def process_prescription_image(image_bytes: bytes) -> dict:
    """End-to-end: OCR the uploaded image/PDF, then structure it into clinical JSON.

    NEVER raises -- see the module docstring's ZERO-CRASH GUARANTEE. The
    outer try/except here is a last-resort safety net in case of a truly
    unanticipated bug in the cascade above; the cascade itself already
    catches everything it knows how to degrade from.

    Returns:
        {
          "patient_name": str or None,
          "prescribed_medicines": [{"name", "dosage", "frequency", "duration"}],
          "ayush_formulations": [{"herb_or_churn", "anupana", "timing"}],
          "vitals_noted": {...},
          "raw_text_extracted": str,
          "ocr_status": "native_ocr_paddleocr" | "native_ocr_pytesseract" | "vision_fallback" | "fallback_mode",
          "confidence_score": float,   # 0.0-1.0
          "needs_review": bool,        # confidence_score below CONFIDENCE_REVIEW_THRESHOLD
          "needs_human_review": bool,  # only present in fallback_mode (always True there)
        }
    """
    try:
        return await _process_prescription_image_inner(image_bytes)
    except Exception:
        logger.exception("Unexpected error in process_prescription_image; returning fallback_mode payload")
        return _fallback_mode_result("unexpected internal error")
