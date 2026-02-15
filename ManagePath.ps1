<#
.SYNOPSIS
    Adds or removes a directory from the System or User PATH variable.

.DESCRIPTION
    Called by context menu registry entries (AddToPath.reg) in two modes:

    1. Direct mode  — pass -Scope and -Action to perform a single operation.
       For Machine scope, the script self-elevates via UAC if needed.

    2. GUI mode     — omit -Scope and -Action to open a WinForms dialog
       showing live status with Add/Remove buttons for both scopes.

.PARAMETER Directory
    The directory path to manage.

.PARAMETER Scope
    "Machine" (System PATH) or "User" (User PATH). Omit for GUI mode.

.PARAMETER Action
    "Add" or "Remove". Omit for GUI mode.

.PARAMETER Elevated
    Internal flag for the self-elevation re-launch. Do not pass manually.

.EXAMPLE
    .\ManagePath.ps1 -Directory "C:\Tools" -Scope User -Action Add
    .\ManagePath.ps1 -Directory "C:\Tools"
#>

#Requires -Version 7.5

param(
    [Parameter(Mandatory)]
    [string]$Directory,

    [ValidateSet("Machine", "User")]
    [string]$Scope,

    [ValidateSet("Add", "Remove")]
    [string]$Action,

    [switch]$Elevated
)

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

# ---------------------------------------------------------------------------
# Direct mode: -Scope and -Action both provided
# ---------------------------------------------------------------------------
if ($Scope -and $Action) {

    # Machine scope needs elevation — self-elevate if we're not already
    if ($Scope -eq "Machine" -and -not $Elevated) {
        $isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
            ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

        if (-not $isAdmin) {
            Start-Process pwsh -Verb RunAs -ArgumentList @(
                "-ExecutionPolicy", "Bypass",
                "-NoProfile",
                "-File", "`"$PSCommandPath`"",
                "-Directory", "`"$Directory`"",
                "-Scope", $Scope,
                "-Action", $Action,
                "-Elevated"
            ) -Wait
            exit $LASTEXITCODE
        }
    }

    # Perform the PATH modification
    $current = [System.Environment]::GetEnvironmentVariable("Path", $Scope)
    $parts = ($current -split ";" | Where-Object { $_ -ne "" })
    $scopeLabel = if ($Scope -eq "Machine") { "System" } else { "User" }

    switch ($Action) {
        "Add" {
            if ($parts -contains $Directory) {
                [System.Windows.Forms.MessageBox]::Show(
                    "$Directory is already in $scopeLabel PATH.",
                    "Manage PATH", 0, 64) | Out-Null
            }
            else {
                $parts += $Directory
                [System.Environment]::SetEnvironmentVariable("Path", ($parts -join ";"), $Scope)
                [System.Windows.Forms.MessageBox]::Show(
                    "Added $Directory to $scopeLabel PATH.`nRestart terminals to pick up the change.",
                    "Manage PATH", 0, 64) | Out-Null
            }
        }
        "Remove" {
            if (-not ($parts -contains $Directory)) {
                [System.Windows.Forms.MessageBox]::Show(
                    "$Directory is not in $scopeLabel PATH.",
                    "Manage PATH", 0, 48) | Out-Null
            }
            else {
                $filtered = $parts | Where-Object { $_ -ne $Directory }
                [System.Environment]::SetEnvironmentVariable("Path", ($filtered -join ";"), $Scope)
                [System.Windows.Forms.MessageBox]::Show(
                    "Removed $Directory from $scopeLabel PATH.`nRestart terminals to pick up the change.",
                    "Manage PATH", 0, 64) | Out-Null
            }
        }
    }
    exit 0
}

# ---------------------------------------------------------------------------
# GUI mode: no Scope/Action — show interactive dialog
# ---------------------------------------------------------------------------

function Get-PathStatus {
    $sysPath = [System.Environment]::GetEnvironmentVariable("Path", "Machine")
    $usrPath = [System.Environment]::GetEnvironmentVariable("Path", "User")
    return @{
        InSystem = (($sysPath -split ";" | Where-Object { $_ -ne "" }) -contains $Directory)
        InUser   = (($usrPath -split ";" | Where-Object { $_ -ne "" }) -contains $Directory)
    }
}

function Invoke-PathAction {
    param([string]$ActionScope, [string]$ActionType)
    Start-Process pwsh -ArgumentList @(
        "-ExecutionPolicy", "Bypass", "-NoProfile",
        "-File", "`"$PSCommandPath`"",
        "-Directory", "`"$Directory`"",
        "-Scope", $ActionScope,
        "-Action", $ActionType
    ) -Wait -WindowStyle Hidden
}

# --- Form ---
$form = New-Object System.Windows.Forms.Form
$form.Text = "Manage PATH"
$form.Size = New-Object System.Drawing.Size(460, 340)
$form.StartPosition = "CenterScreen"
$form.FormBorderStyle = "FixedDialog"
$form.MaximizeBox = $false
$form.MinimizeBox = $false
$form.Font = New-Object System.Drawing.Font("Segoe UI", 9)

