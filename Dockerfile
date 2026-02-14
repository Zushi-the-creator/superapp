FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y gcc g++ curl && rm -rf /var/lib/apt/lists/*

# Copy only backend requirements and install
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn

RUN python -c "import nltk; nltk.download('vader_lexicon'); nltk.download('punkt')"

# Copy only the backend code
COPY backend/ .

RUN mkdir -p /app/data

EXPOSE 8000

CMD ["gunicorn", "main:app", "-w", "1", "-k", "uvicorn.workers.UvicornWorker", "--bind", "0.0.0.0:8000", "--timeout", "120"]
