FROM python:3.11-alpine

# Install system dependencies
RUN apk add --no-cache \
    git \
    unrar \
    nodejs \
    build-base \
    libffi-dev \
    zlib-dev \
    jpeg-dev \
    curl

# Copy application code
WORKDIR /app/mylar
COPY . .

# Install Python dependencies
RUN pip3 install --no-cache-dir -r requirements.txt

# Volumes and ports
VOLUME /config /comics /manga /downloads
EXPOSE 8090

CMD ["python3", "/app/mylar/Mylar.py", "--nolaunch", "--quiet", "--datadir", "/config/mylar"]
