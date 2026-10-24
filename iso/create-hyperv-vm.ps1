# Create and start a Hyper-V VM that boots the Sourabh OS ISO.
# Run in an elevated PowerShell:  .\iso\create-hyperv-vm.ps1 -Iso .\out\sourabhos-amd64.iso
param(
    [Parameter(Mandatory = $true)][string]$Iso,
    [string]$Name = "Sourabh OS",
    [int64]$MemoryGB = 8,       # AI models live in RAM: 8 GB runs 3B models comfortably
    [int64]$DiskGB = 64,        # room for downloaded models
    [string]$Switch = "Default Switch",
    [string]$Resolution = "1600x900",
    [int]$Cpus = 4               # more cores = faster CPU inference
)
$ErrorActionPreference = "Stop"
$Iso = (Resolve-Path $Iso).Path
$vhd = Join-Path (Get-VMHost).VirtualHardDiskPath "$Name.vhdx"

New-VM -Name $Name -Generation 2 -MemoryStartupBytes ($MemoryGB * 1GB) `
       -NewVHDPath $vhd -NewVHDSizeBytes ($DiskGB * 1GB) -SwitchName $Switch | Out-Null
Set-VMProcessor -VMName $Name -Count $Cpus
Set-VMMemory -VMName $Name -DynamicMemoryEnabled $false
# Debian's bootloader isn't signed with the Windows key: turn Secure Boot off
Set-VMFirmware -VMName $Name -EnableSecureBoot Off
$dvd = Add-VMDvdDrive -VMName $Name -Path $Iso -Passthru
Set-VMFirmware -VMName $Name -FirstBootDevice $dvd
$w, $h = $Resolution.Split("x")
Set-VMVideo -VMName $Name -HorizontalResolution $w -VerticalResolution $h -ResolutionType Single
Set-VM -Name $Name -EnhancedSessionTransportType HvSocket -AutomaticCheckpointsEnabled $false

Start-VM -Name $Name
vmconnect.exe localhost $Name
Write-Host "VM '$Name' started. Choose 'Live system' to try it, or 'Install' to install to the virtual disk."
