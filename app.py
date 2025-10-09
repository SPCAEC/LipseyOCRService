import base64, io, os, json
import fitz  # PyMuPDF
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel
from openai import OpenAI

# ---- Environment and setup ----
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
SERVICE_API_KEY = os.getenv("SERVICE_API_KEY")  # shared secret with Apps Script
if not OPENAI_API_KEY:
    raise RuntimeError("OPENAI_API_KEY not set")

client = OpenAI(api_key=OPENAI_API_KEY)
app = FastAPI(title="Lipsey OCR Service")

# ---- Request model ----
class ProcessPayload(BaseModel):
    fileBase64: str
    filename: str = "receipt.pdf"
    max_pages: int = 4


# ---- Utilities ----
def data_url_from_png_bytes(b: bytes) -> str:
    """Convert PNG bytes to a data URL for OpenAI image input."""
    return "data:image/png;base64," + base64.b64encode(b).decode("utf-8")


def pdf_to_page_pngs(pdf_bytes: bytes, max_pages: int = 4, dpi: int = 200) -> list[bytes]:
    """Render first N PDF pages to PNG bytes."""
    images = []
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    pages = min(len(doc), max_pages)
    for i in range(pages):
        page = doc.load_page(i)
        mat = fitz.Matrix(dpi / 72.0, dpi / 72.0)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        images.append(pix.tobytes("png"))
    doc.close()
    return images


# ---- Prompt builders ----
def build_system_prompt() -> str:
    return (
        "You are a document extraction AI that parses veterinary clinic receipts "
        "and returns strict JSON output.\n\n"
        "Each receipt PDF includes three logical sections:\n"
        "1. A client information block (name, address, ZIP).\n"
        "2. A header block (invoice and receipt details, payment summary).\n"
        "3. A service table with columns: Patient, Provider, Description, Date, Quantity, "
        "Subtotal, Tax, and Total.\n\n"
        "Your task:\n"
        "• Identify and extract the client-level data.\n"
        "• Parse only valid service table rows (ignore header rows, 'Subtotal' or 'Tax' lines, "
        "and totals at the very bottom).\n"
        "• Group services by Patient name.\n"
        "• For each patient, calculate the numeric sum of their 'Total' column and include it "
        "as PatientTotal.\n"
        "• Return clean JSON only—no commentary, no markdown.\n\n"
        "All dates should remain as text exactly as shown (e.g. '10/6/2025').\n"
        "All monetary amounts should include a leading '$' and two decimals."
    )


def build_user_prompt() -> str:
    return (
        "Extract the following structured information from this veterinary clinic receipt PDF.\n\n"
        "For the client-level fields, include:\n"
        "- FirstName\n"
        "- LastName\n"
        "- StandardizedName (proper case full name)\n"
        "- ZipCode\n"
        "- GrantEligibility (based on ZIP: 14211 or 14215 = 'PFL'; 14208 = 'Incubator'; "
        "all others = 'Ineligible')\n"
        "- InvoiceDate\n"
        "- InvoiceNumber\n"
        "- ReceiptDate\n"
        "- ReceiptNumber\n"
        "- AmountPaid\n"
        "- Payment\n\n"
        "Then, from the 'Payment History' or similar service table, capture rows that contain:\n"
        "- Patient\n"
        "- Provider\n"
        "- Description\n"
        "- Date\n"
        "- Quantity\n"
        "- Total  ← (ignore Subtotal and Tax columns entirely)\n\n"
        "Group rows by Patient name and include, for each patient:\n"
        "- Name\n"
        "- Provider (use the main provider if repeated)\n"
        "- Items[] (list of their services)\n"
        "- PatientTotal (sum of all 'Total' values for that patient)\n\n"
        "Return one valid JSON object in the exact structure below:\n"
        "{\n"
        "  'Client': { ...fields... },\n"
        "  'Patients': [\n"
        "    {\n"
        "      'Name': '',\n"
        "      'Provider': '',\n"
        "      'PatientTotal': '',\n"
        "      'Items': [ { 'Description': '', 'Date': '', 'Quantity': '', 'Total': '' } ]\n"
        "    }\n"
        "  ]\n"
        "}\n\n"
        "If information is missing or illegible, use an empty string for that field."
    )


# ---- Endpoint ----
@app.post("/process")
async def process(req: Request, payload: ProcessPayload):
    # --- Auth check ---
    if SERVICE_API_KEY:
        incoming = req.headers.get("X-API-Key")
        if incoming != SERVICE_API_KEY:
            raise HTTPException(status_code=401, detail="Unauthorized")

    # --- Clamp page count ---
    payload.max_pages = min(payload.max_pages or 4, 4)

    # --- Decode PDF ---
    try:
        pdf_bytes = base64.b64decode(payload.fileBase64)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid base64: {e}")

    # --- Render PDF pages to PNGs ---
    try:
        png_pages = pdf_to_page_pngs(pdf_bytes, max_pages=payload.max_pages, dpi=220)
        if not png_pages:
            raise HTTPException(status_code=422, detail="Could not render PDF pages")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"PDF render failed: {e}")

    # --- Build messages for GPT ---
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

    # --- Send to OpenAI ---
    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            temperature=0,
            response_format={"type": "json_object"},
        )
        content = resp.choices[0].message.content or ""
        data = json.loads(content)
        return data
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"OpenAI error: {e}")
