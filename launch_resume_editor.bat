@echo off
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" main.py
) else if exist "%USERPROFILE%\.local\bin\uv.exe" (
  "%USERPROFILE%\.local\bin\uv.exe" run main.py
) else if exist "%LOCALAPPDATA%\uv\uv.exe" (
  "%LOCALAPPDATA%\uv\uv.exe" run main.py
) else (
  python main.py
)
