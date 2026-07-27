"""Legacy entry point — kept so existing shortcuts keep working.

The original single-file script has been replaced by the ``bom_validator``
package. Everything now lives there:

    python -m bom_validator                 # launch the desktop app
    python -m bom_validator validate F.xlsx # headless validation
    bomv --help                             # after `pip install -e .`

This shim simply forwards to the new GUI.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

if __name__ == "__main__":
    from bom_validator.gui.app import run_gui

    sys.exit(run_gui(sys.argv[1] if len(sys.argv) > 1 else None))
