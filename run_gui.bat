@echo off
cd /d "%~dp0"
if not exist venv\Scripts\pythonw.exe (
    echo venv가 없습니다. 먼저 README의 설치 안내를 따라주세요.
    pause
    exit /b 1
)
start "" venv\Scripts\pythonw.exe app.py
