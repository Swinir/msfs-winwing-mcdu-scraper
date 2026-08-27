@echo off
REM Build Windows Executables Locally using the GitHub Actions method

echo ============================================================
echo MSFS MCDU Scraper - Build Executables (GitHub Actions Method)
echo ============================================================
echo.

REM Install the same runtime and build dependencies used by GitHub Actions.
echo Installing dependencies...
venv\Scripts\python.exe -m pip install --upgrade pip
if errorlevel 1 (
    echo [ERROR] Failed to upgrade pip!
    pause
    exit /b 1
)

venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 (
    echo [ERROR] Failed to install runtime dependencies!
    pause
    exit /b 1
)

venv\Scripts\python.exe -m pip install -r requirements-dev.txt
if errorlevel 1 (
    echo [ERROR] Failed to install build dependencies!
    pause
    exit /b 1
)

REM Clean previous builds
if exist dist rmdir /s /q dist
if exist build rmdir /s /q build

echo.
echo Building GUI executable...
echo ----------------------------------------
venv\Scripts\python.exe -m PyInstaller --name "MSFS-CDU-Scraper-GUI" ^
    --onefile ^
    --windowed ^
    --icon=NONE ^
    --paths src ^
    --add-data "config.yaml.example;." ^
    --hidden-import=numpy ^
    --hidden-import=cv2 ^
    --hidden-import=yaml ^
    --hidden-import=win32gui ^
    --hidden-import=win32ui ^
    --hidden-import=win32con ^
    --hidden-import=win32api ^
    --hidden-import=windows_capture ^
    --exclude-module=tkinter ^
    --exclude-module=PyQt5 ^
    --exclude-module=PyQt6 ^
    src/gui.py

if errorlevel 1 (
    echo [ERROR] GUI build failed!
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
    xcopy /Y dist\MSFS-CDU-Scraper-GUI.exe release\
    xcopy /Y README.md release\
    xcopy /Y QUICKSTART.md release\
    xcopy /Y LICENSE release\
    xcopy /Y config.yaml.example release\
    echo.
    echo Release package created in release\ folder
)

echo.
pause

