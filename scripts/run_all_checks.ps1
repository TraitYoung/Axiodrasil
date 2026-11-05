Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
python -m unittest discover -s test_suite -v
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python -m test_suite.test_solo_fast
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
