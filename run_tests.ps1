$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot
Write-Host "[tests] python -m unittest discover -s tests -t ."
python -W ignore::ResourceWarning -m unittest discover -s tests -t . -v
exit $LASTEXITCODE
