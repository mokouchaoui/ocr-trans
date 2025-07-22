#!/bin/bash

# Build script for Custom OCR C Library
echo "🔨 Building Custom OCR C Library..."

# Check if make is available
if ! command -v make &> /dev/null; then
    echo "❌ make command not found. Installing build-essential..."
    apt-get update && apt-get install -y build-essential
fi

# Check if Tesseract development libraries are available
if ! pkg-config --exists tesseract; then
    echo "❌ Tesseract development libraries not found. Installing..."
    apt-get update && apt-get install -y tesseract-ocr libtesseract-dev libleptonica-dev
fi

# Build the OCR library
echo "🔧 Compiling OCR library..."
make clean
make

# Check if build was successful
if [ -f "libcustom_ocr.so" ]; then
    echo "✅ OCR library built successfully!"
    
    # Copy to system library path for easier access
    cp libcustom_ocr.so /usr/local/lib/
    
    # Update library cache
    ldconfig
    
    echo "📦 OCR library installed to /usr/local/lib/"
else
    echo "❌ OCR library build failed!"
    exit 1
fi

# Test the library
echo "🧪 Testing OCR library..."
if [ -f "test_ocr" ]; then
    echo "Running OCR test..."
    ./test_ocr
else
    echo "⚠️ OCR test binary not found. Build may be incomplete."
fi

echo "🎉 OCR build process completed!"
