@echo off
rem Build Image Jay into dist\ImageJay\ImageJay.exe (folder build: starts fast, far fewer antivirus false positives
rem than a single-file exe). Then run install.bat to install it with a Start Menu shortcut.
cd /d "%~dp0"
python -m pip install --upgrade -r requirements.txt pyinstaller || goto :fail
python -m PyInstaller --noconfirm --clean --windowed --onedir --name ImageJay ^
    --icon image_jay.ico ^
    --add-data "logo.png;." --add-data "image_jay.ico;." ^
    --version-file version_info.txt ^
    image_jay.py || goto :fail
echo.
echo Built: %~dp0dist\ImageJay\ImageJay.exe
echo Run install.bat to install it (Start Menu shortcut, .ijay file association).
pause
exit /b 0
:fail
echo BUILD FAILED
pause
exit /b 1
