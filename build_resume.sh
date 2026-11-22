#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
if command -v uv >/dev/null 2>&1; then
  PYTHON_CMD=(uv run)
elif command -v python3 >/dev/null 2>&1; then
  PYTHON_CMD=(python3)
elif command -v python >/dev/null 2>&1; then
  PYTHON_CMD=(python)
else
  echo "Python 3 was not found. Install Python 3.11 or newer and try again." >&2
  if [[ -t 0 ]]; then read -r -p "Press Enter to close..."; fi
  exit 1
fi
"${PYTHON_CMD[@]}" generate_resume.py --config config.yaml || {
  echo "Resume PDF generation failed. Install dependencies with: python3 -m pip install -e ." >&2
  if [[ -t 0 ]]; then read -r -p "Press Enter to close..."; fi
  exit 1
}
echo "Resume PDFs generated under: $(pwd)/resumes_output"
if [[ -t 0 ]]; then read -r -p "Press Enter to close..."; fi
