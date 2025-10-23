# Lightweight Python 3.12 gateway image (<= ~150MB)
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# System deps (ca-certificates for TLS, curl for debug)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Only runtime deps for gateway
RUN pip install --no-cache-dir fastapi uvicorn httpx

# Copy gateway
COPY gateway.py /app/gateway.py

EXPOSE 8080

CMD ["uvicorn", "gateway:app", "--host", "0.0.0.0", "--port", "8080"]
