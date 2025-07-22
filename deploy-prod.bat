@echo off
REM OCR Application Deployment Script - Production (Windows)

echo 🚀 Starting OCR Application Production Deployment...

REM Check if Docker is running
docker info >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Docker is not running. Please start Docker and try again.
    exit /b 1
)

echo [INFO] Docker is running ✓

REM Check if docker-compose is available
docker-compose --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] docker-compose is not installed. Please install it first.
    exit /b 1
)

echo [INFO] docker-compose is available ✓

REM Check if .env.prod exists
if not exist ".env.prod" (
    echo [WARNING] .env.prod file not found. Please create it with your production settings.
    if exist ".env.prod.template" (
        copy ".env.prod.template" ".env.prod"
        echo [INFO] Created .env.prod from template
    ) else (
        echo [ERROR] Please create .env.prod file manually
        exit /b 1
    )
)

REM Check if key.json exists
if not exist "key.json" (
    echo [ERROR] Google Cloud key.json file not found. Please add your service account key.
    exit /b 1
)

echo [INFO] Configuration files found ✓

REM Create necessary directories
echo [INFO] Creating necessary directories...
if not exist "uploads" mkdir uploads
if not exist "logs" mkdir logs
if not exist "backup" mkdir backup
if not exist "ssl" mkdir ssl
echo [SUCCESS] Directories created ✓

REM Stop existing containers
echo [INFO] Stopping existing containers...
docker-compose -f docker-compose.prod.yml down --remove-orphans

REM Pull latest images
echo [INFO] Pulling latest base images...
docker-compose -f docker-compose.prod.yml pull mysql redis nginx

REM Build application image
echo [INFO] Building OCR application image...
docker-compose -f docker-compose.prod.yml build --no-cache ocr-app

REM Start services
echo [INFO] Starting production services...
docker-compose -f docker-compose.prod.yml --env-file .env.prod up -d

REM Wait for services to be healthy
echo [INFO] Waiting for services to be healthy...
timeout /t 30 /nobreak >nul

REM Check service health
echo [INFO] Checking service health...
docker-compose -f docker-compose.prod.yml ps

REM Test API endpoint
echo [INFO] Testing API endpoint...
timeout /t 10 /nobreak >nul
curl -f http://localhost/test/ >nul 2>&1
if %errorlevel% equ 0 (
    echo [SUCCESS] API is responding ✓
) else (
    echo [WARNING] API test failed. Check application logs.
)

REM Display service information
echo.
echo 📋 Service Information:
echo - Application: http://localhost
echo - Health Check: http://localhost/health
echo - API Documentation: http://localhost/docs
echo.
echo 🔧 Management Commands:
echo - View logs: docker-compose -f docker-compose.prod.yml logs -f
echo - Stop services: docker-compose -f docker-compose.prod.yml down
echo - Restart services: docker-compose -f docker-compose.prod.yml restart
echo - Scale app: docker-compose -f docker-compose.prod.yml up -d --scale ocr-app=3
echo.
echo [SUCCESS] Production deployment completed successfully! 🎉

pause
