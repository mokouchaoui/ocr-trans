#!/bin/bash

# OCR Application Deployment Script - Production

set -e

echo "🚀 Starting OCR Application Production Deployment..."

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to print colored output
print_status() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
    print_error "Docker is not running. Please start Docker and try again."
    exit 1
fi

print_status "Docker is running ✓"

# Check if docker-compose is available
if ! command -v docker-compose &> /dev/null; then
    print_error "docker-compose is not installed. Please install it first."
    exit 1
fi

print_status "docker-compose is available ✓"

# Check if .env.prod exists
if [ ! -f ".env.prod" ]; then
    print_warning ".env.prod file not found. Creating from template..."
    cp .env.prod.template .env.prod 2>/dev/null || {
        print_error "Please create .env.prod file with your production settings"
        exit 1
    }
fi

# Check if key.json exists
if [ ! -f "key.json" ]; then
    print_error "Google Cloud key.json file not found. Please add your service account key."
    exit 1
fi

print_status "Configuration files found ✓"

# Create necessary directories
print_status "Creating necessary directories..."
mkdir -p uploads logs backup ssl
print_success "Directories created ✓"

# Stop existing containers
print_status "Stopping existing containers..."
docker-compose -f docker-compose.prod.yml down --remove-orphans || true

# Pull latest images
print_status "Pulling latest base images..."
docker-compose -f docker-compose.prod.yml pull mysql redis nginx

# Build application image
print_status "Building OCR application image..."
docker-compose -f docker-compose.prod.yml build --no-cache ocr-app

# Start services
print_status "Starting production services..."
docker-compose -f docker-compose.prod.yml --env-file .env.prod up -d

# Wait for services to be healthy
print_status "Waiting for services to be healthy..."
sleep 30

# Check service health
print_status "Checking service health..."

services=("mysql-db" "redis" "ocr-app" "nginx")
for service in "${services[@]}"; do
    if docker-compose -f docker-compose.prod.yml ps | grep -q "$service.*healthy\|$service.*Up"; then
        print_success "$service is running ✓"
    else
        print_warning "$service might not be healthy. Check logs: docker-compose -f docker-compose.prod.yml logs $service"
    fi
done

# Test API endpoint
print_status "Testing API endpoint..."
sleep 10
if curl -f http://localhost/test/ > /dev/null 2>&1; then
    print_success "API is responding ✓"
else
    print_warning "API test failed. Check application logs."
fi

# Display service information
print_status "Deployment completed!"
echo
echo "📋 Service Information:"
echo "- Application: http://localhost"
echo "- Health Check: http://localhost/health"
echo "- API Documentation: http://localhost/docs"
echo
echo "🔧 Management Commands:"
echo "- View logs: docker-compose -f docker-compose.prod.yml logs -f"
echo "- Stop services: docker-compose -f docker-compose.prod.yml down"
echo "- Restart services: docker-compose -f docker-compose.prod.yml restart"
echo "- Scale app: docker-compose -f docker-compose.prod.yml up -d --scale ocr-app=3"
echo
echo "📊 Resource Usage:"
docker-compose -f docker-compose.prod.yml top
echo
print_success "Production deployment completed successfully! 🎉"
