# Jezero Marswalk routing API - Google Cloud Run (1 GiB, 1 CPU, min instances 0)
FROM python:3.10-slim
# rasterio needs libexpat at runtime; python:3.10-slim does not ship it
RUN apt-get update -qq && apt-get install -y --no-install-recommends libexpat1 \
    && rm -rf /var/lib/apt/lists/*
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8080
WORKDIR /app
COPY requirements.txt api/requirements-api.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-api.txt
COPY routing/ routing/
COPY api/ api/
COPY data/grid5m_jezero_crop/ data/grid5m_jezero_crop/
COPY outputs/ outputs/
EXPOSE 8080
CMD ["sh", "-c", "uvicorn api.main:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*'"]
