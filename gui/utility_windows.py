"""Foreground handoff for the isolated classic utility processes on Windows."""
import ctypes
from ctypes import wintypes
import sys


def _user32():
    user = ctypes.WinDLL('user32', use_last_error=True)
    user.AllowSetForegroundWindow.argtypes = [wintypes.DWORD]
    user.AllowSetForegroundWindow.restype = wintypes.BOOL
    user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user.GetWindowThreadProcessId.restype = wintypes.DWORD
    for name in ('IsWindowVisible', 'IsIconic', 'SetForegroundWindow', 'BringWindowToTop'):
        method = getattr(user, name)
        method.argtypes = [wintypes.HWND]
        method.restype = wintypes.BOOL
    user.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user.ShowWindow.restype = wintypes.BOOL
    return user


def allow_foreground(pid):
    if sys.platform == 'win32':
        _user32().AllowSetForegroundWindow(int(pid))


def raise_process_window(pid):
    if sys.platform != 'win32':
        return False
    user = _user32()
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    windows = []
    def visit(hwnd, _):
        owner = wintypes.DWORD()
        user.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == int(pid) and user.IsWindowVisible(hwnd):
            windows.append(hwnd)
        return True
    user.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
    user.EnumWindows.restype = wintypes.BOOL
    user.EnumWindows(callback_type(visit), 0)
    if not windows:
        return False
    hwnd = windows[0]
    if user.IsIconic(hwnd):
        user.ShowWindow(hwnd, 9)
    user.BringWindowToTop(hwnd)
    return bool(user.SetForegroundWindow(hwnd))


def set_window_owner(widget_id, owner_hwnd):
    """Keep a utility above its real host without making it globally topmost."""
    if sys.platform != 'win32' or not owner_hwnd:
        return False
    user = _user32()
    user.IsWindow.argtypes = [wintypes.HWND]
    user.IsWindow.restype = wintypes.BOOL
    if not user.IsWindow(int(owner_hwnd)):
        return False
    user.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
    user.GetAncestor.restype = wintypes.HWND
    hwnd = user.GetAncestor(int(widget_id), 2)  # Tk exposes the inner client HWND.
    setter = user.SetWindowLongPtrW if ctypes.sizeof(ctypes.c_void_p) == 8 else user.SetWindowLongW
    setter.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
    setter.restype = ctypes.c_ssize_t
    ctypes.set_last_error(0)
    setter(hwnd, -8, int(owner_hwnd))  # GWLP_HWNDPARENT: owner of a top-level window
    return not ctypes.get_last_error()
