@echo off
rem Launch Image Jay. Drag an image or a .ijay session onto this file to open it directly.
cd /d "%~dp0"
where pythonw >nul 2>nul
if %errorlevel%==0 (
    start "" pythonw "%~dp0image_jay.py" %*
) else (
    python "%~dp0image_jay.py" %*
    if errorlevel 1 pause
)
