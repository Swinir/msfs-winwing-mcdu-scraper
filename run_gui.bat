@echo off
REM MSFS A330 WinWing MCDU Scraper - GUI Launcher
REM This script activates the virtual environment and runs the GUI

echo ============================================================
echo MSFS A330 WinWing MCDU Scraper - GUI
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
    echo [INFO] config.yaml not found. Using default settings.
    echo You can create one by copying config.yaml.example
    echo.
)

REM Run the GUI
echo Starting MCDU Scraper GUI...
echo.
cd src
python gui.py

REM Deactivate virtual environment on exit
deactivate

pause
