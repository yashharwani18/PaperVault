@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\stop_desktop.ps1" -LibraryPath "%~dp0data\demo-invoices"
if errorlevel 1 pause
