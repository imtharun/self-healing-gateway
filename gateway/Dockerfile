FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY gateway/requirements.txt ./gateway/requirements.txt
RUN pip install --no-cache-dir --requirement gateway/requirements.txt

COPY gateway ./gateway

RUN addgroup --system gateway \
    && adduser --system --ingroup gateway gateway \
    && chown -R gateway:gateway /app

USER gateway

EXPOSE 10000

CMD ["sh", "-c", "exec uvicorn gateway.app:app --host 0.0.0.0 --port ${PORT:-10000}"]
