@echo off
rem Install Image Jay for the current user (no admin). Add --desktop for a desktop shortcut too:  install.bat -Desktop
cd /d "%~dp0"
if not exist "dist\ImageJay\ImageJay.exe" call build.bat
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" %*
pause
