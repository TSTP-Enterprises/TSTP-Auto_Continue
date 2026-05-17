import os
import sys


THIS_DIR = os.path.dirname(__file__)
V2_ROOT = os.path.abspath(os.path.join(THIS_DIR, ".."))
if V2_ROOT not in sys.path:
    sys.path.insert(0, V2_ROOT)

