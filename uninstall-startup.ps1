$ErrorActionPreference = "Stop"

$startupDir = [Environment]::GetFolderPath("Startup")
$shortcutPath = Join-Path $startupDir "Codex剩余额度弹窗.lnk"

if (Test-Path $shortcutPath) {
    Remove-Item -LiteralPath $shortcutPath
    Write-Host "已移除开机启动：$shortcutPath"
} else {
    Write-Host "没有找到启动项。"
}
