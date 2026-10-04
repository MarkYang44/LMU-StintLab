[CmdletBinding()]
param([switch]$CheckOnly)
$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
Set-Location -LiteralPath $projectRoot
if (-not (Test-Path -LiteralPath '.git')) { throw 'Publish.cmd is for the maintained Git checkout, not a downloaded source ZIP.' }
if (-not (Get-Command git.exe -ErrorAction SilentlyContinue)) { throw 'Install Git for Windows first.' }
$remote = & git remote get-url origin
if ($LASTEXITCODE -ne 0 -or $remote -ne 'https://github.com/MarkYang44/LMU-StintLab.git') { throw 'Unexpected origin. Verify the repository URL before publishing.' }
$branch = & git branch --show-current
if ($branch -ne 'main') { throw 'Publish.cmd only publishes the reviewed main branch.' }
& git diff --quiet
if ($LASTEXITCODE -ne 0) { throw 'Source changes must be reviewed and committed first.' }
& git diff --cached --quiet
if ($LASTEXITCODE -ne 0) { throw 'Staged changes must be reviewed and committed first.' }
$venvPython = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $venvPython)) { throw 'Run Setup.cmd before publishing.' }
& $venvPython (Join-Path $projectRoot 'tools\audit_publication.py')
if ($LASTEXITCODE -ne 0) { throw 'Privacy audit failed. No files were uploaded.' }
if ($CheckOnly) { Write-Host 'Publication checks passed. No upload requested.'; exit 0 }
# Git handles interactive authentication. The user completes any browser login.
# No force push; private data is excluded before this step.
& git -c http.sslBackend=openssl push -u origin main
if ($LASTEXITCODE -ne 0) { throw 'GitHub push failed. Complete Git for Windows authentication and rerun Publish.cmd.' }
Write-Host 'Public source uploaded to https://github.com/MarkYang44/LMU-StintLab' -ForegroundColor Green
