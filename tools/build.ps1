<#
.SYNOPSIS
    Build dist\DataMapperX.exe and prove it starts.

.PARAMETER Python
    Python to use (default: "python"). Use the one from your virtual environment.

.PARAMETER DistPath
    Output folder (default: dist).
#>
param(
    [string]$Python = "python",
    [string]$DistPath = "dist"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
# Build outside the project so OneDrive does not try to sync thousands of intermediate files.
$WorkPath = Join-Path $env:TEMP "DataMapperX_pyinstaller_build"

Push-Location $Root
try {
    # PyInstaller can otherwise build successfully while omitting an unavailable lazy import.
    & $Python -c "import openpyxl, sv_ttk, PIL, PyInstaller; import reportlab.pdfgen.canvas, reportlab.platypus, reportlab.graphics.shapes"
    if ($LASTEXITCODE -ne 0) {
        throw "Build dependencies are missing. Run: $Python -m pip install -r requirements-dev.txt"
    }

    & $Python tools\make_version_info.py
    if ($LASTEXITCODE -ne 0) { throw "make_version_info failed" }

    & $Python -m PyInstaller --noconfirm --clean --workpath $WorkPath --distpath $DistPath DataMapperX.spec
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

    $exe = Join-Path $DistPath "DataMapperX.exe"
    Write-Host "Built $exe ($([math]::Round((Get-Item $exe).Length / 1MB, 1)) MB). Running self-test..."

    # Use a throw-away data folder so the test never touches your real profiles or settings.
    $env:DATAMAPPERX_HOME = Join-Path $env:TEMP "DataMapperX_selftest"
    $process = Start-Process -FilePath $exe -ArgumentList "--smoke-test" -WindowStyle Hidden -Wait -PassThru
    if ($process.ExitCode -ne 0) { throw "Self-test FAILED (exit code $($process.ExitCode)). See $env:DATAMAPPERX_HOME\app_debug.log" }
    Write-Host "Self-test passed."
}
finally {
    Pop-Location
}
