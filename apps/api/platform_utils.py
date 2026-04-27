"""
Cross-platform detection and helpers.

Exposes OS flags and platform-specific mappings so the rest of the
codebase never needs to call sys.platform directly.
"""

import sys

IS_WINDOWS: bool = sys.platform == "win32"
IS_MACOS: bool = sys.platform == "darwin"
IS_LINUX: bool = sys.platform.startswith("linux")


def get_shell_allowlist() -> dict[str, str]:
    """Return a mapping of canonical command names to native OS equivalents.

    The planner always emits canonical Unix names. The shell tool
    translates them to the correct binary at execution time.
    """
    if IS_WINDOWS:
        return {
            "pwd": "cd",
            "ls": "dir",
            "find": "findstr",
            "cat": "type",
            "grep": "findstr",
        }
    # macOS and Linux use the same names
    return {
        "pwd": "pwd",
        "ls": "ls",
        "find": "find",
        "cat": "cat",
        "grep": "grep",
    }
