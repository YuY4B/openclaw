@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8

echo ========================================
echo AI Content Factory - Master Controller
echo ========================================
echo.

REM Check Python installation
python --version >nul 2>&1
if errorlevel 1 (
    echo Error: Python is not installed or not in PATH
    pause
    exit /b 1
)

REM Check dependencies
echo Checking dependencies...
pip show requests >nul 2>&1
if errorlevel 1 (
    echo Installing dependencies...
    pip install -r requirements.txt
)

REM Check config
if not exist config.yaml (
    echo Error: config.yaml not found
    echo Please copy config.yaml.example to config.yaml and configure it
    pause
    exit /b 1
)

REM Set environment variables
set AZURE_API_KEY=your_api_key_here
set PROXY_001=http://user:pass@proxy1:port
set PROXY_002=http://user:pass@proxy2:port
set PROXY_003=http://user:pass@proxy3:port

REM Create output directories
if not exist output mkdir output
if not exist output\videos mkdir output\videos
if not exist logs mkdir logs

echo.
echo Starting Master Controller...
echo Press Ctrl+C to stop
echo.

REM Run the controller
python master_controller.py %*

if errorlevel 1 (
    echo.
    echo Error: Controller exited with error code %errorlevel%
    pause
)
