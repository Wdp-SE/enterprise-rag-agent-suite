param(
    [int]$RagPort = 8765,
    [int]$UiPort = 8502
)

$ErrorActionPreference = 'Stop'
$workspace = $PSScriptRoot
$ragRoot = Join-Path $workspace 'RAG-Challenge-2-main'
$uiRoot = Join-Path $workspace 'demo-ui'
$ragPython = Join-Path $ragRoot '.venv\Scripts\python.exe'
$uiPython = Join-Path $workspace 'OpenManus-rag\.venv\Scripts\python.exe'
$artifact = Join-Path $ragRoot 'data\rd_v2_corpus\retrieval_artifacts\rd-v2-retrieval-final-v1.0-safe-integration'

foreach ($required in @($ragPython, $uiPython, $artifact)) {
    if (-not (Test-Path -LiteralPath $required)) {
        throw "缺少启动依赖：$required"
    }
}

$runRoot = Join-Path $env:TEMP ('rag-agent-prototype-final-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
New-Item -ItemType Directory -Path $runRoot -Force | Out-Null

function Test-Endpoint([string]$Uri) {
    try {
        Invoke-WebRequest -Uri $Uri -UseBasicParsing -TimeoutSec 2 | Out-Null
        return $true
    } catch {
        return $false
    }
}

$ragUrl = "http://127.0.0.1:$RagPort"
if (-not (Test-Endpoint "$ragUrl/health")) {
    $env:RD_V2_PROJECT_ROOT = $ragRoot
    $env:RD_V2_ARTIFACT_ROOT = (Resolve-Path -LiteralPath $artifact).Path
    $env:RD_V2_ALLOW_EXTERNAL_GENERATION = 'false'
    $env:RD_V4_VERSION_STORE_ROOT = Join-Path $runRoot 'version-store'
    New-Item -ItemType Directory -Path $env:RD_V4_VERSION_STORE_ROOT -Force | Out-Null
    Start-Process -FilePath $ragPython -ArgumentList @('-m', 'uvicorn', 'src.rd_v2_api:app', '--host', '127.0.0.1', '--port', "$RagPort") -WorkingDirectory $ragRoot -RedirectStandardOutput (Join-Path $runRoot 'rag.stdout.log') -RedirectStandardError (Join-Path $runRoot 'rag.stderr.log') -WindowStyle Hidden | Out-Null
}

$ragReady = $false
for ($attempt = 0; $attempt -lt 30; $attempt++) {
    if (Test-Endpoint "$ragUrl/health") {
        $ragReady = $true
        break
    }
    Start-Sleep -Seconds 1
}
if (-not $ragReady) {
    throw "RAG 服务未能启动，请查看 $runRoot\rag.stderr.log"
}

$uiUrl = "http://127.0.0.1:$UiPort"
if (-not (Test-Endpoint $uiUrl)) {
    $env:DEMO_RAG_BASE_URL = $ragUrl
    $env:DEMO_RUNTIME_ROOT = Join-Path $runRoot 'ui-runtime'
    $env:STREAMLIT_BROWSER_GATHER_USAGE_STATS = 'false'
    $env:STREAMLIT_SERVER_HEADLESS = 'true'
    Start-Process -FilePath $uiPython -ArgumentList @('-m', 'streamlit', 'run', 'app.py', '--server.address', '127.0.0.1', '--server.port', "$UiPort", '--server.headless', 'true', '--browser.gatherUsageStats', 'false') -WorkingDirectory $uiRoot -RedirectStandardOutput (Join-Path $runRoot 'ui.stdout.log') -RedirectStandardError (Join-Path $runRoot 'ui.stderr.log') -WindowStyle Hidden | Out-Null
}

$uiReady = $false
for ($attempt = 0; $attempt -lt 30; $attempt++) {
    if (Test-Endpoint $uiUrl) {
        $uiReady = $true
        break
    }
    Start-Sleep -Seconds 1
}
if (-not $uiReady) {
    throw "UI 未能启动，请查看 $runRoot\ui.stderr.log"
}

Write-Host "Prototype Final 已启动：$uiUrl"
Write-Host "RAG API：$ragUrl/docs"
Write-Host "本次合成运行目录：$runRoot"
