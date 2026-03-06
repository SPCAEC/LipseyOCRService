
# PDF → PNG Render Service

A lightweight FastAPI microservice that converts uploaded PDF files into PNG images and optionally extracts text snippets from each page.

This service supports automated document processing workflows where PDFs must be rendered into images before AI or OCR processing.

---

## Features

- Converts PDF pages to PNG images
- Limits processing to the first 3 pages for safety
- Optional text extraction from each page
- API key authentication
- File size protection
- Clean JSON response format
- Designed to integrate with Google Apps Script or automation pipelines

---

## Endpoints

### Health Check

GET /health

Response:
{
  "ok": true
}

---

### Convert PDF to PNG

POST /convert

Headers:
X-API-Key: <PDF_RENDER_API_KEY>
Content-Type: application/json

Request body example:
{
  "fileBase64": "<base64 encoded pdf>",
  "filename": "document.pdf",
  "max_pages": 3,
  "format": "png",
  "dpi": 150,
  "include_text": true,
  "text_max_chars": 4000
}

---

## Request Fields

fileBase64 — Base64 encoded PDF file  
filename — Optional original filename  
max_pages — Maximum pages to render (max 3)  
format — Output format (PNG only)  
dpi — Render resolution  
include_text — Extract text snippets  
text_max_chars — Maximum characters of extracted text  

---

## Response Example

{
  "ok": true,
  "filename": "document.pdf",
  "page_count": 2,
  "processed_pages": 2,
  "format": "png",
  "include_text": true,
  "pages": [
    {
      "page": 1,
      "filename": "page_1.png",
      "mimeType": "image/png",
      "base64": "<base64 png>",
      "textSnippet": "text extracted from page..."
    }
  ]
}

---

## Security

Requests must include the header:

X-API-Key: <PDF_RENDER_API_KEY>

The key is stored as a Render environment variable.

---

## Limits and Safeguards

Maximum PDF size: 15 MB  
Maximum pages rendered: 3  
DPI range: 72 – 300  
Text snippet length: up to 20,000 characters  

---

## Deployment (Render)

render.yaml

services:
  - type: web
    name: pdf-to-png-service
    runtime: python
    plan: starter
    buildCommand: pip install -r requirements.txt
    startCommand: uvicorn app:app --host 0.0.0.0 --port $PORT
    envVars:
      - key: PYTHON_VERSION
        value: "3.11.10"
      - key: PDF_RENDER_API_KEY
        sync: false

---

## Dependencies

fastapi
uvicorn
pydantic
PyMuPDF

Defined in requirements.txt

---

## Local Development

Install dependencies:

pip install -r requirements.txt

Run locally:

uvicorn app:app --reload

Service will start at:
http://localhost:8000

Health endpoint:
http://localhost:8000/health

---

## Typical Workflow

1. Client uploads PDF
2. Client converts PDF to Base64
3. Client calls /convert
4. Service renders pages to PNG
5. PNG images and text snippets returned
6. Client processes images with AI or OCR

Typical pipeline:

PDF → Image → AI extraction → structured data

---

## License

Internal utility service.
