import os
import base64
import fitz  # PyMuPDF
from typing import Optional

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

app = FastAPI(title="PDF to PNG Converter", version="1.2.0")

API_KEY = os.getenv("PDF_RENDER_API_KEY", "").strip()
MAX_PDF_BYTES = 15 * 1024 * 1024  # 15 MB


class ConvertRequest(BaseModel):
    fileBase64: str
    filename: Optional[str] = "document.pdf"
    max_pages: Optional[int] = 3
    format: Optional[str] = "png"
    dpi: Optional[int] = 150
    include_text: Optional[bool] = True
    text_max_chars: Optional[int] = 4000


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/convert")
def convert_pdf(
    req: ConvertRequest,
    x_api_key: Optional[str] = Header(default=None)
):
    if API_KEY:
        if not x_api_key or x_api_key != API_KEY:
            raise HTTPException(status_code=401, detail="Unauthorized")

    if not req.fileBase64:
        raise HTTPException(status_code=400, detail="fileBase64 is required")

    if (req.format or "png").lower() != "png":
        raise HTTPException(status_code=400, detail="Only png format is supported")

    max_pages = max(1, min(int(req.max_pages or 3), 3))
    dpi = max(72, min(int(req.dpi or 150), 300))
    include_text = bool(req.include_text)
    text_max_chars = max(200, min(int(req.text_max_chars or 4000), 20000))

    try:
        pdf_bytes = base64.b64decode(req.fileBase64, validate=True)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid base64 PDF payload")

    if not pdf_bytes:
        raise HTTPException(status_code=400, detail="Decoded PDF is empty")

    if len(pdf_bytes) > MAX_PDF_BYTES:
        raise HTTPException(status_code=413, detail="PDF exceeds maximum allowed size")

    safe_filename = (req.filename or "document.pdf").strip()[:200]

    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Unable to open PDF: {str(e)}")

    try:
        page_count = len(doc)
        pages_to_process = min(page_count, max_pages)

        zoom = dpi / 72.0
        matrix = fitz.Matrix(zoom, zoom)

        out_pages = []

        for i in range(pages_to_process):
            page = doc.load_page(i)

            pix = page.get_pixmap(matrix=matrix, alpha=False)
            png_bytes = pix.tobytes("png")
            png_b64 = base64.b64encode(png_bytes).decode("utf-8")

            text_snippet = ""
            if include_text:
                try:
                    text_snippet = page.get_text() or ""
                    text_snippet = text_snippet[:text_max_chars]
                except Exception:
                    text_snippet = ""

            out_pages.append({
                "page": i + 1,
                "filename": f"page_{i + 1}.png",
                "mimeType": "image/png",
                "base64": png_b64,
                "textSnippet": text_snippet
            })

        return {
            "ok": True,
            "filename": safe_filename,
            "page_count": page_count,
            "processed_pages": pages_to_process,
            "format": "png",
            "include_text": include_text,
            "pages": out_pages
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Conversion failed: {str(e)}")
    finally:
        doc.close()