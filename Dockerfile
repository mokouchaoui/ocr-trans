# Multi-stage build for optimized production image
FROM python:3.11-slim as base

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive \
    TZ=Europe/Paris \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8

# Install system dependencies
RUN apt-get update && apt-get install -y \
    # Core system packages
    wget \
    curl \
    gnupg2 \
    lsb-release \
    software-properties-common \
    apt-transport-https \
    ca-certificates \
    # Build dependencies
    build-essential \
    gcc \
    g++ \
    make \
    cmake \
    pkg-config \
    # OCR dependencies (Tesseract)
    tesseract-ocr \
    tesseract-ocr-eng \
    tesseract-ocr-fra \
    libtesseract-dev \
    libleptonica-dev \
    # Image processing libraries
    libopencv-dev \
    python3-opencv \
    # Poppler for PDF processing
    poppler-utils \
    libpoppler-cpp-dev \
    # Image libraries
    libjpeg-dev \
    libpng-dev \
    libtiff-dev \
    libwebp-dev \
    # Font libraries
    fontconfig \
    fonts-dejavu-core \
    fonts-liberation \
    # Other utilities
    git \
    unzip \
    && rm -rf /var/lib/apt/lists/*

# Create app user
RUN useradd --create-home --shell /bin/bash app && \
    mkdir -p /app /app/static /app/templates /app/uploads /app/logs && \
    chown -R app:app /app

# Set work directory
WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt /app/
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r requirements.txt

# Development stage
FROM base as development

# Install development dependencies
RUN pip install --no-cache-dir \
    pytest \
    pytest-asyncio \
    pytest-cov \
    black \
    flake8 \
    mypy \
    jupyterlab \
    ipython

# Copy application code
COPY --chown=app:app . /app/

# Build custom OCR C library
RUN chmod +x /app/build_ocr.sh && \
    cd /app && \
    make clean && \
    make && \
    cp libcustom_ocr.so /usr/local/lib/ && \
    ldconfig

# Create necessary directories and set permissions
RUN mkdir -p /app/static/css /app/static/js /app/static/images && \
    mkdir -p /app/templates && \
    mkdir -p /app/uploads && \
    mkdir -p /app/logs && \
    chmod +x /app/entrypoint.sh || true && \
    chown -R app:app /app

# Switch to app user
USER app

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=30s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/test/ || exit 1

# Default command
CMD ["uvicorn", "full:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

# Production stage
FROM base as production

# Copy only necessary files
COPY --chown=app:app full.py /app/
COPY --chown=app:app static/ /app/static/
COPY --chown=app:app templates/ /app/templates/

# Create production directories
RUN mkdir -p /app/logs /app/uploads && \
    chown -R app:app /app

# Switch to app user
USER app

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=60s --timeout=30s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/test/ || exit 1

# Production command
CMD ["uvicorn", "full:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]

# Testing stage
FROM development as testing

# Install additional testing tools
USER root
RUN pip install --no-cache-dir \
    locust \
    selenium \
    requests-mock

USER app

# Copy test files if they exist
RUN mkdir -p /app/tests/

# Run tests by default
CMD ["pytest", "-v", "--cov=.", "--cov-report=html"]
