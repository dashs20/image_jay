# Image Jay uninstaller (per-user). Removes the app folder, shortcuts, .ijay association and the Apps & features entry.
$ErrorActionPreference = "SilentlyContinue"
$dest = Join-Path $env:LOCALAPPDATA "Programs\Image Jay"
Get-Process ImageJay | Where-Object { $_.Path -like "$dest*" } | Stop-Process -Force
Remove-Item (Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Image Jay.lnk") -Force
Remove-Item (Join-Path ([Environment]::GetFolderPath("Desktop")) "Image Jay.lnk") -Force
Remove-Item "HKCU:\Software\Classes\.ijay" -Recurse -Force
Remove-Item "HKCU:\Software\Classes\ImageJay.Session" -Recurse -Force
Remove-Item "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\ImageJay" -Recurse -Force
# the folder holds this script; delete it after we exit
Start-Process cmd.exe -ArgumentList "/c timeout /t 2 /nobreak >nul & rmdir /s /q `"$dest`"" -WindowStyle Hidden
Write-Host "Image Jay uninstalled."
