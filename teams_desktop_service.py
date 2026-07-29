import os
import re
import json
import subprocess
import time
from typing import Dict, Any, List, Optional, Tuple

def list_teams_desktop_windows() -> List[Dict[str, Any]]:
    """Scan top-level Windows desktop windows for open Microsoft Teams or Teams Web instances."""
    ps_script = """
    Add-Type -AssemblyName UIAutomationClient
    Add-Type -AssemblyName UIAutomationTypes

    $root = [System.Windows.Automation.AutomationElement]::RootElement
    $condition = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ControlTypeProperty, [System.Windows.Automation.ControlType]::Window)
    $windows = $root.FindAll([System.Windows.Automation.TreeScope]::Children, $condition)

    $results = @()
    foreach ($win in $windows) {
        $name = $win.Current.Name
        if ($name -and ($name -match 'Teams' -or $name -match 'Microsoft Teams' -or $name -match 'Chat')) {
            $results += @{
                "title" = $name
                "handle" = $win.Current.NativeWindowHandle
                "process_id" = $win.Current.ProcessId
            }
        }
    }
    $results | ConvertTo-Json -Compress
    """
    
    try:
        res = subprocess.run(["powershell", "-NoProfile", "-Command", ps_script], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=10)
        output = res.stdout.strip()
        if output:
            parsed = json.loads(output)
            if isinstance(parsed, dict):
                return [parsed]
            elif isinstance(parsed, list):
                return parsed
    except Exception as e:
        print(f"Error scanning Teams windows: {e}")
        
    return []


