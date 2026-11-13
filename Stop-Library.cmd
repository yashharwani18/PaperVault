@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\stop_desktop.ps1"
if errorlevel 1 pause
