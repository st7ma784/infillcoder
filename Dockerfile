FROM python:3.11-slim

WORKDIR /app

# System deps for opencv headless
RUN apt-get update && apt-get install -y --no-install-recommends \
        libglib2.0-0 libgl1 \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps first (layer cache)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY core/   ./core/
COPY web/    ./web/

# Output directory for jobs (mount a volume here for persistence)
RUN mkdir -p /data

ENV INFILLCODE_DATA_DIR=/data

EXPOSE 8000

CMD ["uvicorn", "web.main:app", "--host", "0.0.0.0", "--port", "8000"]
