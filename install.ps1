$ErrorActionPreference = 'Stop'

Write-Host "Deploying Codex & Hermes Enterprise Hindsight Memory..."

$USER_HOME = [Environment]::GetFolderPath('UserProfile')
$PLUGINS_DIR = Join-Path $USER_HOME "plugins"
$CODEX_DIR = Join-Path $USER_HOME ".codex"

# 1. Copy Plugins
Write-Host "1. Installing Plugins..."
if (!(Test-Path $PLUGINS_DIR)) { New-Item -ItemType Directory -Force -Path $PLUGINS_DIR | Out-Null }
Copy-Item -Path ".\plugins\*" -Destination $PLUGINS_DIR -Recurse -Force

# 2. Copy Rule Files
Write-Host "2. Deploying Rule Files..."
if (!(Test-Path $CODEX_DIR)) { New-Item -ItemType Directory -Force -Path $CODEX_DIR | Out-Null }
Copy-Item -Path ".\codex_rules\*" -Destination $CODEX_DIR -Force

# 3. Register Scheduled Tasks
Write-Host "3. Registering Enterprise Scheduled Tasks..."
$py = "C:\Users\123\AppData\Local\Programs\Python\Python313\python.exe"

function Register-HindsightTask ($TaskName, $ScriptPath, $Time) {
    schtasks.exe /Delete /TN $TaskName /F 2>$null
    $Action = ""$py" "$ScriptPath""
    schtasks.exe /Create /TN $TaskName /SC DAILY /ST $Time /TR $Action /F | Out-Null
    Write-Host " -> Registered $TaskName at $Time"
}

Register-HindsightTask "HindsightEnterpriseHealth" (Join-Path $PLUGINS_DIR "hindsight-memory\scripts\enterprise_health.py") "03:10"
Register-HindsightTask "HindsightEnterpriseBackup" (Join-Path $PLUGINS_DIR "hindsight-memory\scripts\enterprise_backup.py") "03:15"
Register-HindsightTask "CodexAgentsGuard" (Join-Path $PLUGINS_DIR "hindsight-memory\scripts\guard_agents.py") "03:20"
Register-HindsightTask "HermesAgentsGuard" (Join-Path $PLUGINS_DIR "hermes-hindsight-memory\scripts\guard_hermes_agents.py") "03:25"
Register-HindsightTask "CodexHindsightMaintenance" (Join-Path $PLUGINS_DIR "hindsight-memory\scripts\maintain_hindsight.py") "03:30"
Register-HindsightTask "HermesHindsightMaintenance" (Join-Path $PLUGINS_DIR "hermes-hindsight-memory\scripts\maintain_hindsight.py") "03:45"

Write-Host "Deployment Complete! Please ensure Docker is running with the correct Hindsight container." -ForegroundColor Green