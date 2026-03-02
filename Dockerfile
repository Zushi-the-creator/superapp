FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y gcc g++ curl && rm -rf /var/lib/apt/lists/*

# Use slim requirements (no langchain/chromadb/sentence-transformers)
COPY backend/requirements-prod.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt gunicorn

RUN python -c "import nltk; nltk.download('vader_lexicon'); nltk.download('punkt')"

# Copy backend code but NOT data files (they live on Fly.io volume)
COPY backend/ .
RUN rm -rf data/*.db data/*.png data/*.csv data/*.json __pycache__ *.pyc

RUN mkdir -p /app/data

EXPOSE 8000

CMD ["gunicorn", "main:app", "-w", "1", "-k", "uvicorn.workers.UvicornWorker", "--bind", "0.0.0.0:8000", "--timeout", "300"]
