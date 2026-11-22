@echo off
setlocal
cd /d "%~dp0"
echo Starting PayrollFlow local workbench...
python -m streamlit run app.py --server.address 127.0.0.1
if errorlevel 1 (
    echo.
    echo PayrollFlow failed to start. Check Python and requirements.txt.
    pause
)
endlocal
