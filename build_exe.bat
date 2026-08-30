@echo off
REM Build FrameLabs.exe on Windows.
REM Run this from the repo root (double-click, or `build_exe.bat` in a cmd prompt).

setlocal

where python >nul 2>nul
if errorlevel 1 (
    echo Python was not found on PATH. Install Python 3.12+ from python.org and re-run.
    exit /b 1
)

if not exist venv (
    echo Creating virtual environment...
    python -m venv venv
)

call venv\Scripts\activate.bat

echo Installing FrameLabs and build dependencies...
pip install --upgrade pip
pip install -e .
pip install pyinstaller

echo Building FrameLabs.exe...
pyinstaller framelabs.spec --noconfirm

if errorlevel 1 (
    echo Build failed. Scroll up for the PyInstaller error.
    exit /b 1
)

echo.
echo Done. Your exe is at dist\FrameLabs\FrameLabs.exe
echo Copy the whole dist\FrameLabs folder when distributing -- the exe needs the files next to it.
endlocal
