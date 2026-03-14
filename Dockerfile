FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y gcc g++ curl && rm -rf /var/lib/apt/lists/*

# Use slim requirements (no langchain/chromadb/sentence-transformers)
COPY backend/requirements-prod.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt gunicorn

RUN python -c "import nltk; nltk.download('vader_lexicon'); nltk.download('punkt')"

# Copy backend code
COPY backend/ .

# Seed data: keep stock_cache.db at /app/seed/ for cold volume initialization
# On Fly.io, /app/data is a volume mount that starts empty on first deploy.
# This seeds it with the full 3000+ stock cache so scans work immediately.
RUN mkdir -p /app/seed && \
    cp data/stock_cache.db /app/seed/stock_cache.db 2>/dev/null || true

# Clean runtime data dir (volume mount will override /app/data)
RUN rm -rf data/*.db data/*.png data/*.csv data/*.json __pycache__ *.pyc

# Copy universe file to /app/ (outside Fly volume mount at /app/data)
RUN cp data/us_stock_universe.txt /app/us_stock_universe.txt 2>/dev/null || true

RUN mkdir -p /app/data

EXPOSE 8000

# Startup: seed volume if cold, then run uvicorn
CMD ["sh", "-c", "python3 startup.py && exec python3 -m uvicorn main:app --host 0.0.0.0 --port 8000 --timeout-keep-alive 600"]
