import json
from pathlib import Path

import ezdxf

from vnai.dxf_adapter import export_schematic_dxf

ROOT = Path(__file__).resolve().parents[1]


def test_round_trip_schematic_dxf(tmp_path):
    plan = json.loads((ROOT / "examples" / "townhouse_sample.json").read_text(encoding="utf-8"))
    output = export_schematic_dxf(plan, tmp_path / "test.dxf")
    assert output.exists()
    doc = ezdxf.readfile(output)
    assert doc.header["$INSUNITS"] == 4
    assert len(doc.modelspace().query("LWPOLYLINE")) == 4  # 1 site + 3 rooms
