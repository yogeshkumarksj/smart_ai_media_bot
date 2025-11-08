# Use Python slim
FROM python:3.11-slim

ENV DEBIAN_FRONTEND=noninteractive

# Install system deps (ffmpeg + deps for browser-cookie3 if needed)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      ffmpeg \
      libnss3 \
      libxss1 \
      fonts-liberation \
      wget \
      curl \
      ca-certificates \
      tzdata && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY . /app

# Create empty cookies file (Netscape header) to avoid yt-dlp warnings
RUN echo "# Netscape HTTP Cookie File" > /app/cookies.txt || true

# Install python deps
RUN pip install --no-cache-dir -r requirements.txt

EXPOSE 10000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "10000"]
