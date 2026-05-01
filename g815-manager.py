#!/usr/bin/env python3
"""Development launcher — use 'openlogikey' once installed via pip."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))
from openlogikey.gui.app import main
main()
