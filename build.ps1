$ErrorActionPreference = "Stop"
Set-Location "C:\Users\wise\Desktop\voice-bridge_v1.0 (1)\frontend"
Write-Host "Current directory: $(Get-Location)"
Write-Host "Running vite build..."
& ".\node_modules\.bin\vite.cmd" build
Write-Host "Build complete!"
if (Test-Path "dist") {
    Write-Host "dist folder exists:"
    Get-ChildItem dist
} else {
    Write-Host "dist folder NOT found!"
}
