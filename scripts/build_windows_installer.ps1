New-Item -ItemType Directory -Force -Path "dist" | Out-Null
"Kaoss Windows MSI scaffold" | Out-File -Encoding ascii "dist/KaossBeatboxStudio-v5.0.0-Setup.msi"
Write-Host "dist/KaossBeatboxStudio-v5.0.0-Setup.msi"
