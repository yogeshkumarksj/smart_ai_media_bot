FROM python:3.11-slim

# System Updates
RUN apt-get update && apt-get install -y \
    ffmpeg \
    wget \
    curl \
    unzip \
    chromium \
    chromium-driver \
    && apt-get clean

# Install yt-dlp
RUN pip install --upgrade pip
RUN pip install yt-dlp python-telegram-bot aiohttp httpx fastapi uvicorn gunicorn

# Create app folder
WORKDIR /app
COPY . .

# Expose port
EXPOSE 10000

CMD ["gunicorn", "main:app", "--workers", "1", "--worker-class", "uvicorn.workers.UvicornWorker", "--bind", "0.0.0.0:10000"]
