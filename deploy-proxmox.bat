@echo off
REM Deployment script for Satisfactory Optimizer on Proxmox (Windows)

setlocal enabledelayedexpansion

echo.
echo Satisfactory Optimizer - Proxmox Deployment
echo ============================================
echo.

REM Configuration
set CONTAINER_NAME=satisfactory-optimizer
set PORT=5000
set WATCH_DIR=%USERPROFILE%\satisfactory-watch
set DATA_DIR=satisfactory-data
set REPO=https://github.com/schniti269/satisfactory_optimizer.git

echo Configuration:
echo   Container: %CONTAINER_NAME%
echo   Port: %PORT%
echo   Watch Dir: %WATCH_DIR%
echo   Data Dir: %DATA_DIR%
echo.

REM Step 1: Create watch directory
echo Creating watch directory...
if not exist "%WATCH_DIR%" mkdir "%WATCH_DIR%"
echo OK: %WATCH_DIR%

REM Step 2: Create data directory
echo Creating data directory...
if not exist "%DATA_DIR%" mkdir "%DATA_DIR%"
echo OK: %DATA_DIR%

REM Step 3: Build Docker image
echo.
echo Building Docker image...
docker build -t %CONTAINER_NAME%:latest .
if errorlevel 1 (
    echo ERROR: Failed to build Docker image
    exit /b 1
)
echo OK: Docker image built

REM Step 4: Stop existing container
echo.
echo Checking for existing container...
docker ps --filter "name=%CONTAINER_NAME%" --format "{{.Names}}" | findstr /r "^%CONTAINER_NAME%$" >nul
if %errorlevel% equ 0 (
    echo Stopping existing container...
    docker stop %CONTAINER_NAME%
    docker rm %CONTAINER_NAME%
)

REM Step 5: Start new container
echo.
echo Starting new container...
docker run -d ^
    --name %CONTAINER_NAME% ^
    -p %PORT%:5000 ^
    -v "%WATCH_DIR%":/app/watch:ro ^
    -v "%DATA_DIR%":/app/webapp ^
    -e FLASK_ENV=production ^
    -e WATCH_DIR=/app/watch ^
    --restart unless-stopped ^
    %CONTAINER_NAME%:latest

if errorlevel 1 (
    echo ERROR: Failed to start container
    exit /b 1
)
echo OK: Container started

REM Step 6: Display status
echo.
echo ============================================
echo Deployment Complete!
echo ============================================
echo.
echo Dashboard: http://localhost:%PORT%
echo Watch Dir: %WATCH_DIR%
echo.
echo Commands:
echo   View logs: docker logs -f %CONTAINER_NAME%
echo   Stop: docker stop %CONTAINER_NAME%
echo   Restart: docker restart %CONTAINER_NAME%
echo.
echo Next Steps:
echo 1. Copy your Satisfactory save file to: %WATCH_DIR%
echo 2. Open the dashboard in your browser
echo 3. The app will automatically detect and process the save file
echo.

REM Show container info
docker ps --filter "name=%CONTAINER_NAME%"

echo.
pause
