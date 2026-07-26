FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    libxml2-dev \
    libxslt-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/
COPY migrations/ ./migrations/
COPY run.py .

RUN mkdir -p data logs

RUN useradd -m -u 1000 watcher && chown -R watcher:watcher /app
USER watcher

EXPOSE 8000

CMD ["python", "run.py"]
