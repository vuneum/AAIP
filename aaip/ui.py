"""
AAIP UI Module - Stub implementation for test compatibility

NOTE: This is a stub module created to fix test import failures.
The actual implementation should be developed separately.
"""

import re


def visible_len(text: str) -> int:
    """
    Get the visible length of text, ignoring ANSI escape codes.
    
    Tests expect this to strip color codes and return actual character count.
    """
    # Strip ANSI escape sequences
    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    stripped = ansi_escape.sub('', text)
    return len(stripped)


def green(text: str) -> str:
    """Return text wrapped in green ANSI escape codes"""
    return f"\033[32m{text}\033[0m"


def red(text: str) -> str:
    """Return text wrapped in red ANSI escape codes"""
    return f"\033[31m{text}\033[0m"


def yellow(text: str) -> str:
    """Return text wrapped in yellow ANSI escape codes"""
    return f"\033[33m{text}\033[0m"


def blue(text: str) -> str:
    """Return text wrapped in blue ANSI escape codes"""
    return f"\033[34m{text}\033[0m"


def bold(text: str) -> str:
    """Return text wrapped in bold ANSI escape codes"""
    return f"\033[1m{text}\033[0m"


def summary(rows):
    """
    Print a summary table with aligned borders.
    
    This is a stub implementation for test compatibility.
    """
    if not rows:
        return
        
    # Find max key length
    max_key_len = max(len(str(key)) for key, _ in rows)
    
    # Print each row
    for key, value in rows:
        key_str = str(key)
        value_str = str(value)
        print(f"{key_str:<{max_key_len}} │ {value_str}")