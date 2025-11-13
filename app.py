import os
import json
import base64
from typing import List

import fitz  # PyMuPDF
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel
from openai import OpenAI

# -------------------------------------------------------------------
# Environment and setup
# -------------------------------------------------------------------
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
SERVICE_API_KEY = os.getenv("SERVICE_API_KEY")  # shared secret with Apps Script

if not OPENAI_API_KEY:
    raise RuntimeError("OPENAI_API_KEY not set")

client = OpenAI(api_key=OPENAI_API_KEY)
app = FastAPI(title="Lipsey OCR Service")

# -------------------------------------------------------------------
# Models
# -------------------------------------------------------------------
class ProcessPayload(BaseModel):
    fileBase64: str
    filename: str = "receipt.pdf"
    max_pages: int = 4  # we hard-cap to 4 below


# -------------------------------------------------------------------
# Utilities
# -------------------------------------------------------------------
def data_url_from_png_bytes(b: bytes) -> str:
    """Convert PNG bytes to a data URL for OpenAI image inputs."""
    return "data:image/png;base64," + base64.b64encode(b).decode("utf-8")


def pdf_to_page_pngs(pdf_bytes: bytes, max_pages: int = 4, dpi: int = 300) -> List[bytes]:
    """
    Render the first N PDF pages to PNG bytes at high DPI.
    Higher DPI -> better OCR fidelity for small text/rows.
    """
    images: List[bytes] = []
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    pages = min(len(doc), max_pages)
    for i in range(pages):
        page = doc.load_page(i)
        mat = fitz.Matrix(dpi / 72.0, dpi / 72.0)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        images.append(pix.tobytes("png"))
    doc.close()
    return images


def _to_num(s) -> float:
    try:
        return float(str(s).replace("$", "").replace(",", "").strip())
    except Exception:
        return 0.0


# -------------------------------------------------------------------
# Prompts
# -------------------------------------------------------------------
def build_system_prompt() -> str:
    return (
        "You are a meticulous table extractor for veterinary clinic receipts.\n"
        "Receipts include:\n"
        "  • Client block (name, address, ZIP)\n"
        "  • Header block (invoice/receipt details, payment summary)\n"
        "  • A service table titled or near 'Payment History' with columns: "
        "Patient, Provider, Description, Date, Quantity, Total.\n\n"
        "Rules:\n"
        "  1) The service table may CONTINUE across multiple pages. Treat all pages as one continuous table.\n"
        "  2) Return EVERY data row. Do NOT omit rows with $0.00, discounts, or strike-through pricing; "
        "     include the row if a 'Total' value is present for that row.\n"
        "  3) Ignore only Subtotal and Tax summary lines (do not add them as Items).\n"
        "  4) Associate each row with its Patient by the Patient column; group rows by patient name exactly as printed.\n"
        "  5) For each patient, PatientTotal = sum of that patient's 'Total' values.\n"
        "  6) Output strict JSON only (no commentary or markdown).\n"
        "  7) Dates remain exactly as seen (e.g., '10/6/2025'). Amounts have a leading '$' and two decimals.\n"
    )


def build_user_prompt() -> str:
    return (
        "Extract the following:\n\n"
        "Client fields:\n"
        "- FirstName\n"
        "- LastName\n"
        "- StandardizedName (proper case full name)\n"
        "- ZipCode\n"
        "- GrantEligibility (ZIP: 14211 or 14215 = 'PFL'; 14208 = 'Incubator'; else 'Extended Incubator')\n"
        "- InvoiceDate\n"
        "- InvoiceNumber\n"
        "- ReceiptDate\n"
        "- ReceiptNumber\n"
        "- AmountPaid\n"
        "- Payment\n\n"
        "Service table extraction from ALL pages (the table may continue across pages):\n"
        "- For EVERY data row (not header, not Subtotal, not Tax), capture: "
        "Patient, Provider, Description, Date, Quantity, Total\n"
        "- Group rows by Patient name.\n"
        "- For each patient, return: Name, Provider (dominant provider if repeated), PatientTotal, "
        "Items[] with objects { Description, Date, Quantity, Total }\n\n"
        "Return exactly this JSON structure (and nothing else):\n"
        "{\n"
        "  'Client': { ... },\n"
        "  'Patients': [\n"
        "    {\n"
        "      'Name': '',\n"
        "      'Provider': '',\n"
        "      'PatientTotal': '',\n"
        "      'Items': [ { 'Description': '', 'Date': '', 'Quantity': '', 'Total': '' } ]\n"
        "    }\n"
        "  ]\n"
        "}\n"
        "If a field is missing, use an empty string.\n"
    )


# -------------------------------------------------------------------
# Endpoint
# -------------------------------------------------------------------
@app.post("/process")
async def process(req: Request, payload: ProcessPayload):
    # Auth check
    if SERVICE_API_KEY:
        incoming = req.headers.get("X-API-Key")
        if incoming != SERVICE_API_KEY:
            raise HTTPException(status_code=401, detail="Unauthorized")

    # Clamp pages to a safe maximum
    try:
        max_pages = int(payload.max_pages or 4)
    except Exception:
        max_pages = 4
    max_pages = min(max_pages, 4)

    # Decode base64 PDF
    try:
        pdf_bytes = base64.b64decode(payload.fileBase64)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid base64: {e}")

    # Render PDF pages to PNG
    try:
        png_pages = pdf_to_page_pngs(pdf_bytes, max_pages=max_pages, dpi=300)
        if not png_pages:
            raise HTTPException(status_code=422, detail="Could not render PDF pages")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"PDF render failed: {e}")

    # Build Chat Completions messages with image data URLs
    messages = [
        {"role": "system", "content": build_system_prompt()},
        {
            "role": "user",
            "content": [{"type": "text", "text": build_user_prompt()}]
            + [
                {"type": "image_url", "image_url": {"url": data_url_from_png_bytes(p)}}
                for p in png_pages
            ],
        },
    ]

    # Call OpenAI (use stronger model for better table fidelity)
    try:
        resp = client.chat.completions.create(
            model="gpt-4o",
            messages=messages,
            temperature=0,
            response_format={"type": "json_object"},
        )
        content = resp.choices[0].message.content or ""
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"OpenAI error: {e}")

    # Parse JSON
    try:
        data = json.loads(content)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to parse JSON: {e}")

    # Optional meta sanity-check for coverage
    try:
        amt_paid = _to_num(data.get("Client", {}).get("AmountPaid", "0"))
        sum_patients = sum(_to_num(p.get("PatientTotal", "0")) for p in data.get("Patients", []))
        data["Meta"] = {
            "amount_paid": data.get("Client", {}).get("AmountPaid", ""),
            "patient_total_sum": f"${sum_patients:,.2f}",
            "coverage_ok": (sum_patients >= 0.8 * amt_paid) if amt_paid else True,
        }
    except Exception:
        # Meta is optional; never fail the request for this
        pass

    return data


# Optional simple health endpoint
@app.get("/healthz")
async def healthz():
    return {"ok": True}