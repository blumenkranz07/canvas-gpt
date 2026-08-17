param(
    [string]$Python = ".\.venv\Scripts\python.exe",
    [ValidateSet("Release", "Dev")]
    [string]$Flavor = "Release"
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$uiRoot = Join-Path $projectRoot "ui"
$uiDist = Join-Path $projectRoot "src\canvas_gpt\ui_dist"
$buildRoot = Join-Path $projectRoot "build"

if ($Flavor -eq "Dev") {
    $entrypoint = Join-Path $projectRoot "packaging\desktop_dev_entry.py"
    $appName = "CanvasGPT-Dev"
    $windowOption = "--console"
    $providerBundleOptions = @("--hidden-import", "canvas_gpt.providers.fake_provider")
}
else {
    $entrypoint = Join-Path $projectRoot "packaging\desktop_entry.py"
    $appName = "CanvasGPT"
    $windowOption = "--windowed"
    $providerBundleOptions = @("--exclude-module", "canvas_gpt.providers.fake_provider")
}

Push-Location $projectRoot
try {
    & npm --prefix $uiRoot run build
    if ($LASTEXITCODE -ne 0) { throw "Frontend build failed." }

    New-Item -ItemType Directory -Force -Path $buildRoot | Out-Null

    $pyInstallerOptions = @(
        "-m", "PyInstaller",
        "--noconfirm",
        "--clean",
        $windowOption,
        "--name", $appName,
        "--specpath", $buildRoot,
        "--paths", (Join-Path $projectRoot "src"),
        "--add-data", "$uiDist;canvas_gpt\ui_dist",
        "--collect-all", "webview"
    ) + $providerBundleOptions + @($entrypoint)
    & $Python @pyInstallerOptions
    if ($LASTEXITCODE -ne 0) { throw "Desktop build failed." }

    $archive = Join-Path $projectRoot "dist\$appName-windows-x64.zip"
    if (Test-Path -LiteralPath $archive) {
        Remove-Item -LiteralPath $archive -Force
    }
    Compress-Archive -LiteralPath (Join-Path $projectRoot "dist\$appName") -DestinationPath $archive
    Write-Output "Built ($Flavor): $(Join-Path $projectRoot "dist\$appName\$appName.exe")"
    Write-Output "Archive: $archive"
}
finally {
    Pop-Location
}
