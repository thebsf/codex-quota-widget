$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$distDir = Join-Path $projectRoot "dist"
$exe = Get-ChildItem -LiteralPath $distDir -Filter "*.exe" -File -ErrorAction SilentlyContinue | Select-Object -First 1
$exePath = if ($exe) { $exe.FullName } else { $null }
$watcherPath = Join-Path $projectRoot "codex-quota-watcher.ps1"
$powershellPath = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"

if (-not $exePath -or -not (Test-Path -LiteralPath $exePath)) {
    throw "没有在 $distDir 找到 exe，请先运行 .\build-windows.ps1 打包。"
}

if (-not (Test-Path $watcherPath)) {
    throw "没有找到 $watcherPath。"
}

$startupDir = [Environment]::GetFolderPath("Startup")
$shortcutPath = Join-Path $startupDir "Codex剩余额度弹窗.lnk"

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $powershellPath
$shortcut.Arguments = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$watcherPath`""
$shortcut.WorkingDirectory = $projectRoot
$shortcut.WindowStyle = 7
$shortcut.Description = "监听 Codex 启停并同步显示剩余额度弹窗"
$shortcut.Save()

Start-Process -FilePath $powershellPath -ArgumentList @(
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-WindowStyle", "Hidden",
    "-File", $watcherPath
) -WindowStyle Hidden | Out-Null

Write-Host "已加入 Codex 启停监听：$shortcutPath"
Write-Host "监听器已启动，并会随 Windows 启动；Codex 启动时打开弹窗，Codex 关闭时关闭弹窗。"
