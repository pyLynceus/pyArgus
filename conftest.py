import os
import sys

# Tests run against the working tree whether or not the package is
# installed; the repo root goes first on the path.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
