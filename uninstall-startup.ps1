$ErrorActionPreference = "Stop"

$startupDir = [Environment]::GetFolderPath("Startup")
$shortcutPath = Join-Path $startupDir "Codex剩余额度弹窗.lnk"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$watcherPath = Join-Path $projectRoot "codex-quota-watcher.ps1"

if (Test-Path $shortcutPath) {
    Remove-Item -LiteralPath $shortcutPath
    Write-Host "已移除开机启动：$shortcutPath"
} else {
    Write-Host "没有找到启动项。"
}

$watcherProcesses = Get-CimInstance Win32_Process -Filter "Name = 'powershell.exe' OR Name = 'pwsh.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -and $_.CommandLine -like "*$watcherPath*" }

foreach ($process in $watcherProcesses) {
    Stop-Process -Id $process.ProcessId -Force -ErrorAction SilentlyContinue
}

if ($watcherProcesses) {
    Write-Host "已停止 Codex 启停监听器。"
}
