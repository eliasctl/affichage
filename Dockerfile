FROM python:3.12-alpine

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p static/uploads static/icons static/videos data

# Déclarer les volumes persistants
# VOLUME ["/app/static/uploads", "/app/static/icons", "/app/static/videos", "/app/data"]

EXPOSE 8000
