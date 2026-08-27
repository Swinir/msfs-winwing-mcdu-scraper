"""
Aircraft profiles: what actually varies between FMS displays.

The scraper never cares which aircraft it is looking at — it OCRs pixels,
and glyph templates are learned at runtime, so a new font teaches itself.
What varies between FMS families is only:

  * the character grid dimensions,
  * which font the WinWing hardware should load,
  * whether label rows render in the small font,
  * and the template store — glyphs learned from one font must not be
    matched against another, so each family gets its own store file.

The WinWing CDU hardware itself is always 24x14; a smaller profile grid is
padded out to the hardware grid before sending (see pipeline.pad_to_hardware).

Profiles cover FMS *families*, so one profile serves every aircraft built on
the same avionics: the Airbus profile covers the iniBuilds default suite and
the LatinVFR / Horizon Sim Airbuses (which are built on the default
avionics), the Boeing profile covers the C-17 and E-7 CDU screens, and the
UNS-1 profile covers the Black Square and Just Flight fleets that share the
Universal UNS-1.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict


#: Font files MobiFlight actually ships for the MCDU hardware
#: (Scripts/Winwing/Fonts/Default/MCDU/*.dat).  An unknown name is silently
#: ignored by MobiFlight's FontLoader, leaving the previous font in place.
KNOWN_FONTS = frozenset({"AirbusThales", "Boeing", "Collins"})

#: Small-font conventions.
#:  labels_small — odd rows are label rows drawn in the small font, except
#:                 the last row (the scratchpad).  Airbus and Boeing CDUs
#:                 both follow this.
#:  all_large   — every row renders at full size (UNS-1 style CRTs).
SMALL_FONT_RULES = ("labels_small", "all_large")


@dataclass(frozen=True)
class AircraftProfile:
    """One FMS family's display characteristics."""

    id: str
    label: str
    columns: int
    rows: int
    #: Font the WinWing hardware loads for this family.
    font: str
    small_font_rule: str = "labels_small"
    #: Which set of known fixed page labels applies, if any.  Every
    #: airliner CDU here shares the labels_small convention, so that
    #: is no guide at all: the ATR's INIT page and the Airbus's INIT
    #: page match each other's title and share none of their labels.
    #: Empty means the display's own text is the only authority.
    page_labels: str = ""
    #: Basename of this family's learned-glyph store under templates/.
    template_filename: str = ""
    notes: str = ""

    def template_path(self) -> Path:
        """Where this profile's learned glyphs live."""
        from mcdu_parser import TemplateMatcher
        base = TemplateMatcher.DEFAULT_TEMPLATE_PATH.parent
        return base / self.template_filename


PROFILES: Dict[str, AircraftProfile] = {
    profile.id: profile
    for profile in (
        AircraftProfile(
            id="airbus",
            label="Airbus MCDU  (default A320neo/A321/A330, LatinVFR, Horizon)",
            columns=24,
            rows=14,
            font="AirbusThales",
            page_labels="airbus",
            # Legacy filename so templates learned before profiles existed
            # keep working — they were all Airbus.
            template_filename="mcdu_templates.npz",
        ),
        AircraftProfile(
            id="atr",
            label="ATR 42/72-600 MCDU  (Thales FMS 220)",
            columns=24,
            rows=14,
            font="AirbusThales",
            template_filename="mcdu_templates_atr.npz",
            notes=(
                "Same Thales-style 24x14 layout as the Airbus MCDU, but the "
                "ATR renders its glyphs differently, so it learns into its "
                "own template store."
            ),
        ),
        AircraftProfile(
            id="boeing",
            label="Boeing CDU  (747-8, 787, C-17, E-7)",
            columns=24,
            rows=14,
            font="Boeing",
            template_filename="mcdu_templates_boeing.npz",
        ),
        AircraftProfile(
            id="fokker",
            label="Fokker 70/100 FMC  (Just Flight, Honeywell/Pegasus)",
            columns=24,
            rows=14,
            font="Boeing",
            template_filename="mcdu_templates_fokker.npz",
            notes=(
                "Green monochrome CRT with the usual label/value row pairs. "
                "Row count and pitch are measured; the column count is the "
                "24-column CDU convention, since the pages captured so far "
                "use only about 17 of them. Correct it under Advanced > "
                "Override grid size if text lands in the wrong columns."
            ),
        ),
        AircraftProfile(
            id="avro_gnlu",
            label="Avro RJ / BAe 146 GNLU  (Just Flight)",
            columns=25,
            rows=14,
            font="Boeing",
            template_filename="mcdu_templates_avro.npz",
            notes=(
                "Measured at 25 columns - one more than the WinWing "
                "hardware. Each row is squeezed by dropping blank cells, "
                "preferring trailing and leading ones, so the line-select "
                "prompts at both edges survive."
            ),
        ),
        AircraftProfile(
            id="uns1",
            label="UNS-1 FMS  (Black Square, Just Flight 146/F28) — experimental",
            columns=24,
            rows=11,
            font="Boeing",
            small_font_rule="all_large",
            template_filename="mcdu_templates_uns1.npz",
            notes=(
                "24x11, measured from Working Title and Just Flight BAe 146 "
                "captures. Unlike an airliner CDU the UNS-1 is only "
                "approximately a uniform grid: measured, 45% of its glyphs "
                "cross a cell edge, against none on the ATR. Recognition "
                "reads a wider window to cope (ISSUES.md #28), and the "
                "Working Title page scores 91% from cold. Still the hardest "
                "display here - check the grid overlay before starting."
            ),
        ),
        AircraftProfile(
            id="custom",
            label="Custom grid…  (set size under Advanced)",
            columns=24,
            rows=14,
            font="AirbusThales",
            template_filename="mcdu_templates_custom.npz",
            notes=(
                "For FMS types not listed (GNS-XLS, CMA-900, …). Set the "
                "grid under Advanced > Override grid size so the overlay "
                "matches the display."
            ),
        ),
    )
}

DEFAULT_PROFILE_ID = "airbus"


def get_profile(profile_id: str) -> AircraftProfile:
    """Look up a profile, falling back to the default."""
    return PROFILES.get(profile_id, PROFILES[DEFAULT_PROFILE_ID])
