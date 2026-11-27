<#
.SYNOPSIS
    Night Jester demosu için Kod Koruyucu test reposunu hazırlar.

.DESCRIPTION
    Repo yoksa oluşturur ve ilk commit'i atar. Ardından app.py dosyasına kaydedilmiş ama
    commit'lenmemiş bir satır ekler. Böylece Deadline modunda uyuyunca Kod Koruyucu'nun
    yedekleyeceği bir değişiklik olur. Hiçbir dosyayı silmez, var olan commit'lere dokunmaz.

.PARAMETER RepoPath
    Test reposunun yolu. Varsayılan: Masaüstü\nj_test_repo

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File tools\prepare_demo_repo.ps1
#>
param(
    [string]$RepoPath = (Join-Path ([Environment]::GetFolderPath("Desktop")) "nj_test_repo")
)

$ErrorActionPreference = "Stop"

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Host "git bulunamadı. Git for Windows kurulu ve PATH'te olmalı." -ForegroundColor Red
    exit 1
}

if (-not (Test-Path (Join-Path $RepoPath ".git"))) {
    Write-Host "Test reposu oluşturuluyor: $RepoPath"
    New-Item -ItemType Directory -Force -Path $RepoPath | Out-Null
    git -C $RepoPath init -q
    Set-Content -Path (Join-Path $RepoPath "app.py") -Value "print('Night Jester demo v1')" -Encoding utf8
    git -C $RepoPath add app.py
    git -C $RepoPath commit -q -m "ilk commit"
} else {
    Write-Host "Test reposu zaten var: $RepoPath"
}

$stamp = Get-Date -Format "HH:mm:ss"
Add-Content -Path (Join-Path $RepoPath "app.py") -Value "# $stamp - deadline gecesi, kaydedildi ama commit'lenmedi" -Encoding utf8

Write-Host ""
Write-Host "Hazır. Commit'lenmemiş değişiklik:" -ForegroundColor Green
git -C $RepoPath status --short
Write-Host ""
Write-Host "Mevcut Kod Koruyucu yedekleri:"
$stashes = git -C $RepoPath stash list
if ($stashes) { $stashes } else { Write-Host "  (henüz yok)" }
Write-Host ""
Write-Host "Ayarlar > Kod Koruyucu sekmesinde repo yolu şu olmalı:" -ForegroundColor Cyan
Write-Host "  $($RepoPath -replace '\\', '/')"
