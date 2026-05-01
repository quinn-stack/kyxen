#!/usr/bin/env python3
"""Development launcher — use 'openlogikey-daemon' once installed via pip."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))
from openlogikey.__main__ import main
main()
