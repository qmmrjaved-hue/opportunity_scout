@echo off
cd /d "%~dp0"
if not exist venv\Scripts\python.exe (
    echo OpportunityScout is not installed yet. Double-click setup.bat first.
    pause
    exit /b 1
)
echo Starting OpportunityScout... your browser will open at http://localhost:8501
echo Keep this window open while you use the app. Close it to stop the app.
start "" cmd /c "timeout /t 5 >nul & start http://localhost:8501"
venv\Scripts\python.exe -m streamlit run app.py
pause
