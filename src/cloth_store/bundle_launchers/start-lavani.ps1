# My GFs Closet — local static preview (Python stdlib HTTP server).
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot

$pythonCmd = $null
$pythonArgs = @('-m', 'http.server', '8080', '--bind', '127.0.0.1')

if (Get-Command py -ErrorAction SilentlyContinue) {
    $pythonCmd = 'py'
    $pythonArgs = @('-3') + $pythonArgs
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    $pythonCmd = 'python'
} else {
    Write-Host ''
    Write-Host 'Python 3 is not installed or not on PATH.' -ForegroundColor Red
    Write-Host 'Install from https://www.python.org/downloads/'
    Write-Host 'During setup, check "Add python.exe to PATH".'
    Write-Host ''
    Read-Host 'Press Enter to exit'
    exit 1
}

Write-Host ''
Write-Host "My GFs Closet - local preview at http://127.0.0.1:8080/"
Write-Host 'Press Ctrl+C to stop the server.'
Write-Host ''
Start-Process 'http://127.0.0.1:8080/'
& $pythonCmd @pythonArgs
