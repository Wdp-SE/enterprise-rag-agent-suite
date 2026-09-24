param(
    [int]$RagPort = 8765,
    [int]$UiPort = 8502,
    [switch]$EnableGeneration
)

$ErrorActionPreference = 'Stop'
$workspace = $PSScriptRoot
$ragRoot = Join-Path $workspace 'RAG-Challenge-2-main'
$uiRoot = Join-Path $workspace 'demo-ui'
$ragPython = Join-Path $ragRoot '.venv\Scripts\python.exe'
$uiPython = Join-Path $workspace 'OpenManus-rag\.venv\Scripts\python.exe'
$officialCorpus = Join-Path $ragRoot 'public_corpus\retrieval_policy.json'

foreach ($required in @($ragPython, $uiPython, $officialCorpus)) {
    if (-not (Test-Path -LiteralPath $required)) {
        throw "缺少启动依赖：$required；请先按 README 安装环境。"
    }
}

function Test-Endpoint([string]$Uri) {
    try {
        Invoke-WebRequest -Uri $Uri -UseBasicParsing -TimeoutSec 2 | Out-Null
        return $true
    } catch {
        return $false
    }
}

$ragUrl = "http://127.0.0.1:$RagPort"
$uiUrl = "http://127.0.0.1:$UiPort"
if (Test-Endpoint "$ragUrl/health") {
    throw "RAG 端口 $RagPort 已被占用；请停止旧服务或指定 -RagPort。"
}
if (Test-Endpoint $uiUrl) {
    throw "UI 端口 $UiPort 已被占用；请停止旧服务或指定 -UiPort。"
}

$runRoot = Join-Path $env:TEMP ('rag-agent-public-demo-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
New-Item -ItemType Directory -Path $runRoot -Force | Out-Null

$env:APP_ENV = 'public_demo'
$env:RD_V2_PROJECT_ROOT = $ragRoot
if ($EnableGeneration -and [string]::IsNullOrWhiteSpace($env:DASHSCOPE_API_KEY)) {
    throw '启用生成式回答前，请先在本机环境变量设置 DASHSCOPE_API_KEY。'
}
$env:RD_V2_ALLOW_EXTERNAL_GENERATION = if ($EnableGeneration) { 'true' } else { 'false' }

$ragProcess = Start-Process -FilePath $ragPython -ArgumentList @('-m', 'uvicorn', 'src.public_server:app', '--host', '127.0.0.1', '--port', "$RagPort") -WorkingDirectory $ragRoot -RedirectStandardOutput (Join-Path $runRoot 'rag.stdout.log') -RedirectStandardError (Join-Path $runRoot 'rag.stderr.log') -WindowStyle Hidden -PassThru

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

$env:RAG_API_BASE_URL = $ragUrl
$env:DEMO_RUNTIME_ROOT = Join-Path $runRoot 'ui-runtime'
$env:DEMO_DATA_CLASSIFICATION = 'Official Public'
$env:DEMO_LEGACY_FIXTURES = 'false'
$env:DEMO_ALLOW_RAG_QUERY = 'false'
$env:STREAMLIT_BROWSER_GATHER_USAGE_STATS = 'false'
$env:STREAMLIT_SERVER_HEADLESS = 'true'
$uiProcess = Start-Process -FilePath $uiPython -ArgumentList @('-m', 'streamlit', 'run', 'app.py', '--server.address', '127.0.0.1', '--server.port', "$UiPort", '--server.headless', 'true', '--browser.gatherUsageStats', 'false') -WorkingDirectory $uiRoot -RedirectStandardOutput (Join-Path $runRoot 'ui.stdout.log') -RedirectStandardError (Join-Path $runRoot 'ui.stderr.log') -WindowStyle Hidden -PassThru

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

Write-Host "官方公开研发资料工作台已启动：$uiUrl"
Write-Host "RAG API：$ragUrl/docs"
Write-Host "临时运行目录：$runRoot"
Write-Host "进程 ID：RAG $($ragProcess.Id)，UI $($uiProcess.Id)"
