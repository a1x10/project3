param([string]$AppDir)
$AppDir = (Resolve-Path $AppDir).Path.TrimEnd('\')
$exe = Join-Path $AppDir 'node_modules\electron\dist\electron.exe'
$shell = New-Object -ComObject WScript.Shell

# remove old shortcuts from previous versions
foreach ($old in @((Join-Path ([Environment]::GetFolderPath('Desktop')) 'Agy Desktop.lnk'), (Join-Path ([Environment]::GetFolderPath('Programs')) 'Agy Desktop.lnk'))) {
  if (Test-Path $old) { Remove-Item $old -Force }
}

$targets = @(
  (Join-Path ([Environment]::GetFolderPath('Desktop')) 'Stella.lnk'),
  (Join-Path ([Environment]::GetFolderPath('Programs')) 'Stella.lnk')
)
foreach ($lnk in $targets) {
  $s = $shell.CreateShortcut($lnk)
  $s.TargetPath = $exe
  $s.Arguments = '"' + $AppDir + '"'
  $s.WorkingDirectory = $AppDir
  $s.Description = 'Stella'
  $s.Save()
  # set "Run as administrator" flag on the shortcut
  $bytes = [IO.File]::ReadAllBytes($lnk)
  $bytes[0x15] = $bytes[0x15] -bor 0x20
  [IO.File]::WriteAllBytes($lnk, $bytes)
  Write-Host "  shortcut: $lnk"
}
