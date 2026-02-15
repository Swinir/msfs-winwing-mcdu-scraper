@echo off
REM MSFS A330 WinWing MCDU Scraper - Windows Launch Script
REM This script activates the virtual environment and runs the scraper

echo ============================================================
echo MSFS A330 WinWing MCDU Scraper
echo ============================================================
echo.

REM Check if virtual environment exists
if not exist "venv\Scripts\activate.bat" (
    echo [ERROR] Virtual environment not found!
    echo Please run: python -m venv venv
    echo Then: pip install -r requirements.txt
    pause
    exit /b 1
)

REM Activate virtual environment
echo Activating virtual environment...
call venv\Scripts\activate.bat

REM Check if config.yaml exists
if not exist "config.yaml" (
    echo.
    echo [WARNING] config.yaml not found!
    echo Please copy config.yaml.example to config.yaml and configure it.
    echo.
    pause
    exit /b 1
)

REM Run the scraper
echo Starting MCDU scraper...
echo.
cd src
python main.py

REM Deactivate virtual environment on exit
deactivate

pause
