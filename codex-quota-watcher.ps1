param(
    [switch]$Once
)

$ErrorActionPreference = "Stop"

$mutex = $null
if (-not $Once) {
    $createdNew = $false
    $mutex = New-Object System.Threading.Mutex($true, "Local\CodexQuotaWatcherSingleInstance", [ref]$createdNew)
    if (-not $createdNew) {
        exit 0
    }
}

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$distDir = Join-Path $projectRoot "dist"

function Get-WidgetExePath {
    $exe = Get-ChildItem -LiteralPath $distDir -Filter "*.exe" -File -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($exe) {
        return $exe.FullName
    }
    return $null
}

function Test-CodexRunning {
    $processes = Get-Process -Name "Codex", "codex" -ErrorAction SilentlyContinue
    return [bool]($processes | Select-Object -First 1)
}

function Get-WidgetProcesses {
    param(
        [string]$WidgetExePath
    )

    $widgetProcessName = [System.IO.Path]::GetFileNameWithoutExtension($WidgetExePath)
    Get-Process -ErrorAction SilentlyContinue | Where-Object {
        try {
            $_.Path -eq $WidgetExePath
        } catch {
            $_.ProcessName -eq $widgetProcessName
        }
    }
}

function Sync-WidgetState {
    $exePath = Get-WidgetExePath
    if (-not $exePath -or -not (Test-Path -LiteralPath $exePath)) {
        return
    }

    $codexRunning = Test-CodexRunning
    $widgetProcesses = @(Get-WidgetProcesses -WidgetExePath $exePath)

    if ($codexRunning) {
        if ($widgetProcesses.Count -gt 1) {
            $widgetProcesses |
                Sort-Object Id |
                Select-Object -Skip 1 |
                ForEach-Object { Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue }
            $widgetProcesses = @(Get-WidgetProcesses -WidgetExePath $exePath)
        }
        if ($widgetProcesses.Count -eq 0) {
            Start-Process -FilePath $exePath -WorkingDirectory (Split-Path -Parent $exePath) -WindowStyle Hidden
        }
        return
    }

    foreach ($process in $widgetProcesses) {
        Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
    }
}

try {
    do {
        Sync-WidgetState
        if ($Once) {
            break
        }
        Start-Sleep -Seconds 3
    } while ($true)
} finally {
    if ($mutex) {
        $mutex.ReleaseMutex()
        $mutex.Dispose()
    }
}
