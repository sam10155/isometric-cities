"""City configuration loading.

A city is fully described by cities/<name>/config.yaml. All pipeline code takes a
CityConfig rather than reading files or hardcoding city facts.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
CITIES_DIR = REPO_ROOT / "cities"


@dataclass(frozen=True)
class GridSpec:
    quadrant_px: int
    meters_per_quadrant: float
    origin_x: float
    origin_y: float

    @property
    def meters_per_px(self) -> float:
        return self.meters_per_quadrant / self.quadrant_px


@dataclass(frozen=True)
class CameraSpec:
    azimuth_deg: float
    elevation_deg: float
    projection: str


@dataclass(frozen=True)
class CityConfig:
    name: str
    display_name: str
    crs: str
    seed_lonlat: tuple[float, float]
    grid: GridSpec
    camera: CameraSpec
    pilot_bbox_lonlat: tuple[float, float, float, float] | None
    city_dir: Path

    @property
    def db_path(self) -> Path:
        return self.city_dir / "quadrants.sqlite"


def load_city(name: str) -> CityConfig:
    city_dir = CITIES_DIR / name
    path = city_dir / "config.yaml"
    if not path.exists():
        available = sorted(p.name for p in CITIES_DIR.iterdir() if p.is_dir())
        raise FileNotFoundError(f"No config for city '{name}' at {path}. Available: {available}")
    raw = yaml.safe_load(path.read_text())

    grid_raw = raw["grid"]
    grid = GridSpec(
        quadrant_px=int(grid_raw["quadrant_px"]),
        meters_per_quadrant=float(grid_raw["meters_per_quadrant"]),
        origin_x=float(grid_raw["origin_xy"][0]),
        origin_y=float(grid_raw["origin_xy"][1]),
    )
    cam_raw = raw["camera"]
    camera = CameraSpec(
        azimuth_deg=float(cam_raw["azimuth_deg"]),
        elevation_deg=float(cam_raw["elevation_deg"]),
        projection=str(cam_raw["projection"]),
    )
    pilot = raw.get("pilot_bbox_lonlat")
    return CityConfig(
        name=raw["name"],
        display_name=raw["display_name"],
        crs=raw["crs"],
        seed_lonlat=tuple(raw["seed_lonlat"]),
        grid=grid,
        camera=camera,
        pilot_bbox_lonlat=tuple(pilot) if pilot else None,
        city_dir=city_dir,
    )
