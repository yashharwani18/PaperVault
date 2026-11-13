@echo off
if exist "%~dp0output\Local-Library-Desktop\PaperVault.exe" (
  start "" "%~dp0output\Local-Library-Desktop\PaperVault.exe" --library "%~dp0data\pc-prototype"
  exit /b 0
)
if exist "%~dp0output\Local-Library-Desktop\Library.exe" (
  start "" "%~dp0output\Local-Library-Desktop\Library.exe" --library "%~dp0data\pc-prototype"
  exit /b 0
)
echo Build the desktop app first: .venv\Scripts\python.exe scripts\build_standalone.py
pause
exit /b 1
