"""
Global test configuration for AAIP tests.
Adds SDK Python package to sys.path for imports.
Also adds workspace root to sys.path for aaip package imports.
"""

import sys
import os

# Add workspace root to sys.path for aaip package imports (HIGHEST PRIORITY)
workspace_root = os.path.join(os.path.dirname(__file__), '..')
if workspace_root not in sys.path:
    sys.path.insert(0, workspace_root)

# Add sdk/python directory to sys.path for SDK imports
# This allows imports like `from sdk.python.aaip import ...`
sdk_dir = os.path.join(os.path.dirname(__file__), '..', 'sdk', 'python')
sdk_parent = os.path.join(os.path.dirname(__file__), '..', 'sdk')
if sdk_parent not in sys.path:
    sys.path.insert(0, sdk_parent)