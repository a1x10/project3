# Laptop microphone -> speaker on the board. Run: start_mic.bat
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
if (-not $py) { Write-Host "Python not found. Set path: `$env:PYEXE='C:\...\python.exe'; .\start_mic.ps1"; exit 1 }

if (-not (Test-Path .venv-mic\Scripts\python.exe)) {
    & $py -m venv .venv-mic
}
& .\.venv-mic\Scripts\python.exe -m pip install -q -r requirements-mic.txt

if (-not (Test-Path host.txt)) {
    $h = Read-Host "Board IP (for example 192.168.8.11)"
    $h | Set-Content host.txt -Encoding ascii
}
$hostip = (Get-Content host.txt -Raw).Trim()

$args2 = @("mic_client.py", "--host", $hostip)
if (Test-Path device.txt) { $args2 += @("--device", (Get-Content device.txt -Raw).Trim()) }
else {
    & .\.venv-mic\Scripts\python.exe mic_client.py --list-devices
    Write-Host ""
    Write-Host "To use a specific microphone, write its number into device.txt next to this script, then run again."
}
& .\.venv-mic\Scripts\python.exe @args2
