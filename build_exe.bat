@echo off
echo ================================================
echo   RT Viewer EXE Builder
echo ================================================
echo.

:: Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found. Install from https://python.org
    pause & exit /b 1
)

:: Check Node
node --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Node.js not found. Install from https://nodejs.org
    pause & exit /b 1
)

echo [1/4] Installing Python dependencies...
pip install pyinstaller pystray pillow watchdog fastapi uvicorn numpy pydicom -q
if errorlevel 1 ( echo ERROR: pip install failed & pause & exit /b 1 )

echo [2/4] Building frontend production bundle...
cd frontend
call npm install --silent
call npm run build
if errorlevel 1 ( echo ERROR: npm build failed & pause & exit /b 1 )
cd ..

echo [3/4] Running PyInstaller...
pyinstaller launcher.spec --clean --noconfirm
if errorlevel 1 ( echo ERROR: PyInstaller failed & pause & exit /b 1 )

echo [4/4] Copying data files to dist...
if not exist "dist\RTViewer\dicom_data" mkdir "dist\RTViewer\dicom_data"
if not exist "dist\RTViewer\logs"       mkdir "dist\RTViewer\logs"

:: Copy the phantom test data if present
if exist "dicom_data\HN_PHANTOM_001" (
    xcopy /E /I /Y "dicom_data\HN_PHANTOM_001" "dist\RTViewer\dicom_data\HN_PHANTOM_001" >nul
    echo   Copied phantom test data.
)

echo.
echo ================================================
echo   Build complete!
echo   Output: dist\RTViewer\RTViewer.exe
echo   
echo   Double-click RTViewer.exe to start.
echo   The browser will open automatically.
echo ================================================
pause
