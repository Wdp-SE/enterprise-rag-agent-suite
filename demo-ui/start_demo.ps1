$ErrorActionPreference = 'Stop'
$python = Join-Path $PSScriptRoot '..\OpenManus-rag\.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw 'OpenManus-rag virtual environment is missing. See README.md.'
}
& $python -m streamlit run (Join-Path $PSScriptRoot 'app.py') --server.address 127.0.0.1 --server.port 8501

