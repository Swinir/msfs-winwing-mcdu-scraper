#!/bin/bash
# MSFS A330 WinWing MCDU Scraper - GUI Launcher (Linux/Mac)

echo "============================================================"
echo "MSFS A330 WinWing MCDU Scraper - GUI"
echo "============================================================"
echo ""

# Check if virtual environment exists
if [ ! -f "venv/bin/activate" ]; then
    echo "[ERROR] Virtual environment not found!"
    echo "Please run: python -m venv venv"
    echo "Then: pip install -r requirements.txt"
    exit 1
fi

# Activate virtual environment
echo "Activating virtual environment..."
source venv/bin/activate

# Check if config.yaml exists
if [ ! -f "config.yaml" ]; then
    echo ""
    echo "[INFO] config.yaml not found. Using default settings."
    echo "You can create one by copying config.yaml.example"
    echo ""
fi

# Run the GUI
echo "Starting MCDU Scraper GUI..."
echo ""
cd src
python gui.py

# Deactivate virtual environment on exit
deactivate
