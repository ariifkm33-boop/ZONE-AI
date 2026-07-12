FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /data

EXPOSE 8000

CMD ["gunicorn", "ultimate_token_hunter:app", "--bind", "0.0.0.0:8000", "--timeout", "300", "--workers", "1", "--threads", "4", "--log-level", "info"]
