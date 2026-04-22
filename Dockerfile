FROM python:3.12-alpine

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p static/uploads static/icons static/videos data

EXPOSE 8000

HEALTHCHECK --interval=60s --timeout=3s --retries=2 \
  CMD wget -q --spider http://localhost:8000/api/hash || exit 1

CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "2", "--threads", "4", "--timeout", "120", "--preload", "app:app"]
