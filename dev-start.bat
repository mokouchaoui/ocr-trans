@echo off
REM OCR Application Development Environment (Windows)

echo 🛠️ Starting OCR Application Development Environment...

REM Check if Docker is running
docker info >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Docker is not running. Please start Docker and try again.
    exit /b 1
)

echo [INFO] Docker is running ✓

REM Check if key.json exists
if not exist "key.json" (
    echo [WARNING] Google Cloud key.json file not found. Some features may not work.
    echo [INFO] You can continue development without it for basic testing.
)

REM Create necessary directories
echo [INFO] Creating necessary directories...
if not exist "uploads" mkdir uploads
if not exist "logs" mkdir logs
echo [SUCCESS] Directories created ✓

REM Stop existing containers
echo [INFO] Stopping existing containers...
docker-compose down --remove-orphans

REM Start development services
echo [INFO] Starting development services...
docker-compose --env-file .env.dev up -d --build

REM Wait for services
echo [INFO] Waiting for services to start...
timeout /t 20 /nobreak >nul

REM Check service health
echo [INFO] Checking service health...
docker-compose ps

REM Display service information
echo.
echo 📋 Development Environment Information:
echo - Application: http://localhost:8000
echo - API Documentation: http://localhost:8000/docs
echo - Interactive API: http://localhost:8000/redoc
echo - Health Check: http://localhost:8000/test/
echo.
echo 🔧 Development Commands:
echo - View logs: docker-compose logs -f
echo - View app logs: docker-compose logs -f ocr-app
echo - Stop services: docker-compose down
echo - Rebuild: docker-compose up -d --build
echo - Shell access: docker-compose exec ocr-app bash
echo.
echo 📁 Important directories:
echo - uploads/ - File uploads will be stored here
echo - logs/ - Application logs
echo - Modify code and it will auto-reload!
echo.
echo [SUCCESS] Development environment ready! 🎉

pause
