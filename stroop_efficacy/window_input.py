"""Keep Windows text composition out of keyboard-response windows."""

import ctypes
import sys
from ctypes import wintypes

from psychopy import logging


GA_ROOT = 2
IACE_CHILDREN = 1


def disable_window_ime(window):
    """Detach IME contexts from this native window and its existing children."""
    if sys.platform != "win32":
        return

    handle = getattr(window, "_hw_handle", None)
    if not handle:
        return

    get_ancestor = ctypes.windll.user32.GetAncestor
    get_ancestor.argtypes = (wintypes.HWND, wintypes.UINT)
    get_ancestor.restype = wintypes.HWND

    associate_context = ctypes.windll.imm32.ImmAssociateContextEx
    associate_context.argtypes = (wintypes.HWND, wintypes.HANDLE, wintypes.DWORD)
    associate_context.restype = wintypes.BOOL

    # PsychoPy's pyglet handle can point to the drawing child, while the
    # top-level window can also receive focus. Both belong to this task window.
    root = get_ancestor(handle, GA_ROOT)
    if root and associate_context(root, None, 0):
        if associate_context(root, None, IACE_CHILDREN):
            return
    logging.warning("实验窗口无法停用输入法。开场前请切换到英文输入后重试。")
