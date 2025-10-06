# ---- Base image ----
FROM python:3.11-slim

# ---- Install system dependencies needed by PyMuPDF ----
RUN apt-get update && apt-get install -y \
    build-essential \
    libmupdf-dev \
    libjpeg-dev \
    zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

# ---- Set up working dir ----
WORKDIR /app
COPY requirements.txt .

# ---- Install Python deps ----
RUN pip install --no-cache-dir -r requirements.txt

# ---- Copy app code ----
COPY . .

# ---- Run ----
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]