FROM python:3.10-slim

# Install system dependencies (FFmpeg & ImageMagick)
RUN apt-get update && apt-get install -y \
    ffmpeg \
    imagemagick \
    git \
    && rm -rf /var/lib/apt-get/lists/*

# Dynamically patch ImageMagick policy (works for v6 and v7)
RUN POLICY_FILE=$(find /etc -name "policy.xml" | grep ImageMagick) && \
    sed -i 's/domain="path" rights="none" pattern="@\*"/domain="path" rights="read|write" pattern="@\*"/g' "$POLICY_FILE"

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD exec gunicorn --bind 0.0.0.0:$PORT --timeout 300 --workers 1 main:app
