$ErrorActionPreference = "Stop"

$Distro      = "Ubuntu"
$LinuxUser   = "mcpagent"
$WindowsRepo = "C:\Users\samue\Documents\GitHub\local-mcp-server"
$WslConfig   = "$env:USERPROFILE\.wslconfig"
$DiskBackup  = "$WindowsRepo\vm\disks\ubuntu-mcp-baseline.tar"

Write-Host "============================================================================" -ForegroundColor Cyan
Write-Host "         WSL2 ISOLATED MCP RUNTIME - ONE-SHOT PROVISIONING SCRIPT           " -ForegroundColor Cyan
Write-Host "============================================================================" -ForegroundColor Cyan

# -----------------------------------------------------------------------------
# 1. Cap WSL2 Memory & CPU on Windows Host
# -----------------------------------------------------------------------------
Write-Host "`n[1/6] Configuring Windows .wslconfig resource limits..." -ForegroundColor Yellow
@"
[wsl2]
memory=2GB
processors=2
swap=1GB
"@ | Set-Content -Path $WslConfig -Encoding ASCII
Write-Host "  [OK] Saved $WslConfig (2GB RAM limit)" -ForegroundColor Green

# -----------------------------------------------------------------------------
# 2. Ensure WSL2 & Ubuntu Distro Are Installed
# -----------------------------------------------------------------------------
Write-Host "`n[2/6] Checking WSL2 '$Distro' installation..." -ForegroundColor Yellow
$installed = wsl --list --quiet 2>$null | ForEach-Object { $_.Trim() -replace "`0", "" }
if ($installed -notcontains $Distro) {
    Write-Host "  [INFO] Installing $Distro via WSL (follow any OS prompts if shown)..."
    wsl --install -d $Distro --no-launch
    ubuntu install --root
}
Write-Host "  [OK] $Distro is available." -ForegroundColor Green

# -----------------------------------------------------------------------------
# 3. Install System Packages (Python, Venv, Git, GitHub CLI) & Lock Down /mnt/c
# -----------------------------------------------------------------------------
Write-Host "`n[3/6] Provisioning Linux packages, $LinuxUser account, and FS isolation..." -ForegroundColor Yellow
$rootSetup = @'
set -e
export DEBIAN_FRONTEND=noninteractive

apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-pip git curl ca-certificates gnupg

# Install official GitHub CLI (gh)
mkdir -p -m 755 /etc/apt/keyrings
curl -fsSL https://github.com | tee /etc/apt/keyrings/githubcli-archive-keyring.gpg > /dev/null
chmod go+r /etc/apt/keyrings/githubcli-archive-keyring.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg] https://github.com stable main" | tee /etc/apt/sources.list.d/github-cli.list > /dev/null
apt-get update -qq
apt-get install -y -qq gh

# Create restricted non-sudo user if it doesn't exist
if ! id -u mcpagent >/dev/null 2>&1; then
    adduser --disabled-password --gecos "" mcpagent
fi

# Disable Windows C:\ automounting & set default user
cat << 'EOF' > /etc/wsl.conf
[automount]
enabled = false

[user]
default = mcpagent
EOF
'@

($rootSetup -replace "`r`n", "`n") | wsl -d $Distro -u root -- bash -s
Write-Host "  [OK] Packages installed, '$LinuxUser' created, and /etc/wsl.conf locked down." -ForegroundColor Green

# -----------------------------------------------------------------------------
# 4. Restart WSL2 to Enforce /mnt/c Isolation
# -----------------------------------------------------------------------------
Write-Host "`n[4/6] Restarting WSL2 to apply filesystem isolation..." -ForegroundColor Yellow
wsl --shutdown
Start-Sleep -Seconds 2
Write-Host "  [OK] WSL2 restarted with /mnt/c unmounted." -ForegroundColor Green

# -----------------------------------------------------------------------------
# 5. Stream Repository (Code, .env, data/channels.db) & Build Python .venv
# -----------------------------------------------------------------------------
Write-Host "`n[5/6] Streaming local repository into WSL2 and building .venv..." -ForegroundColor Yellow
$tempTar = "$env:TEMP\local-mcp-server-payload.tar"
if (Test-Path $tempTar) { Remove-Item $tempTar -Force }

# Use Windows built-in tar.exe to archive project while excluding heavy/host folders
tar -cf $tempTar `
    --exclude=".git" `
    --exclude=".venv" `
    --exclude="venv" `
    --exclude="__pycache__" `
    --exclude="vm/disks/*.tar" `
    -C $WindowsRepo .

$userSetup = @'
set -e
mkdir -p ~/local-mcp-server
tar -xf - -C ~/local-mcp-server
cd ~/local-mcp-server

# Fix Windows CRLF line endings on shell scripts or .env if present
sed -i 's/\r$//' .env 2>/dev/null || true
find . -name "*.sh" -exec sed -i 's/\r$//' {} + 2>/dev/null || true

python3 -m venv .venv
.venv/bin/pip install --upgrade pip -q
.venv/bin/pip install -r requirements.txt -q
mkdir -p data repos
'@

# Pipe the tar archive directly into WSL2 stdin
cmd /c "type `"$tempTar`" | wsl -d $Distro -u $LinuxUser -- bash -c `"$(($userSetup -replace "`r`n", "`n") -replace '"', '\"')`""
Remove-Item $tempTar -Force
Write-Host "  [OK] Repository, .env, channels.db, and .venv ready inside WSL2." -ForegroundColor Green

# -----------------------------------------------------------------------------
# 6. Export Clean Baseline Snapshot to vm\disks\
# -----------------------------------------------------------------------------
Write-Host "`n[6/6] Exporting clean baseline VM snapshot..." -ForegroundColor Yellow
New-Item -ItemType Directory -Force -Path "$WindowsRepo\vm\disks" | Out-Null
wsl --shutdown
wsl --export $Distro $DiskBackup
Write-Host "  [OK] Snapshot saved to $DiskBackup" -ForegroundColor Green

Write-Host "`n============================================================================" -ForegroundColor Cyan
Write-Host " PROVISIONING COMPLETE!" -ForegroundColor Green
Write-Host "============================================================================" -ForegroundColor Cyan
Write-Host "Next steps:"
Write-Host "  1. Authenticate GitHub CLI inside the VM (use a repo-scoped Fine-Grained PAT):"
Write-Host "     wsl -d $Distro -u $LinuxUser -- gh auth login" -ForegroundColor White
Write-Host "  2. Close your old Windows Uvicorn window and run your updated start_server.bat."
