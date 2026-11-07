# Image Jay per-user installer (no admin needed).
#  - copies dist\ImageJay to %LOCALAPPDATA%\Programs\Image Jay
#  - Start Menu shortcut (right-click it -> Pin to taskbar) and an optional desktop shortcut
#  - .ijay session files open in Image Jay
#  - "Apps & features" entry with an uninstaller
param([switch]$Desktop, [switch]$Quiet)
$ErrorActionPreference = "Stop"

$src = Join-Path $PSScriptRoot "dist\ImageJay"
if (-not (Test-Path (Join-Path $src "ImageJay.exe"))) {
    Write-Host "dist\ImageJay\ImageJay.exe not found - run build.bat first." -ForegroundColor Red
    exit 1
}
$dest = Join-Path $env:LOCALAPPDATA "Programs\Image Jay"
$exe = Join-Path $dest "ImageJay.exe"

Get-Process ImageJay -ErrorAction SilentlyContinue | Where-Object { $_.Path -eq $exe } | Stop-Process -Force
if (Test-Path $dest) { Remove-Item $dest -Recurse -Force }
New-Item -ItemType Directory -Force $dest | Out-Null
Copy-Item (Join-Path $src "*") $dest -Recurse -Force
Copy-Item (Join-Path $PSScriptRoot "uninstall.ps1") $dest -Force

# shortcuts
$shell = New-Object -ComObject WScript.Shell
function New-Shortcut($path) {
    $lnk = $shell.CreateShortcut($path)
    $lnk.TargetPath = $exe
    $lnk.WorkingDirectory = $dest
    $lnk.IconLocation = "$exe,0"
    $lnk.Description = "Image Jay - measure dimensions from images"
    $lnk.Save()
}
$startMenu = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Image Jay.lnk"
New-Shortcut $startMenu
if ($Desktop) { New-Shortcut (Join-Path ([Environment]::GetFolderPath("Desktop")) "Image Jay.lnk") }

# .ijay file association (current user)
$cls = "HKCU:\Software\Classes"
New-Item -Force "$cls\.ijay" | Out-Null
Set-ItemProperty "$cls\.ijay" -Name "(default)" -Value "ImageJay.Session"
New-Item -Force "$cls\ImageJay.Session\DefaultIcon" | Out-Null
Set-ItemProperty "$cls\ImageJay.Session" -Name "(default)" -Value "Image Jay session"
Set-ItemProperty "$cls\ImageJay.Session\DefaultIcon" -Name "(default)" -Value "`"$exe`",0"
New-Item -Force "$cls\ImageJay.Session\shell\open\command" | Out-Null
Set-ItemProperty "$cls\ImageJay.Session\shell\open\command" -Name "(default)" -Value "`"$exe`" `"%1`""

# Apps & features entry
$un = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\ImageJay"
New-Item -Force $un | Out-Null
$size = [int]((Get-ChildItem $dest -Recurse | Measure-Object Length -Sum).Sum / 1KB)
$props = @{
    DisplayName = "Image Jay"; DisplayVersion = "1.0.0"; Publisher = "dashs20"; DisplayIcon = "$exe,0"
    InstallLocation = $dest; EstimatedSize = $size; NoModify = 1; NoRepair = 1
    UninstallString = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$dest\uninstall.ps1`""
}
foreach ($k in $props.Keys) { Set-ItemProperty $un -Name $k -Value $props[$k] }

# tell Explorer the associations changed
Add-Type -Namespace Win32 -Name Shell -MemberDefinition '[DllImport("shell32.dll")] public static extern void SHChangeNotify(int e, int f, IntPtr a, IntPtr b);'
[Win32.Shell]::SHChangeNotify(0x08000000, 0, [IntPtr]::Zero, [IntPtr]::Zero)

Write-Host "Installed Image Jay to $dest" -ForegroundColor Green
Write-Host "Start Menu: 'Image Jay' (right-click -> Pin to taskbar)."
if (-not $Quiet) { Start-Process $exe }
