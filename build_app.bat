@echo off
REM =====================================================================
REM  Build script for "BOM Validator" Windows app (single-file .exe)
REM  آیکون: فایل app_icon.* یا web-data-scraping-icon-svg-download-png-3587064.*
REM  در همین پوشه باشد تا روی exe و پنجرهٔ برنامه نصب شود.
REM =====================================================================
setlocal
cd /d "%~dp0"

echo [1/4] Creating build environment...
if not exist .venv-build (
    python -m venv .venv-build
    if errorlevel 1 goto :error
)
call .venv-build\Scripts\activate.bat

echo [2/4] Installing dependencies...
python -m pip install --upgrade pip
if errorlevel 1 goto :error
pip install -r requirements.txt pyinstaller pillow
if errorlevel 1 goto :error

echo [3/4] Building exe (icon is detected automatically)...
pyinstaller app.spec --clean --noconfirm
if errorlevel 1 goto :error

echo [4/4] Done!
echo.
echo  Output:  dist\BOM Validator.exe
echo  Send ONLY this file to the customer (license_generator.py stays with you).
echo.
pause
exit /b 0

:error
echo.
echo  BUILD FAILED - see the messages above.
pause
exit /b 1
