# Lipsey OCR Service

FastAPI service that converts PDF receipts to images and extracts structured fields with GPT (gpt-4o-mini).

## Run locally
pip install -r requirements.txt
export OPENAI_API_KEY=...
export SERVICE_API_KEY=dev-secret
uvicorn app:app --reload

POST /process
{
  "fileBase64": "<base64-pdf>",
  "filename": "receipt.pdf",
  "max_pages": 2
}
Headers: X-API-Key: <SERVICE_API_KEY>