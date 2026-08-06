$ErrorActionPreference = "Stop"
Set-Location "$PSScriptRoot\..\apps\api"
$env:PYTHONPATH = (Resolve-Path ".\src").Path
python -m uvicorn conclave.main:app --reload --host 127.0.0.1 --port 8000
