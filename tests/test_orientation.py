import pytest

from vnai.orientation import azimuth_octant


@pytest.mark.parametrize(
    ("degrees", "expected"),
    [(0, "N"), (22.49, "N"), (22.5, "NE"), (45, "NE"), (90, "E"),
     (180, "S"), (225, "SW"), (359.9, "N"), (-90, "W"), (360, "N")],
)
def test_compass_octants(degrees, expected):
    assert azimuth_octant(degrees) == expected


def test_invalid_compass():
    for value in [float("nan"), float("inf"), True, "east"]:
        with pytest.raises(ValueError):
            azimuth_octant(value)
