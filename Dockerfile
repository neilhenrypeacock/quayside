FROM python:3.11-slim

WORKDIR /app

# Copy everything first (source needed for editable-style install)
COPY . .

# Install dependencies
RUN pip install --no-cache-dir .

# Create data directory for SQLite
RUN mkdir -p /data

ENV QUAYSIDE_DB_PATH=/data/quayside.db

EXPOSE 8080

CMD ["python", "-m", "gunicorn", "--bind", "0.0.0.0:8080", "--workers", "2", "quayside.web.app:create_app()"]
