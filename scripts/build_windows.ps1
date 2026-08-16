param(
    [string]$Python = ".\.venv\Scripts\python.exe"
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$uiRoot = Join-Path $projectRoot "ui"
$uiDist = Join-Path $projectRoot "src\canvas_gpt\ui_dist"
$entrypoint = Join-Path $projectRoot "packaging\desktop_entry.py"
$buildRoot = Join-Path $projectRoot "build"

Push-Location $projectRoot
try {
    & npm --prefix $uiRoot run build
    if ($LASTEXITCODE -ne 0) { throw "Frontend build failed." }

    New-Item -ItemType Directory -Force -Path $buildRoot | Out-Null

    & $Python -m PyInstaller `
        --noconfirm `
        --clean `
        --windowed `
        --name CanvasGPT `
        --specpath $buildRoot `
        --paths (Join-Path $projectRoot "src") `
        --add-data "$uiDist;canvas_gpt\ui_dist" `
        --collect-all webview `
        $entrypoint
    if ($LASTEXITCODE -ne 0) { throw "Desktop build failed." }

    $archive = Join-Path $projectRoot "dist\CanvasGPT-windows-x64.zip"
    if (Test-Path -LiteralPath $archive) {
        Remove-Item -LiteralPath $archive -Force
    }
    Compress-Archive -LiteralPath (Join-Path $projectRoot "dist\CanvasGPT") -DestinationPath $archive
    Write-Output "Built: $(Join-Path $projectRoot 'dist\CanvasGPT\CanvasGPT.exe')"
    Write-Output "Archive: $archive"
}
finally {
    Pop-Location
}
