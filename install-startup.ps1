$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$exePath = Join-Path $projectRoot "dist\Codex剩余额度弹窗.exe"

if (-not (Test-Path $exePath)) {
    throw "没有找到 $exePath，请先运行 .\build-windows.ps1 打包。"
}

$startupDir = [Environment]::GetFolderPath("Startup")
$shortcutPath = Join-Path $startupDir "Codex剩余额度弹窗.lnk"

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $exePath
$shortcut.WorkingDirectory = Split-Path -Parent $exePath
$shortcut.WindowStyle = 7
$shortcut.Description = "Codex 打开时显示剩余额度弹窗"
$shortcut.Save()

Write-Host "已加入开机启动：$shortcutPath"
Write-Host "它会随 Windows 启动，Codex 未打开时自动隐藏。"
