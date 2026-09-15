$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot

$ollamaCandidates = @(
    "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe",
    "C:\Program Files\Ollama\ollama.exe"
)
$ollamaExe = $ollamaCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $ollamaExe) { $ollamaExe = (Get-Command ollama -ErrorAction SilentlyContinue).Source }
if (-not $ollamaExe) { throw "Ollama를 찾을 수 없습니다." }

try { Invoke-RestMethod "http://127.0.0.1:11434/api/tags" -TimeoutSec 2 | Out-Null }
catch {
    Start-Process -FilePath $ollamaExe -ArgumentList "serve" -WindowStyle Hidden
    Start-Sleep -Seconds 2
}

$models = (Invoke-RestMethod "http://127.0.0.1:11434/api/tags" -TimeoutSec 5).models.name
if ($models -notcontains "qwen3:1.7b") { & $ollamaExe pull "qwen3:1.7b" }
if (-not ($models | Where-Object { $_ -like "bge-m3:*" })) { & $ollamaExe pull "bge-m3" }

Write-Host "TEIN Knowledge: http://127.0.0.1:8000" -ForegroundColor Cyan
& ".\.venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8000
