import os
import io
import base64
import tempfile
from typing import Optional

import fitz  # PyMuPDF
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

app = FastAPI(title="PDF to PNG Converter", version="1.0.0")

API_KEY = os.getenv("PDF_RENDER_API_KEY", "").strip()


class ConvertRequest(BaseModel):
    fileBase64: str
    filename: Optional[str] = "document.pdf"
    max_pages: Optional[int] = 3
    format: Optional[str] = "png"
    dpi: Optional[int] = 150


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

    try:
        pdf_bytes = base64.b64decode(req.fileBase64)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid base64 PDF payload")

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

            out_pages.append({
                "page": i + 1,
                "filename": f"page_{i + 1}.png",
                "mimeType": "image/png",
                "base64": png_b64
            })

        return {
            "ok": True,
            "filename": req.filename,
            "page_count": page_count,
            "processed_pages": pages_to_process,
            "format": "png",
            "pages": out_pages
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Conversion failed: {str(e)}")
    finally:
        doc.close()
