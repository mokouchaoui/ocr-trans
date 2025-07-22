# Makefile for OCR C library
CC = gcc
CXX = g++
CFLAGS = -Wall -Wextra -O2 -fPIC
CXXFLAGS = -Wall -Wextra -O2 -fPIC -std=c++11
LDFLAGS = -shared

# Include directories
INCLUDES = -I/usr/include/tesseract -I/usr/include/leptonica

# Libraries
LIBS = -ltesseract -lleptonica

# Source files
SOURCES = ocr.c
TARGET_LIB = libocr.so
TARGET_EXE = ocr_cli

# Default target
all: $(TARGET_LIB) $(TARGET_EXE)

# Shared library for Python integration
$(TARGET_LIB): $(SOURCES)
	$(CXX) $(CXXFLAGS) $(INCLUDES) $(LDFLAGS) -o $@ $^ $(LIBS)

# Command line executable
$(TARGET_EXE): $(SOURCES)
	$(CXX) $(CXXFLAGS) $(INCLUDES) -o $@ $^ $(LIBS)

# Install dependencies (Ubuntu/Debian)
install-deps:
	sudo apt-get update
	sudo apt-get install -y \
		tesseract-ocr \
		tesseract-ocr-dev \
		libtesseract-dev \
		libleptonica-dev \
		tesseract-ocr-fra \
		tesseract-ocr-eng \
		tesseract-ocr-ara \
		build-essential \
		pkg-config

# Install dependencies (CentOS/RHEL)
install-deps-centos:
	sudo yum install -y epel-release
	sudo yum install -y \
		tesseract \
		tesseract-devel \
		leptonica-devel \
		tesseract-langpack-fra \
		tesseract-langpack-eng \
		gcc-c++ \
		make \
		pkgconfig

# Install dependencies (macOS with Homebrew)
install-deps-mac:
	brew install tesseract leptonica
	brew install tesseract-lang

# Windows build (requires MSYS2/MinGW)
windows:
	pacman -S mingw-w64-x86_64-tesseract-ocr
	pacman -S mingw-w64-x86_64-leptonica
	$(CXX) $(CXXFLAGS) -I/mingw64/include/tesseract -I/mingw64/include/leptonica \
		-L/mingw64/lib -o ocr_cli.exe $(SOURCES) -ltesseract -lleptonica

# Clean build files
clean:
	rm -f $(TARGET_LIB) $(TARGET_EXE) *.o

# Test the OCR
test: $(TARGET_EXE)
	@echo "Testing OCR with sample image..."
	@if [ -f "test_image.png" ]; then \
		./$(TARGET_EXE) test_image.png fra+eng; \
	else \
		echo "No test image found. Place a test image as 'test_image.png'"; \
	fi

# Create a test image with text (requires ImageMagick)
create-test:
	convert -size 800x200 xc:white -font Arial -pointsize 24 -fill black \
		-annotate +50+100 "FACTURE N° FA009421\nDate: 15/06/2024\nMontant TTC: 180.894,20 EUR" \
		test_image.png

# Docker build environment
docker-build:
	docker build -t ocr-builder -f Dockerfile.ocr .
	docker run --rm -v $(PWD):/workspace ocr-builder make

# Performance test
benchmark: $(TARGET_EXE)
	@echo "Running OCR benchmark..."
	@time ./$(TARGET_EXE) test_image.png fra+eng > /dev/null

# Memory check (requires valgrind)
memcheck: $(TARGET_EXE)
	valgrind --leak-check=full --show-leak-kinds=all ./$(TARGET_EXE) test_image.png

# Code formatting
format:
	clang-format -i *.c *.h

# Static analysis
analyze:
	cppcheck --enable=all --std=c++11 $(SOURCES)

# Documentation
docs:
	doxygen Doxyfile

.PHONY: all clean test install-deps install-deps-centos install-deps-mac windows create-test docker-build benchmark memcheck format analyze docs
