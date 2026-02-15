#!/bin/bash
# MSFS A330 WinWing MCDU Scraper - Linux/Mac Launch Script
# This script activates the virtual environment and runs the scraper

echo "============================================================"
echo "MSFS A330 WinWing MCDU Scraper"
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
    echo "[WARNING] config.yaml not found!"
    echo "Please copy config.yaml.example to config.yaml and configure it."
    echo ""
    exit 1
fi

# Run the scraper
echo "Starting MCDU scraper..."
echo ""
cd src
python main.py

# Deactivate virtual environment on exit
deactivate
