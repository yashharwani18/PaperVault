@echo off
echo Opening SYNTHETIC invoice demo. No transaction in this library is real.
"%~dp0.venv\Scripts\python.exe" "%~dp0scripts\prepare_demo_paths.py"
if errorlevel 1 exit /b 1
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start_desktop.ps1" -LibraryPath "%~dp0data\demo-invoices" -Port 8766
if errorlevel 1 pause
