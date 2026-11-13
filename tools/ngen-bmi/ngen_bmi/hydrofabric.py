"""The hydrofabric files ngen is given, and the catchment ids they hold."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Union

__all__ = ["Hydrofabric"]

PathLike = Union[str, Path]


@dataclass(frozen=True)
class Hydrofabric:
    """Catchment and nexus data: one GeoPackage for both, or two GeoJSON files."""

    catchments: Path
    nexus: Path

    @classmethod
    def from_args(cls, hydrofabric: Optional[PathLike] = None, catchments: Optional[PathLike] = None,
                  nexus: Optional[PathLike] = None) -> "Hydrofabric":
        if hydrofabric is not None:
            if catchments is not None or nexus is not None:
                raise ValueError("pass either hydrofabric= (a GeoPackage) or catchments= and nexus=, "
                                 "not both")
            path = Path(hydrofabric).resolve()
            return cls(path, path)
        if catchments is None or nexus is None:
            raise ValueError("a hydrofabric is needed: hydrofabric= (a GeoPackage) or "
                             "catchments= and nexus= (GeoJSON)")
        return cls(Path(catchments).resolve(), Path(nexus).resolve())

    def catchment_ids(self) -> List[str]:
        """Catchment ids in file order, read the way ngen reads them."""
        path = self.catchments
        if not path.is_file():
            raise FileNotFoundError(f"hydrofabric file not found: {path}")
        if path.suffix.lower() == ".gpkg":
            return _gpkg_divide_ids(path)
        data = json.loads(path.read_text(encoding="utf-8"))
        ids = []
        for feature in data.get("features", []):
            fid = feature.get("id") or (feature.get("properties") or {}).get("id")
            if fid is None:
                raise ValueError(f"{path}: a feature has no id")
            ids.append(str(fid))
        return ids


def _gpkg_divide_ids(path: Path) -> List[str]:
    # ngen (src/geopackage/read.cpp) uses divide_id and falls back to the legacy id column.
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        try:
            rows = con.execute("SELECT divide_id FROM divides").fetchall()
        except sqlite3.OperationalError:
            rows = con.execute("SELECT id FROM divides").fetchall()
    finally:
        con.close()
    return [str(r[0]) for r in rows]
