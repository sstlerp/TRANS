FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /opt/trans-erp
RUN apt-get update && apt-get install -y --no-install-recommends default-mysql-client && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN useradd -r -u 1001 erp && mkdir -p /var/lib/trans-erp/storage /var/log/trans-erp && \
    chown -R erp /var/lib/trans-erp /var/log/trans-erp /opt/trans-erp
USER erp
EXPOSE 8000
# migrate, seed reference data (idempotent), then serve
CMD ["sh", "-c", "alembic upgrade head && python -m app.seed && uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4 --proxy-headers"]
