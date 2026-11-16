"""Pure geometric compass labels; does NOT implement feng shui schools."""

import math

OCTANTS = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")


def azimuth_octant(degrees: float) -> str:
    """Convert clockwise true-north bearing in degrees to the closest 8-way direction.

    0° = North, 90° = East. Sector intervals are half-open; 22.5° maps to NE.
    This is not a Bát Trạch/Kua calculation.
    """
    if isinstance(degrees, bool) or not isinstance(degrees, (int, float)):
        raise ValueError("Azimuth must be a finite number of degrees")
    if not math.isfinite(degrees):
        raise ValueError("Azimuth must be finite")
    return OCTANTS[int(((float(degrees) % 360.0) + 22.5) // 45) % 8]
