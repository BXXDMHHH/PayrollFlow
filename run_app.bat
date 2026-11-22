@echo off
setlocal
cd /d "%~dp0"
echo Starting PayrollFlow local workbench...
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -m streamlit run app.py --server.address 127.0.0.1
) else (
    python -m streamlit run app.py --server.address 127.0.0.1
)
if errorlevel 1 (
    echo.
    echo PayrollFlow failed to start. Check Python and requirements.txt.
    pause
)
endlocal
