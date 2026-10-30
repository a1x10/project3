# Запуск колонки на Windows. Можно задать свой Python: $env:PYEXE="C:\Path\python.exe"
Set-Location $PSScriptRoot

function Find-Python {
    if ($env:PYEXE -and (Test-Path $env:PYEXE)) { return $env:PYEXE }
    foreach ($v in "3.12", "3.11", "3.10") {
        $p = (& py "-$v" -c "import sys;print(sys.executable)" 2>$null)
        if ($LASTEXITCODE -eq 0 -and $p) { return $p }
    }
    foreach ($v in "312", "311", "310") {
        foreach ($base in "$env:LOCALAPPDATA\Programs\Python\Python$v", "C:\Python$v", "C:\Program Files\Python$v") {
            if (Test-Path "$base\python.exe") { return "$base\python.exe" }
        }
    }
    $c = Get-Command python -ErrorAction SilentlyContinue
    if ($c) { return $c.Source }
    return $null
}

$py = Find-Python
if (-not $py) {
    Write-Host "Python не найден. Задайте путь: `$env:PYEXE='C:\...\python.exe'; .\start.ps1"
    exit 1
}
Write-Host "Python: $py"

if (-not (Test-Path .venv\Scripts\python.exe)) { 
    if (Test-Path .venv) { Remove-Item .venv -Recurse -Force }
    & $py -m venv .venv
}
& .\.venv\Scripts\python.exe -m pip install -q -r requirements.txt
if (-not (Test-Path .env)) {
    $k = Read-Host "ELEVENLABS_API_KEY"
    $a = Read-Host "ELEVENLABS_AGENT_ID"
    "ELEVENLABS_API_KEY=$k`nELEVENLABS_AGENT_ID=$a" | Set-Content .env -Encoding ascii
}
& .\.venv\Scripts\python.exe speaker.py --list-devices
& .\.venv\Scripts\python.exe speaker.py
