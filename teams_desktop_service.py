import os
import re
import json
import time
import ctypes
import subprocess
from ctypes import wintypes
from typing import Dict, Any, List, Optional, Tuple

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

SW_RESTORE = 9
VK_CONTROL = 0x11
VK_A = 0x41
VK_C = 0x43
VK_PRIOR = 0x21 # PageUp
VK_HOME = 0x24  # Home
KEYEVENTF_KEYUP = 0x0002

def press_key(vk: int):
    """Synthesize hardware key press and release."""
    user32.keybd_event(vk, 0, 0, 0)
    time.sleep(0.04)
    user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)

def press_combo(vk1: int, vk2: int):
    """Synthesize hardware key combination (e.g. Ctrl+A, Ctrl+C)."""
    user32.keybd_event(vk1, 0, 0, 0)
    user32.keybd_event(vk2, 0, 0, 0)
    time.sleep(0.04)
    user32.keybd_event(vk2, 0, KEYEVENTF_KEYUP, 0)
    user32.keybd_event(vk1, 0, KEYEVENTF_KEYUP, 0)

def find_teams_window_handle(target_pattern: Optional[str] = None) -> int:
    """Find NativeWindowHandle for open Microsoft Teams window."""
    teams_hwnd = [0]
    pattern = target_pattern.lower() if target_pattern else "teams"

    def enum_proc(hwnd, lparam):
        if user32.IsWindowVisible(hwnd):
            length = user32.GetWindowTextLengthW(hwnd)
            if length > 0:
                buff = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buff, length + 1)
                title = buff.value.lower()
                if pattern in title or "teams" in title or "chat" in title:
                    teams_hwnd[0] = hwnd
                    return False
        return True

    WINFUNCTYPE = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows(WINFUNCTYPE(enum_proc), 0)
    return teams_hwnd[0]

def list_teams_desktop_windows() -> List[Dict[str, Any]]:
    """Scan top-level Windows desktop windows for open Microsoft Teams or Teams Web instances."""
    results = []
    
    def enum_proc(hwnd, lparam):
        if user32.IsWindowVisible(hwnd):
            length = user32.GetWindowTextLengthW(hwnd)
            if length > 0:
                buff = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buff, length + 1)
                title = buff.value
                if any(kw in title.lower() for kw in ['teams', 'microsoft teams', 'chat']):
                    results.append({
                        "title": title,
                        "handle": hwnd,
                        "process_id": 0
                    })
        return True

    WINFUNCTYPE = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows(WINFUNCTYPE(enum_proc), 0)
    return results

def get_system_clipboard_text() -> str:
    """Extract current text from Windows system clipboard."""
    try:
        res = subprocess.run(["powershell", "-NoProfile", "-Command", "Get-Clipboard"], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=5)
        return res.stdout.strip()
    except Exception as e:
        print(f"Error fetching clipboard: {e}")
        return ""

def capture_teams_chat_from_window(
    window_title: Optional[str] = None,
    delay_seconds: int = 0,
    auto_scroll_up: bool = True,
    scroll_depth: str = "standard"
) -> Tuple[bool, str, List[str]]:
    """
    Pure Python Win32 Keystroke Capture Engine:
    1. Pauses for delay_seconds if specified to give user time to switch to Teams.
    2. Brings Teams window to foreground (if found).
    3. Triggers hardware Auto-Scroll UP (PageUp / Ctrl+Home) to dynamically load earlier message history.
    4. Triggers hardware Ctrl+A and Ctrl+C keystrokes.
    5. Reads text from system clipboard and parses chat messages.
    """
    if delay_seconds > 0:
        time.sleep(delay_seconds)

    # 1. Locate and activate Teams window if possible
    hwnd = find_teams_window_handle(window_title)
    if hwnd:
        user32.ShowWindow(hwnd, SW_RESTORE)
        user32.SetForegroundWindow(hwnd)
        time.sleep(0.3)

    # 2. Auto-Scroll UP to load earlier conversation history
    if auto_scroll_up:
        depth = scroll_depth.lower() if scroll_depth else "standard"
        if depth == "top":
            press_combo(VK_CONTROL, VK_HOME)
            time.sleep(0.4)
        else:
            scroll_count = 8
            if depth == "deep":
                scroll_count = 20
            elif depth == "max":
                scroll_count = 600
                
            for _ in range(scroll_count):
                press_key(VK_PRIOR)
                time.sleep(0.06)
            time.sleep(0.3)

    # 3. Hardware Keystrokes for Ctrl+A & Ctrl+C
    time.sleep(0.15)
    press_combo(VK_CONTROL, VK_A)
    time.sleep(0.15)
    press_combo(VK_CONTROL, VK_C)
    time.sleep(0.25)

    # 4. Extract Clipboard Text
    captured_text = get_system_clipboard_text()
    
    if not captured_text or len(captured_text.strip()) < 5:
        return False, "Could not capture text from Microsoft Teams window. Make sure Microsoft Teams is open and active on your screen.", []

    lines = [line.strip() for line in captured_text.split('\n') if line.strip()]
    ignore_nav = {'search', 'activity', 'chat', 'teams', 'calendar', 'calls', 'files', 'apps', 'help', 'settings', 'more options', 'reply', 'send'}
    clean_lines = [l for l in lines if l.lower() not in ignore_nav]

    transcript = "\n".join(clean_lines)
    return True, transcript, clean_lines
