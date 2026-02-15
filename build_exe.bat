@echo off
REM Build Windows Executables Locally
REM This script builds both GUI and CLI executables using PyInstaller

echo ============================================================
echo MSFS MCDU Scraper - Build Executables
echo ============================================================
echo.

REM Check if pyinstaller is installed
python -c "import PyInstaller" 2>nul
if errorlevel 1 (
    echo [ERROR] PyInstaller not found!
    echo Installing PyInstaller...
    pip install pyinstaller
)

echo.
echo Building GUI executable...
echo ----------------------------------------
pyinstaller --clean gui.spec
if errorlevel 1 (
    echo [ERROR] GUI build failed!
    pause
    exit /b 1
)

echo.
echo Building CLI executable...
echo ----------------------------------------
pyinstaller --clean cli.spec
if errorlevel 1 (
    echo [ERROR] CLI build failed!
    pause
    exit /b 1
)

echo.
echo ============================================================
echo Build Complete!
echo ============================================================
echo.
echo Executables created in dist\ folder:
echo   - MSFS-MCDU-Scraper-GUI.exe
echo   - MSFS-MCDU-Scraper-CLI.exe
echo.

REM Create release package
echo Creating release package...
if not exist release mkdir release
xcopy /Y dist\MSFS-MCDU-Scraper-GUI.exe release\
xcopy /Y dist\MSFS-MCDU-Scraper-CLI.exe release\
xcopy /Y README.md release\
xcopy /Y QUICKSTART.md release\
xcopy /Y LICENSE release\
xcopy /Y config.yaml.example release\
xcopy /E /Y docs release\docs\

echo.
echo Release package created in release\ folder
echo.
pause
