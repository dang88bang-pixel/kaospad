New-Item -ItemType Directory -Force -Path "vendor/asio-sdk" | Out-Null
"Offline ASIO SDK shim for CI scaffold" | Out-File -Encoding utf8 "vendor/asio-sdk/README.txt"
Write-Host "Prepared offline ASIO SDK shim"
