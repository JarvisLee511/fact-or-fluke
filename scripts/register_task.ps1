# Registers the daily run: every 30 minutes from 06:00 to 12:00 (laptop local time), no console window.
# scripts/daily.py exits at once when the day is already done or the data is not complete yet.
$root = Split-Path -Parent $PSScriptRoot
$py = Join-Path $root ".venv\Scripts\pythonw.exe"
$script = Join-Path $root "scripts\daily.py"

$action = New-ScheduledTaskAction -Execute $py -Argument "`"$script`"" -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -Daily -At 6:00AM
$trigger.Repetition = (New-ScheduledTaskTrigger -Once -At 6:00AM -RepetitionInterval (New-TimeSpan -Minutes 30) `
    -RepetitionDuration (New-TimeSpan -Hours 6)).Repetition
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
    -WakeToRun -ExecutionTimeLimit (New-TimeSpan -Hours 2) -MultipleInstances IgnoreNew

Register-ScheduledTask -TaskName "Fact or Fluke Daily" -TaskPath "\FactOrFluke\" -Action $action -Trigger $trigger `
    -Settings $settings -Description "Fact or Fluke: fetch last night's NBA data, update fun facts, predict today, email" `
    -Force | Out-Null
Get-ScheduledTask -TaskPath "\FactOrFluke\" | Select-Object TaskName, State
