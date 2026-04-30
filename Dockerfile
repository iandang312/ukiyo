FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY pyproject.toml ./
COPY backend/ukiyo_service ./backend/ukiyo_service
COPY alembic.ini ./
COPY alembic ./alembic
COPY scripts ./scripts
COPY data ./data
COPY app.py ./

RUN pip install --upgrade pip && pip install .

EXPOSE 8000

CMD ["sh", "-c", "alembic upgrade head && uvicorn app:app --host 0.0.0.0 --port 8000"]
