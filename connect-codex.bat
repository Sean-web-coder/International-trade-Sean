@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 goto failed
if not exist ".venv\Scripts\python.exe" py -3 -m venv .venv
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -m pip install -r requirements-worker.txt
if errorlevel 1 goto failed
where codex >nul 2>nul
if errorlevel 1 (
  echo Install Node.js LTS, then run: npm install -g @openai/codex
  goto failed
)
call codex login status >nul 2>nul
if errorlevel 1 call codex login
if errorlevel 1 goto failed
".venv\Scripts\python.exe" worker.py
pause
exit /b 0
:failed
echo Install Python 3.10+, Node.js LTS and Codex CLI, then retry.
pause
exit /b 1
