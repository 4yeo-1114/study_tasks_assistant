FROM python:3.10-slim-bookworm

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY api.py ./
COPY web ./web
COPY agent ./agent
COPY llm ./llm
COPY tasks ./tasks
COPY knowledge ./knowledge
COPY storage ./storage
COPY core ./core
COPY frontend ./frontend
COPY alembic.ini ./
COPY migrations ./migrations

CMD ["python", "-m", "uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000"]
