FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATA_DIR=/data \
    PORT=8000 \
    LIVE=1
WORKDIR /app
COPY pyproject.toml README.md ./
COPY guardian ./guardian
COPY scenarios ./scenarios
COPY messages ./messages
COPY fixtures ./fixtures
RUN pip install --no-cache-dir . \
    && useradd --create-home --uid 10001 guardian \
    && mkdir -p /data \
    && chown guardian:guardian /data
USER guardian
EXPOSE 8000
CMD ["sh", "-c", "exec uvicorn guardian.app:app --host 0.0.0.0 --port \"$PORT\""]
