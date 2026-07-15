$ErrorActionPreference = 'Continue'
$out = 'D:\4thSem\smartAttendance\feature_state.txt'
$vmp = (Get-WindowsOptionalFeature -Online -FeatureName VirtualMachinePlatform).State
$wsl = (Get-WindowsOptionalFeature -Online -FeatureName Microsoft-Windows-Subsystem-Linux).State
"VMP=$vmp WSL=$wsl" | Out-File -Encoding ascii $out
