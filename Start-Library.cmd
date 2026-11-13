@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start_desktop.ps1"
if errorlevel 1 pause
