"""
MSFS WinWing CDU Scraper

Captures an aircraft's FMS display (MCDU / CDU / UNS-1) from its Microsoft
Flight Simulator pop-out window and forwards it to WinWing CDU hardware over
MobiFlight's WebSocket interface.

The scraper reads pixels rather than sim data, so it works with any aircraft
whose FMS shows a character grid - including those with no native MobiFlight
integration. See aircraft_profiles for the supported display families.
"""

__version__ = "2.0.0"