$lblDir = New-Object System.Windows.Forms.Label
$lblDir.Text = "Directory:"
$lblDir.Location = New-Object System.Drawing.Point(15, 15)
$lblDir.AutoSize = $true
$form.Controls.Add($lblDir)

$txtDir = New-Object System.Windows.Forms.TextBox
$txtDir.Text = $Directory
$txtDir.Location = New-Object System.Drawing.Point(15, 35)
$txtDir.Size = New-Object System.Drawing.Size(415, 24)
$txtDir.ReadOnly = $true
$txtDir.BackColor = [System.Drawing.SystemColors]::Window
$form.Controls.Add($txtDir)

# System PATH group
$grpSys = New-Object System.Windows.Forms.GroupBox
$grpSys.Text = "System PATH (requires admin)"
$grpSys.Location = New-Object System.Drawing.Point(15, 70)
$grpSys.Size = New-Object System.Drawing.Size(415, 90)
$form.Controls.Add($grpSys)

$lblSysStatus = New-Object System.Windows.Forms.Label
$lblSysStatus.Location = New-Object System.Drawing.Point(10, 25)
$lblSysStatus.AutoSize = $true
$grpSys.Controls.Add($lblSysStatus)

$btnSysAdd = New-Object System.Windows.Forms.Button
$btnSysAdd.Text = "Add"
$btnSysAdd.Size = New-Object System.Drawing.Size(90, 30)
$btnSysAdd.Location = New-Object System.Drawing.Point(10, 50)
$grpSys.Controls.Add($btnSysAdd)

$btnSysRemove = New-Object System.Windows.Forms.Button
$btnSysRemove.Text = "Remove"
$btnSysRemove.Size = New-Object System.Drawing.Size(90, 30)
$btnSysRemove.Location = New-Object System.Drawing.Point(110, 50)
$grpSys.Controls.Add($btnSysRemove)

# User PATH group
$grpUsr = New-Object System.Windows.Forms.GroupBox
$grpUsr.Text = "User PATH"
$grpUsr.Location = New-Object System.Drawing.Point(15, 170)
$grpUsr.Size = New-Object System.Drawing.Size(415, 90)
$form.Controls.Add($grpUsr)

$lblUsrStatus = New-Object System.Windows.Forms.Label
$lblUsrStatus.Location = New-Object System.Drawing.Point(10, 25)
$lblUsrStatus.AutoSize = $true
$grpUsr.Controls.Add($lblUsrStatus)

$btnUsrAdd = New-Object System.Windows.Forms.Button
$btnUsrAdd.Text = "Add"
$btnUsrAdd.Size = New-Object System.Drawing.Size(90, 30)
$btnUsrAdd.Location = New-Object System.Drawing.Point(10, 50)
$grpUsr.Controls.Add($btnUsrAdd)

$btnUsrRemove = New-Object System.Windows.Forms.Button
$btnUsrRemove.Text = "Remove"
$btnUsrRemove.Size = New-Object System.Drawing.Size(90, 30)
$btnUsrRemove.Location = New-Object System.Drawing.Point(110, 50)
$grpUsr.Controls.Add($btnUsrRemove)

$btnClose = New-Object System.Windows.Forms.Button
$btnClose.Text = "Close"
$btnClose.Size = New-Object System.Drawing.Size(90, 30)
$btnClose.Location = New-Object System.Drawing.Point(340, 268)
$btnClose.Add_Click({ $form.Close() })
$form.Controls.Add($btnClose)
$form.CancelButton = $btnClose

function Update-UI {
    $status = Get-PathStatus
    if ($status.InSystem) {
        $lblSysStatus.Text = [char]0x2705 + "  Currently in System PATH"
        $lblSysStatus.ForeColor = [System.Drawing.Color]::DarkGreen
        $btnSysAdd.Enabled = $false
        $btnSysRemove.Enabled = $true
    } else {
        $lblSysStatus.Text = [char]0x274C + "  Not in System PATH"
        $lblSysStatus.ForeColor = [System.Drawing.Color]::DarkRed
        $btnSysAdd.Enabled = $true
        $btnSysRemove.Enabled = $false
    }
    if ($status.InUser) {
        $lblUsrStatus.Text = [char]0x2705 + "  Currently in User PATH"
        $lblUsrStatus.ForeColor = [System.Drawing.Color]::DarkGreen
        $btnUsrAdd.Enabled = $false
        $btnUsrRemove.Enabled = $true
    } else {
        $lblUsrStatus.Text = [char]0x274C + "  Not in User PATH"
        $lblUsrStatus.ForeColor = [System.Drawing.Color]::DarkRed
        $btnUsrAdd.Enabled = $true
        $btnUsrRemove.Enabled = $false
    }
}

$btnSysAdd.Add_Click({ Invoke-PathAction "Machine" "Add"; Update-UI })
$btnSysRemove.Add_Click({ Invoke-PathAction "Machine" "Remove"; Update-UI })
$btnUsrAdd.Add_Click({ Invoke-PathAction "User" "Add"; Update-UI })
$btnUsrRemove.Add_Click({ Invoke-PathAction "User" "Remove"; Update-UI })

Update-UI
[void]$form.ShowDialog()
