"""python3 -m tests —— 等价于从项目根 `python3 -m unittest discover tests`。"""

import os
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)

if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

if __name__ == "__main__":
    sys.argv = [sys.argv[0], "discover", "-s", _HERE, "-t", _ROOT, "-v"]
    unittest.main(module=None)
