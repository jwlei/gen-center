# Creates a "gen-center" shortcut on the Desktop and in the Start menu that
# runs start_webapp.pyw: starts the control panel (port 8800) with no console
# window and opens it in the default browser. Safe to re-run.
#   powershell -ExecutionPolicy Bypass -File scripts\create_shortcut.ps1
#   Add -Startup to create a headless Windows sign-in shortcut instead.

param([switch]$Startup)

$root = Split-Path -Parent $PSScriptRoot
$launcher = Join-Path $root 'start_webapp.pyw'

# pythonw / pyw run Python without a console window.
$pythonw = (Get-Command pyw -ErrorAction SilentlyContinue).Source
if (-not $pythonw) { $pythonw = (Get-Command pythonw).Source }

$shell = New-Object -ComObject WScript.Shell
$folders = if ($Startup) { @([Environment]::GetFolderPath('Startup')) } else { @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs')) }
foreach ($folder in $folders) {
    $shortcut = $shell.CreateShortcut((Join-Path $folder 'gen-center.lnk'))
    $shortcut.TargetPath = $pythonw
    $shortcut.Arguments = "`"$launcher`"" + $(if ($Startup) { ' --headless' } else { '' })
    $shortcut.WorkingDirectory = $root
    $shortcut.Description = if ($Startup) { 'Start the gen-center panel without opening a browser' } else { 'Open the gen-center panel' }
    # Clapperboard-style "video" icon from Windows' own icon library.
    $shortcut.IconLocation = Join-Path $env:SystemRoot 'System32\imageres.dll,18'
    $shortcut.Save()
    Write-Output "Created $(Join-Path $folder 'gen-center.lnk')"
}
