#!/usr/bin/env python3
"""Development launcher — use 'kyxen-daemon' once installed via pip."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))
from kyxen_keys.__main__ import main
main()
