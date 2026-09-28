@echo off
setlocal
cd /d "%~dp0"
echo ==================================================
echo   OpportunityScout - one-time setup (Windows)
echo ==================================================
echo.

where python >nul 2>nul
if errorlevel 1 goto :nopython
python -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)"
if errorlevel 1 goto :oldpython

if exist venv\Scripts\python.exe (
    echo [1/4] Virtual environment already exists.
) else (
    echo [1/4] Creating virtual environment...
    python -m venv venv
    if errorlevel 1 goto :fail
)

echo [2/4] Installing Python packages - this can take a few minutes...
venv\Scripts\python.exe -m pip install --upgrade pip --quiet
venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 goto :fail

echo [3/4] Installing the headless browser (Chromium)...
venv\Scripts\python.exe -m playwright install chromium
if errorlevel 1 goto :fail

echo [4/4] Gemini API key
if not exist .env goto :askkey
findstr /c:"your_gemini_api_key_here" .env >nul
if errorlevel 1 (
    echo       Existing key found in .env - keeping it.
    goto :done
)

:askkey
echo       Get a free key at https://aistudio.google.com/apikey
set "GEMINI_KEY="
set /p "GEMINI_KEY=      Paste your key and press Enter (or just press Enter to add it later): "
if "%GEMINI_KEY%"=="" (
    copy /y .env.example .env >nul
    echo       No key entered. Add it later by editing the .env file.
) else (
    > .env echo GEMINI_API_KEY=%GEMINI_KEY%
    echo       Key saved to .env
)

:done
echo.
echo ==================================================
echo   Setup complete!  Double-click start.bat to run.
echo ==================================================
pause
exit /b 0

:nopython
echo [ERROR] Python was not found.
echo         Install Python 3.10 or newer from https://www.python.org/downloads/
echo         and tick "Add python.exe to PATH" during installation. Then run setup.bat again.
pause
exit /b 1

:oldpython
echo [ERROR] Python 3.10 or newer is required. You have:
python --version
pause
exit /b 1

:fail
echo.
echo [ERROR] Setup failed - see the messages above. Check your internet connection and try again.
pause
exit /b 1
