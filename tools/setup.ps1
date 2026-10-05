[CmdletBinding()]
param([string]$GameDirectory = '', [switch]$BuildTools)
$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
Set-Location -LiteralPath $projectRoot
if (-not [Environment]::Is64BitOperatingSystem) { throw 'LMU Stintrix requires 64-bit Windows.' }

function Find-Python313 {
    foreach ($entry in @(@{Name='py.exe';Args=@('-3.13')}, @{Name='python.exe';Args=@()})) {
        $command = Get-Command $entry.Name -ErrorAction SilentlyContinue
        if (-not $command) { continue }
        $prefixArgs = $entry.Args
        $previousPreference = $ErrorActionPreference
        $ErrorActionPreference = 'Continue'
        $result = & $command.Source @prefixArgs -c "import sys,struct; sys.exit(1) if sys.version_info[:2] != (3,13) or struct.calcsize('P') != 8 else print(sys.executable)" 2>$null
        $code = $LASTEXITCODE
        $ErrorActionPreference = $previousPreference
        if ($code -eq 0 -and $result) { return [string](@($result)[-1]) }
    }
    return $null
}

$pythonExecutable = Find-Python313
if (-not $pythonExecutable) {
    $winget = Get-Command winget.exe -ErrorAction SilentlyContinue
    if (-not $winget) { throw 'Install 64-bit Python 3.13 with Tcl/Tk from https://www.python.org/downloads/windows/ and run Setup.cmd again.' }
    Write-Host 'Installing official Python 3.13 for the current user with winget...'
    & $winget.Source install --id Python.Python.3.13 --exact --source winget --scope user --silent --accept-package-agreements --accept-source-agreements
    if ($LASTEXITCODE -ne 0) { throw 'Python installation failed. Install Python 3.13 manually, then rerun Setup.cmd.' }
    $pythonExecutable = Find-Python313
    if (-not $pythonExecutable) {
        $candidate = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python313\python.exe'
        if (Test-Path -LiteralPath $candidate -PathType Leaf) { $pythonExecutable = $candidate }
    }
    if (-not $pythonExecutable) { throw 'Python was installed; reopen this folder and run Setup.cmd again.' }
}

$venvPython = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $venvPython -PathType Leaf)) {
    Write-Host 'Creating an isolated local Python environment...'
    & $pythonExecutable -m venv (Join-Path $projectRoot '.venv')
    if ($LASTEXITCODE -ne 0) { throw 'Failed to create .venv.' }
}
& $venvPython -c "import sys,struct; sys.exit(0 if sys.version_info[:2] == (3,13) and struct.calcsize('P') == 8 else 1)"
if ($LASTEXITCODE -ne 0) { throw 'This .venv is not 64-bit Python 3.13. Rename .venv and run Setup.cmd again.' }
Write-Host 'Downloading official pinned wheels and verifying SHA256...'
$dependencyArgs = @()
if ($BuildTools) { $dependencyArgs += '--build' }
& $venvPython (Join-Path $projectRoot 'tools\install_dependencies.py') @dependencyArgs
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed. Check your network, then rerun Setup.cmd.' }

$configFile = Join-Path $projectRoot 'local_settings.json'
if (Test-Path -LiteralPath $configFile) {
    $config = Get-Content -LiteralPath $configFile -Raw | ConvertFrom-Json
} else { $config = [PSCustomObject]@{data_directory='data';game_directory=''} }
if ($GameDirectory) {
    if (-not (Test-Path -LiteralPath $GameDirectory -PathType Container)) { throw 'GameDirectory does not exist.' }
    $resolvedGame = (Resolve-Path -LiteralPath $GameDirectory).Path
    $config | Add-Member -MemberType NoteProperty -Name game_directory -Value $resolvedGame -Force
}
# Local paths are private. Never copy settings or modify the game installation.
$utf8 = New-Object System.Text.UTF8Encoding($false)
[IO.File]::WriteAllText($configFile, ($config | ConvertTo-Json -Depth 5), $utf8)
& $venvPython (Join-Path $projectRoot 'tools\doctor.py')
if ($LASTEXITCODE -ne 0) { throw 'Environment check failed; see the checks above.' }
& $venvPython (Join-Path $projectRoot 'tools\build_brand.py')
if ($LASTEXITCODE -ne 0) { throw 'App icon generation failed.' }
Write-Host 'Ready. Double-click Start.cmd. Demo.cmd runs synthetic telemetry. No game files were changed.' -ForegroundColor Green
