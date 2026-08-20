FROM python:3.11-slim

RUN apt-get update && apt-get install -y \
    chromium \
    fonts-noto-color-emoji \
    fonts-unifont \
    libx11-xcb1 \
    libxkbcommon0 \
    libxcb1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Install Playwright browsers
RUN playwright install chromium

ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
ENV SCRAPER_CONFIG_DIR=/app/configs

EXPOSE 8000

# Flask app (deviation from spec: gunicorn/Flask instead of uvicorn/FastAPI)
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "2", "--timeout", "120", "app.main:app"]