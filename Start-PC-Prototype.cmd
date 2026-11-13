@echo off
if not exist "%~dp0output\Local-Library-Desktop\Library.exe" (
  echo Build the desktop app first: .venv\Scripts\python.exe scripts\build_standalone.py
  pause
  exit /b 1
)
start "" "%~dp0output\Local-Library-Desktop\Library.exe" --library "%~dp0data\pc-prototype"
