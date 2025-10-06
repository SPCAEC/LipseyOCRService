import base64, io, os, json
import fitz  # PyMuPDF
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel
from openai import OpenAI

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
SERVICE_API_KEY = os.getenv("SERVICE_API_KEY")  # shared secret with Apps Script
if not OPENAI_API_KEY:
    raise RuntimeError("OPENAI_API_KEY not set")

client = OpenAI(api_key=OPENAI_API_KEY)
app = FastAPI(title="Lipsey OCR Service")

# ---- Request model ----
class ProcessPayload(BaseModel):
    fileBase64: str                 # base64 of the PDF (no data: prefix)
    filename: str = "receipt.pdf"
    max_pages: int = 2              # process first N pages

def data_url_from_png_bytes(b: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(b).decode("utf-8")

def pdf_to_page_pngs(pdf_bytes: bytes, max_pages: int = 2, dpi: int = 200) -> list[bytes]:
    """Render first N PDF pages to PNG bytes."""
    images = []
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    pages = min(len(doc), max_pages)
    for i in range(pages):
        page = doc.load_page(i)
        mat = fitz.Matrix(dpi/72.0, dpi/72.0)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        images.append(pix.tobytes("png"))
    doc.close()
    return images

def build_prompt() -> str:
    return (
        "You are a structured data extractor for veterinary clinic receipts. "
        "You will receive one or more page images of a receipt. Extract the fields below "
        "and return ONLY a single valid JSON object (no commentary, no code fences):\n\n"
        "{\n"
        '  "FirstName": "",\n'
        '  "LastName": "",\n'
        '  "StandardizedName": "",\n'
        '  "ZipCode": "",\n'
        '  "GrantEligibility": "",\n'
        '  "InvoiceDate": "",\n'
        '  "InvoiceNumber": "",\n'
        '  "ReceiptDate": "",\n'
        '  "ReceiptNumber": "",\n'
        '  "AmountPaid": "",\n'
        '  "Payment": ""\n'
        "}\n\n"
        "Rules:\n"
        "- FirstName: first word in the first line of the Client block.\n"
        "- LastName: last word in that line.\n"
        '- StandardizedName: the same line in proper case (e.g., "Lusita Gains").\n'
        "- ZipCode: last 5 digits in the third line of the Client block.\n"
        '- GrantEligibility: 14211 or 14215 → "PFL"; 14208 → "Incubator"; else → "Ineligible".\n'
        '- InvoiceDate: the "Date" shown under "Invoice Number".\n'
        '- InvoiceNumber: the value labeled "Invoice Number".\n'
        '- ReceiptDate: the "Payment Entry Date".\n'
        '- ReceiptNumber: the "Receipt Number".\n'
        '- AmountPaid: the "Amount Paid" value.\n'
        '- Payment: the text following "Payment", e.g., "Pets for Life $140.32".\n'
        "Missing values should be empty strings."
    )

@app.post("/process")
async def process(req: Request, payload: ProcessPayload):
    # Simple shared-secret check (prevents public abuse)
    if SERVICE_API_KEY:
        incoming = req.headers.get("X-API-Key")
        if incoming != SERVICE_API_KEY:
            raise HTTPException(status_code=401, detail="Unauthorized")

    try:
        pdf_bytes = base64.b64decode(payload.fileBase64)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid base64")

    # PDF → first N page PNGs
    try:
        png_pages = pdf_to_page_pngs(pdf_bytes, max_pages=payload.max_pages, dpi=220)
        if not png_pages:
            raise HTTPException(status_code=422, detail="Could not render PDF pages")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"PDF render failed: {e}")

    # Build Chat Completions messages with data URLs for images
    messages = [
        {
            "role": "system",
            "content": "You are a precise, careful data extractor. Always return valid JSON."
        },
        {
            "role": "user",
            "content": [{"type": "text", "text": build_prompt()}] +
                       [{"type": "image_url", "image_url": {"url": data_url_from_png_bytes(p)}} for p in png_pages]
        }
    ]

    try:
        # Use vision-capable model and force JSON output
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            temperature=0,
            response_format={"type": "json_object"}
        )
        content = resp.choices[0].message.content or ""
        # Validate JSON
        data = json.loads(content)
        return data
    except Exception as e:
        # Return a useful error for Apps Script logs
        raise HTTPException(status_code=500, detail=f"OpenAI error: {e}")