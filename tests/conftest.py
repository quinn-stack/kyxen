import os
import sys

# Make the package importable without installing it (pip install -e . also works).
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
