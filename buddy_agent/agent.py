"""ADK web entry module exposing root_agent from BuddyApp."""

import os
import sys

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from buddyai.app import BuddyApp

root_agent = BuddyApp().root_agent
