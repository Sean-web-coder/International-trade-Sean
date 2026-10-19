@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 (
  echo Install Python 3.10+ from python.org with the Python launcher enabled.
  pause
  exit /b 1
)
if not exist ".venv\Scripts\python.exe" py -3 -m venv .venv
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto failed
where codex >nul 2>nul
if errorlevel 1 (
  echo Install Node.js LTS, then run: npm install -g @openai/codex
  pause
  exit /b 1
)
call codex login status >nul 2>nul
if errorlevel 1 (
  call codex login
  if errorlevel 1 goto failed
)
".venv\Scripts\python.exe" -m streamlit run app.py --server.address 127.0.0.1 --browser.gatherUsageStats false
if errorlevel 1 goto failed
exit /b 0
:failed
echo Startup failed. See the error above.
pause
exit /b 1
