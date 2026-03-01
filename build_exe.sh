#!/bin/bash
# Build Windows Executables Locally (on Linux/Mac with Wine)
# Note: This is mainly for reference. Windows builds work best on Windows.

echo "============================================================"
echo "MSFS MCDU Scraper - Build Executables"
echo "============================================================"
echo ""

# Check if pyinstaller is installed
if ! python -c "import PyInstaller" 2>/dev/null; then
    echo "[ERROR] PyInstaller not found!"
    echo "Installing PyInstaller..."
    pip install pyinstaller
fi

echo ""
echo "Building GUI executable..."
echo "----------------------------------------"
pyinstaller --clean gui.spec
if [ $? -ne 0 ]; then
    echo "[ERROR] GUI build failed!"
    exit 1
fi

echo ""
echo "Building CLI executable..."
echo "----------------------------------------"
pyinstaller --clean cli.spec
if [ $? -ne 0 ]; then
    echo "[ERROR] CLI build failed!"
    exit 1
fi

echo ""
echo "============================================================"
echo "Build Complete!"
echo "============================================================"
echo ""
echo "Executables created in dist/ folder:"
echo "  - MSFS-MCDU-Scraper-GUI.exe"
echo "  - MSFS-MCDU-Scraper-CLI.exe"
echo ""

# Create release package
echo "Creating release package..."
mkdir -p release
cp dist/MSFS-MCDU-Scraper-GUI.exe release/
cp dist/MSFS-MCDU-Scraper-CLI.exe release/
cp README.md release/
cp QUICKSTART.md release/
cp LICENSE release/
cp config.yaml.example release/

echo ""
echo "Release package created in release/ folder"
echo ""
