@echo off
setlocal
cd /d "%~dp0"
where uv >nul 2>nul
if not errorlevel 1 (
  uv run generate_resume.py --config config.yaml
  if errorlevel 1 goto :failed
  goto :success
)
set "PYTHON_CMD="
where python >nul 2>nul && set "PYTHON_CMD=python"
if not defined PYTHON_CMD (
  where py >nul 2>nul && set "PYTHON_CMD=py -3"
)
if not defined PYTHON_CMD (
  echo Python 3 was not found. Install Python 3.11 or newer and try again.
  set "EXIT_CODE=1"
  goto :finish
)
%PYTHON_CMD% generate_resume.py --config config.yaml
if errorlevel 1 goto :failed

:success
echo Resume PDFs generated under: %CD%\resumes_output
set "EXIT_CODE=0"
goto :finish

:failed
echo Resume PDF generation failed. Install dependencies with: python -m pip install -e .
set "EXIT_CODE=1"

:finish
echo.
pause
exit /b %EXIT_CODE%