def capture_teams_chat_from_window(window_title: Optional[str] = None, delay_seconds: int = 0, auto_scroll_up: bool = True, scroll_depth: str = "standard") -> Tuple[bool, str, List[str]]:
    """
    Robust Desktop Automation Capture with Hardware Keystrokes:
    1. Pauses for delay_seconds if specified to give user time to switch to Teams.
    2. Optional Auto-Scroll UP (PageUp / Ctrl+Home) to trigger dynamic loading of earlier chat history.
       scroll_depth: 'standard' (~40 msgs), 'deep' (~100 msgs), 'max' (~200 msgs), 'top' (jump to top).
    3. Synthesizes OS hardware keystrokes (Ctrl+A, Ctrl+C) on active window / Teams window.
    4. Reads clipboard text and parses chat messages.
    """
    if delay_seconds > 0:
        time.sleep(delay_seconds)

    target_pattern = window_title if window_title else "Teams"
    scroll_flag = "true" if auto_scroll_up else "false"
    depth_clean = scroll_depth.lower() if scroll_depth else "standard"
    
    ps_script = f"""
    Add-Type -AssemblyName System.Windows.Forms
    Add-Type -AssemblyName UIAutomationClient
    Add-Type -AssemblyName UIAutomationTypes

    $sig = @'
    [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
    [DllImport("user32.dll")] public static extern void keybd_event(byte bVk, byte bScan, uint dwFlags, uint dwExtraInfo);
'@
    $win32 = Add-Type -MemberDefinition $sig -Name "Win32HWFocus" -Namespace Win32Utils -PassThru

    # Save current browser / app window handle
    $origHWnd = $win32::GetForegroundWindow()

    # Locate Teams window handle
    $teamsHWnd = [IntPtr]::Zero

    # Search via Get-Process
    $proc = Get-Process | Where-Object {{ $_.ProcessName -like '*teams*' }} | Where-Object {{ $_.MainWindowHandle -ne 0 }} | Select-Object -First 1
    if ($proc) {{
        $teamsHWnd = $proc.MainWindowHandle
    }}

    # Search via UI Automation if no process handle
    if ($teamsHWnd -eq [IntPtr]::Zero) {{
        $root = [System.Windows.Automation.AutomationElement]::RootElement
        $condition = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ControlTypeProperty, [System.Windows.Automation.ControlType]::Window)
        $windows = $root.FindAll([System.Windows.Automation.TreeScope]::Children, $condition)

        foreach ($win in $windows) {{
            $name = $win.Current.Name
            if ($name -and ($name -match '{target_pattern}' -or $name -match 'Microsoft Teams' -or $name -match 'Teams')) {{
                $teamsHWnd = [IntPtr]$win.Current.NativeWindowHandle
                break
            }}
        }}
    }}

    $capturedText = ""

    if ($teamsHWnd -ne [IntPtr]::Zero) {{
        # 1. Bring Teams window to foreground
        $win32::ShowWindow($teamsHWnd, 9) # SW_RESTORE
        $win32::SetForegroundWindow($teamsHWnd)
        Start-Sleep -Milliseconds 450

        # 2. Auto-Scroll UP to load earlier conversation history
        if ("{scroll_flag}" -eq "true") {{
            if ("{depth_clean}" -eq "top") {{
                # Ctrl + Home to jump to very top of chat
                $win32::keybd_event(0x11, 0, 0, 0)
                $win32::keybd_event(0x24, 0, 0, 0)
                $win32::keybd_event(0x24, 0, 2, 0)
                $win32::keybd_event(0x11, 0, 2, 0)
                Start-Sleep -Milliseconds 400
            }} else {{
                $scrollCount = 8
                if ("{depth_clean}" -eq "deep") {{ $scrollCount = 20 }}
                elseif ("{depth_clean}" -eq "max") {{ $scrollCount = 600 }}

                for ($i = 0; $i -lt $scrollCount; $i++) {{
                    $win32::keybd_event(0x21, 0, 0, 0) # PageUp DOWN
                    $win32::keybd_event(0x21, 0, 2, 0) # PageUp UP
                    Start-Sleep -Milliseconds 120
                }}
                Start-Sleep -Milliseconds 300
            }}
        }}

        # 3. Hardware Keystrokes for Ctrl+A
        $win32::keybd_event(0x11, 0, 0, 0) # Ctrl DOWN
        $win32::keybd_event(0x41, 0, 0, 0) # A DOWN
        $win32::keybd_event(0x41, 0, 2, 0) # A UP
        $win32::keybd_event(0x11, 0, 2, 0) # Ctrl UP

        Start-Sleep -Milliseconds 200

        # 4. Hardware Keystrokes for Ctrl+C
        $win32::keybd_event(0x11, 0, 0, 0) # Ctrl DOWN
        $win32::keybd_event(0x43, 0, 0, 0) # C DOWN
        $win32::keybd_event(0x43, 0, 2, 0) # C UP
        $win32::keybd_event(0x11, 0, 2, 0) # Ctrl UP

        Start-Sleep -Milliseconds 300

        $capturedText = [System.Windows.Forms.Clipboard]::GetText()

        # 4. Restore original browser / app window focus
        if ($origHWnd -ne [IntPtr]::Zero) {{
            $win32::SetForegroundWindow($origHWnd)
        }}
    }}

    # Fallback to UI Automation tree if clipboard is empty
    if (-not $capturedText -or $capturedText.Trim().Length -lt 10) {{
        $root = [System.Windows.Automation.AutomationElement]::RootElement
        $condition = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ControlTypeProperty, [System.Windows.Automation.ControlType]::Window)
        $windows = $root.FindAll([System.Windows.Automation.TreeScope]::Children, $condition)

        $targetWin = $null
        foreach ($win in $windows) {{
            $name = $win.Current.Name
            if ($name -and ($name -match '{target_pattern}' -or $name -match 'Teams')) {{
                $targetWin = $win
                break
            }}
        }}

        if ($targetWin) {{
            $textCondition = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ControlTypeProperty, [System.Windows.Automation.ControlType]::Text)
            $elements = $targetWin.FindAll([System.Windows.Automation.TreeScope]::Subtree, $textCondition)

            $lines = @()
            foreach ($el in $elements) {{
                $val = $el.Current.Name
                if ($val -and $val.Trim().Length -gt 2) {{
                    $lines += $val.Trim()
                }}
            }}
            $capturedText = $lines -join "`n"
        }}
    }}

    if (-not $capturedText -or $capturedText.Trim().Length -lt 5) {{
        Write-Output "ERROR: Teams window was not found or focus could not be activated."
        exit 1
    }}

    Write-Output $capturedText
    """
    
    try:
        res = subprocess.run(["powershell", "-NoProfile", "-Command", ps_script], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=15)
        output = res.stdout.strip()
        
        if "ERROR:" in output or not output:
            return False, "Could not automatically switch to Microsoft Teams window. Make sure Microsoft Teams is running and visible on your taskbar.", []
            
        lines = [line.strip() for line in output.split('\n') if line.strip()]
        
        ignore_nav = {'search', 'activity', 'chat', 'teams', 'calendar', 'calls', 'files', 'apps', 'help', 'settings', 'more options', 'reply', 'send'}
        clean_lines = [l for l in lines if l.lower() not in ignore_nav]

        transcript = "\n".join(clean_lines)
        return True, transcript, clean_lines

    except Exception as e:
        return False, f"Hardware keystroke automation capture error: {str(e)}", []
