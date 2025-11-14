# -----------------------------
# Base image
# -----------------------------
FROM python:3.11-slim

# Avoid prompts during install
ENV DEBIAN_FRONTEND=noninteractive

# -----------------------------
# Install system dependencies
# -----------------------------
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        ffmpeg \
        curl \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# -----------------------------
# Set work directory
# -----------------------------
WORKDIR /app

# -----------------------------
# Copy project files
# -----------------------------
COPY . /app

# -----------------------------
# Install Python dependencies
# -----------------------------
RUN pip install --no-cache-dir -r requirements.txt

# -----------------------------
# Environment variables
# -----------------------------
ENV PYTHONUNBUFFERED=1
ENV BOT_TOKEN=${BOT_TOKEN}

# -----------------------------
# Expose FastAPI Port
# -----------------------------
EXPOSE 8000

# -----------------------------
# Start server
# -----------------------------
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
