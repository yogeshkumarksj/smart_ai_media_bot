# ---------------------------
# Stage 1: Builder
# ---------------------------
FROM python:3.11-slim AS builder

ARG DEBIAN_FRONTEND=noninteractive

# Install system dependencies (Playwright + FFmpeg)
RUN apt-get update && apt-get install -y \
    wget \
    gnupg \
    ca-certificates \
    libnss3 \
    libatk-bridge2.0-0 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxrandr2 \
    libgbm1 \
    libxss1 \
    libasound2 \
    fonts-liberation \
    libnspr4 \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright browsers
RUN playwright install chromium

# ---------------------------
# Stage 2: Production Image
# ---------------------------
FROM python:3.11-slim

WORKDIR /app

# Copy Python environment
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy application code
COPY . .

# Expose port
EXPOSE 10000

# Run with Gunicorn + Uvicorn worker (FastAPI/ASGI compatible)
CMD ["gunicorn", "main:app", "-k", "uvicorn.workers.UvicornWorker", "--bind", "0.0.0.0:10000"]

