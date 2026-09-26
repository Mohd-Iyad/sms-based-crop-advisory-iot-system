@echo off
REM Starts the backend so the ESP32 on your Wi-Fi can reach it.
REM   --host 0.0.0.0  = listen on the network, not just this PC (the ESP32 is a different device)
REM   The ESP32's BACKEND_URL must be  http://<this PC's Wi-Fi IPv4 address>:8000/sensor-data
REM   (find it with:  ipconfig   -> "IPv4 Address" of your Wi-Fi adapter)
cd /d "%~dp0"
REM The venv normally lives inside this folder (README Step 1); a copy one level up also works.
set "PY=venv\Scripts\python.exe"
if not exist "%PY%" set "PY=..\venv\Scripts\python.exe"
if not exist "%PY%" (
  echo Virtual environment not found in .\venv or ..\venv - see README Step 1.
  exit /b 1
)
echo.
echo Dashboard on this PC:   http://127.0.0.1:8000/dashboard
echo API docs / test page:   http://127.0.0.1:8000/docs
echo Press Ctrl+C to stop.
echo.
"%PY%" -m uvicorn main:app --host 0.0.0.0 --port 8000
