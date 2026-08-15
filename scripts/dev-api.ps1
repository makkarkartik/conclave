$ErrorActionPreference = "Stop"
Set-Location "$PSScriptRoot\..\apps\api"
$env:PYTHONPATH = (Resolve-Path ".\src").Path
# conclave.serve (not `python -m uvicorn`): sets the Windows selector loop policy
# before uvicorn creates its event loop — psycopg async requires it.
python -m conclave.serve --reload --host 127.0.0.1 --port 8000
