@echo off
cd /d "%~dp0"
if not exist venv\Scripts\pythonw.exe (
    echo [ERROR] venv not found. Please run the setup steps in README.md first.
    pause
    exit /b 1
)
start "" venv\Scripts\pythonw.exe app.py
