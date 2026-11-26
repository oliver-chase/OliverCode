#!/usr/bin/env python3
"""A hook that does nothing and exits 0. A settings file written by a later install can still name this script, and a missing hook script blocks the tool call it guards, so the file stays until `olivercode install` rewrites the settings."""
import sys

sys.exit(0)
