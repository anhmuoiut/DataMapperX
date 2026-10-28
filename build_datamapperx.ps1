param(
    [string]$DistPath = "dist"
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$WorkPath = Join-Path $env:TEMP "DataMapperX_pyinstaller_build"

Push-Location $Root
try {
    python -m PyInstaller --noconfirm --workpath $WorkPath --distpath $DistPath DataMapperX.spec
}
finally {
    Pop-Location
}
