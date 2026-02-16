@echo off
REM Build Windows Executables Locally using the GitHub Actions method

echo ============================================================
echo MSFS MCDU Scraper - Build Executables (GitHub Actions Method)
echo ============================================================
echo.

REM Check if PyInstaller is installed
venv\Scripts\python.exe -c "import PyInstaller" 2>nul
if errorlevel 1 (
    echo [ERROR] PyInstaller not found!
    echo Installing PyInstaller...
    venv\Scripts\pip.exe install pyinstaller
)

REM Clean previous builds
if exist dist rmdir /s /q dist
if exist build rmdir /s /q build

echo.
echo Building GUI executable...
echo ----------------------------------------
venv\Scripts\pyinstaller --name "MSFS-MCDU-Scraper-GUI" ^
    --onefile ^
    --windowed ^
    --icon=NONE ^
    --paths src ^
    --add-data "config.yaml.example;." ^
    --add-data "docs;docs" ^
    --hidden-import=PIL ^
    --hidden-import=PIL._tkinter_finder ^
    --hidden-import=numpy ^
    --hidden-import=cv2 ^
    --hidden-import=yaml ^
    --hidden-import=win32gui ^
    --hidden-import=win32ui ^
    --hidden-import=win32con ^
    --hidden-import=win32api ^
    --collect-all pytesseract ^
    src/gui.py

if errorlevel 1 (
    echo [ERROR] GUI build failed!
    pause
    exit /b 1
)

echo.
echo Building CLI executable...
echo ----------------------------------------
venv\Scripts\pyinstaller --name "MSFS-MCDU-Scraper-CLI" ^
    --onefile ^
    --console ^
    --icon=NONE ^
    --paths src ^
    --add-data "config.yaml.example;." ^
    --hidden-import=PIL ^
    --hidden-import=numpy ^
    --hidden-import=cv2 ^
    --hidden-import=yaml ^
    --collect-all pytesseract ^
    src/main.py
    
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
echo Executables created in dist\ folder.
echo.

REM Create release package (optional)
set /p create_release="Create release package (y/n)? "
if /i "%create_release%"=="y" (
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
)

echo.
pause

