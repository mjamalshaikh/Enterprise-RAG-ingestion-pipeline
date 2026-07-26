# Set these only for the current PowerShell window.
$env:QDRANT_ADMIN_API_KEY = "qdrant_admin_F9mK7vQ2LpX8nRw4HsZd1YcT6UaB3JeN5GfW0xPi"
$env:QDRANT_READ_ONLY_API_KEY = "qdrant_readonly_R8cY4LmN2QvH9aXt6JkP1WsE5ZfG7BuD3nVr0XpA"

$baseUrl = "http://localhost:6333"
$testCollection = "qdrant_key_smoke_test"

$adminHeaders = @{ "api-key" = $env:QDRANT_ADMIN_API_KEY }
$readOnlyHeaders = @{ "api-key" = $env:QDRANT_READ_ONLY_API_KEY }

try {
    # 1. Both credentials should authenticate and list collections.
    Invoke-RestMethod -Method Get -Uri "$baseUrl/collections" -Headers $adminHeaders |
        Out-Null
    Write-Host "PASS: Admin key authenticated." -ForegroundColor Green

    Invoke-RestMethod -Method Get -Uri "$baseUrl/collections" -Headers $readOnlyHeaders |
        Out-Null
    Write-Host "PASS: Read-only key authenticated." -ForegroundColor Green

    # 2. Admin key should create a temporary collection.
    $createBody = @{
        vectors = @{
            size     = 4
            distance = "Cosine"
        }
    } | ConvertTo-Json -Depth 5

    Invoke-RestMethod -Method Put `
        -Uri "$baseUrl/collections/$testCollection" `
        -Headers $adminHeaders `
        -ContentType "application/json" `
        -Body $createBody | Out-Null

    Write-Host "PASS: Admin key created test collection." -ForegroundColor Green

    # 3. Read-only key should be allowed to read it.
    Invoke-RestMethod -Method Get `
        -Uri "$baseUrl/collections/$testCollection" `
        -Headers $readOnlyHeaders | Out-Null

    Write-Host "PASS: Read-only key read test collection." -ForegroundColor Green

    # 4. Read-only key must be denied a write.
    $pointBody = @{
        points = @(
            @{
                id     = 1
                vector = @(0.1, 0.2, 0.3, 0.4)
            }
        )
    } | ConvertTo-Json -Depth 5

    try {
        Invoke-RestMethod -Method Put `
            -Uri "$baseUrl/collections/$testCollection/points" `
            -Headers $readOnlyHeaders `
            -ContentType "application/json" `
            -Body $pointBody | Out-Null

        Write-Host "FAIL: Read-only key was able to write." -ForegroundColor Red
    }
    catch {
        Write-Host "PASS: Read-only key was denied write access." -ForegroundColor Green
    }
}
finally {
    # 5. Remove the temporary collection using the admin key.
    try {
        Invoke-RestMethod -Method Delete `
            -Uri "$baseUrl/collections/$testCollection" `
            -Headers $adminHeaders | Out-Null

        Write-Host "Cleanup complete." -ForegroundColor Green
    }
    catch {
        Write-Host "Cleanup skipped: test collection was not created." -ForegroundColor Yellow
    }
}