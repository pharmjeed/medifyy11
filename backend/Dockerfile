# Medify backend — FastAPI + Python 3.12 (DOC-07 §١)
FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

COPY pyproject.toml ./
COPY app ./app
COPY alembic.ini ./
COPY alembic ./alembic

RUN pip install --no-cache-dir .

# faster-whisper اختيارية — تُثبت عند STT_ENGINE=whisper (ثقيلة)
ARG INSTALL_WHISPER=false
RUN if [ "$INSTALL_WHISPER" = "true" ]; then pip install --no-cache-dir "faster-whisper>=1.0"; fi

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
