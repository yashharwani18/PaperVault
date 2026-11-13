@echo off
if exist "%~dp0output\Local-Library-Desktop\Library.exe" start "" "%~dp0output\Local-Library-Desktop\Library.exe" --library "%~dp0data\pc-prototype" --quit
