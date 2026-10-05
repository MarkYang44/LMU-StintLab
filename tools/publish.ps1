[CmdletBinding()]
param([switch]$CheckOnly)
$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
Set-Location -LiteralPath $projectRoot
if (-not (Test-Path -LiteralPath '.git')) { throw 'Publish.cmd is for the maintained Git checkout, not a downloaded source ZIP.' }
if (-not (Get-Command git.exe -ErrorAction SilentlyContinue)) { throw 'Install Git for Windows first.' }
# Trust only this explicit checkout for each command. Do not alter global Git
# configuration or file ownership when the checkout was created by a sandbox.
$gitProjectArgs = @('-c', 'safe.directory=', '-c', ('safe.directory=' + $projectRoot.Replace('\', '/')))
$remote = & git @gitProjectArgs remote get-url origin
if ($LASTEXITCODE -ne 0) { throw 'Git could not read origin. See the Git error above; no upload was attempted.' }
if ($remote -ne 'https://github.com/MarkYang44/LMU-Stintrix.git') { throw 'Unexpected origin. Verify the repository URL before publishing.' }
$branch = & git @gitProjectArgs branch --show-current
if ($LASTEXITCODE -ne 0) { throw 'Git could not read the current branch. No upload was attempted.' }
if ($branch -ne 'main') { throw 'Publish.cmd only publishes the reviewed main branch.' }
& git @gitProjectArgs diff --quiet
if ($LASTEXITCODE -gt 1) { throw 'Git could not check working-tree changes. No upload was attempted.' }
if ($LASTEXITCODE -ne 0) { throw 'Source changes must be reviewed and committed first.' }
& git @gitProjectArgs diff --cached --quiet
if ($LASTEXITCODE -gt 1) { throw 'Git could not check staged changes. No upload was attempted.' }
if ($LASTEXITCODE -ne 0) { throw 'Staged changes must be reviewed and committed first.' }
$venvPython = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $venvPython)) { throw 'Run Setup.cmd before publishing.' }
& $venvPython (Join-Path $projectRoot 'tools\audit_publication.py')
if ($LASTEXITCODE -ne 0) { throw 'Privacy audit failed. No files were uploaded.' }
if ($CheckOnly) { Write-Host 'Publication checks passed. No upload requested.'; exit 0 }
# Git handles interactive authentication. The user completes any browser login.
# No force push; private data is excluded before this step.
& git @gitProjectArgs -c http.sslBackend=openssl push -u origin main
if ($LASTEXITCODE -ne 0) { throw 'GitHub push failed. Complete Git for Windows authentication and rerun Publish.cmd.' }
Write-Host 'Public source uploaded to https://github.com/MarkYang44/LMU-Stintrix' -ForegroundColor Green
