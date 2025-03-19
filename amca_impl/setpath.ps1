$newDir = "$env:LOCALAPPDATA\amca\bin"
$oldPath = [Environment]::GetEnvironmentVariable("PATH", "User")
[Environment]::SetEnvironmentVariable("PATH", $oldPath + ";" + $newDir, "User")
Write-Output "PATH set successfully."