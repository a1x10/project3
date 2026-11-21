param([string]$AppDir)
$AppDir = (Resolve-Path $AppDir).Path.TrimEnd('\')
$exe = Join-Path $AppDir 'node_modules\electron\dist\electron.exe'
$shell = New-Object -ComObject WScript.Shell

$targets = @(
  (Join-Path ([Environment]::GetFolderPath('Desktop')) 'Agy Desktop.lnk'),
  (Join-Path ([Environment]::GetFolderPath('Programs')) 'Agy Desktop.lnk')
)
foreach ($lnk in $targets) {
  $s = $shell.CreateShortcut($lnk)
  $s.TargetPath = $exe
  $s.Arguments = '"' + $AppDir + '"'
  $s.WorkingDirectory = $AppDir
  $s.Description = 'Agy Desktop - Antigravity CLI'
  $s.Save()
  # set "Run as administrator" flag on the shortcut
  $bytes = [IO.File]::ReadAllBytes($lnk)
  $bytes[0x15] = $bytes[0x15] -bor 0x20
  [IO.File]::WriteAllBytes($lnk, $bytes)
  Write-Host "  shortcut: $lnk"
}
