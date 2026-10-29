# Build the Docker image and export it as a .tar for Synology Container Manager ("Image" → "Add" → "Add from file").
# Usage (from the project root):  .\deploy\build-image.ps1 [-Version 1.0.0]
param([string]$Version = "1.0.0")
$root = Split-Path -Parent $PSScriptRoot
$image = "aeons-expeditions:$Version"
$tar = Join-Path $PSScriptRoot "aeons-expeditions-$Version.tar"

# DS218+ is x86-64 (Intel Celeron J3355): build for linux/amd64 explicitly.
# (docker writes progress to stderr, so check exit codes rather than PowerShell errors)
docker build --platform linux/amd64 -t $image $root 2>&1 | ForEach-Object { "$_" }
if ($LASTEXITCODE -ne 0) { Write-Error "docker build failed"; exit 1 }
docker save -o $tar $image
if ($LASTEXITCODE -ne 0) { Write-Error "docker save failed"; exit 1 }
Write-Host "Image $image saved to $tar ($([math]::Round((Get-Item $tar).Length / 1MB)) MB)"
