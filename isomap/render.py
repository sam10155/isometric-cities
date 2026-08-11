"""Software orthographic isometric renderer for cached 3D Tiles meshes.

Renders glb mesh tiles (ECEF coordinates) to an isometric pixel image:
ECEF -> local ENU (east/north/up at the quadrant center) -> orthographic
isometric projection (config camera: azimuth/elevation) -> textured
rasterization with a z-buffer.

Pure numpy/PIL — no GPU, no browser. Works entirely from the tile cache: zero
API requests. Speed is adequate for single-quadrant work; batching may move to
a GPU renderer later, but correctness and zero-cost iteration come first.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import trimesh
from PIL import Image

from .config import CityConfig
from . import gridlib
from .tiles3d import _ecef_to_lonlat, _lonlat_to_ecef


@dataclass
class IsoCamera:
    """Orthographic isometric camera derived from city config."""

    azimuth_deg: float
    elevation_deg: float

    def view_matrix(self) -> np.ndarray:
        """3x3 rotation: ENU world -> camera (x right, y up on screen, z toward viewer)."""
        az = math.radians(self.azimuth_deg)
        el = math.radians(self.elevation_deg)
        # forward: direction the camera looks (into the scene), in ENU
        f = np.array([
            math.sin(az) * math.cos(el),
            math.cos(az) * math.cos(el),
            -math.sin(el),
        ])
        up_hint = np.array([0.0, 0.0, 1.0])
        # right = f x up_hint: facing SW (az 225), the viewer's right is NW.
        # (A 2026-08-11 "fix" flipped this to cross(up_hint, f) and MIRRORED
        # the world — BMO read "OMB". Verify with readable facade text, and
        # note roof art may be rotated by design, which is not mirroring.)
        right = np.cross(f, up_hint)
        right /= np.linalg.norm(right)
        up = np.cross(right, f)
        return np.stack([right, up, -f])  # rows: right, up, back


def ecef_to_enu_matrix(lon: float, lat: float) -> np.ndarray:
    """3x3 rotation ECEF -> ENU at (lon, lat)."""
    lon_r, lat_r = math.radians(lon), math.radians(lat)
    sl, cl = math.sin(lon_r), math.cos(lon_r)
    sp, cp = math.sin(lat_r), math.cos(lat_r)
    return np.array([
        [-sl, cl, 0],
        [-sp * cl, -sp * sl, cp],
        [cp * cl, cp * sl, sp],
    ])


class ScreenFrame:
    """THE global screen-space coordinate system for a city's map.

    One fixed ENU frame at the city grid origin + the iso camera define a
    single 2D screen plane (meters; x right, y DOWN like images). Every
    render, tile, and committed pixel is registered in this frame — this is
    what makes separately-rendered pieces composable. (Per-render centering
    without a global frame silently misregisters cross-render compositions:
    world offsets project to *diagonal* screen offsets under the 45deg iso
    camera.)

    Screen TILES replace ground quadrants as the map unit: tile (ti, tj)
    covers screen meters [ti*M, (ti+1)*M) x [tj*M, (tj+1)*M), M =
    meters_per_quadrant. Tile indices are the new (qx, qy) for the DB/planner
    — the tiling math in tilelib is unchanged.
    """

    # constant shift (meters, multiple of tile_m) so the whole city sits in
    # positive screen/tile space — the grid origin is NW of the city and
    # screen-right points NW, putting raw sx negative citywide
    SCREEN_OFFSET = (40960.0, 0.0)

    def __init__(self, city: CityConfig):
        self.city = city
        g = city.grid
        lon0, lat0 = gridlib.xy_to_lonlat(city, g.origin_x, g.origin_y)
        self.origin_ecef = np.array(_lonlat_to_ecef(lon0, lat0, 0.0))
        self.to_enu = ecef_to_enu_matrix(lon0, lat0)
        self.V = IsoCamera(city.camera.azimuth_deg, city.camera.elevation_deg).view_matrix()
        self.tile_m = g.meters_per_quadrant
        self.px_per_m = g.quadrant_px / g.meters_per_quadrant

    def ecef_to_screen(self, ecef: np.ndarray) -> np.ndarray:
        """(N,3) ECEF -> (N,3) screen: x right, y down (image convention), z depth."""
        enu = (ecef - self.origin_ecef) @ self.to_enu.T
        cam = enu @ self.V.T
        return np.column_stack([
            cam[:, 0] + self.SCREEN_OFFSET[0],
            -cam[:, 1] + self.SCREEN_OFFSET[1],
            cam[:, 2],
        ])

    def lonlat_to_screen(self, lon: float, lat: float, h: float = 0.0) -> tuple[float, float]:
        s = self.ecef_to_screen(np.array([_lonlat_to_ecef(lon, lat, h)]))
        return float(s[0, 0]), float(s[0, 1])

    def screen_to_lonlat(self, sx: float, sy: float) -> tuple[float, float]:
        """Screen point -> lon/lat of the ellipsoid-surface (h=0) point that
        projects there. Iterates because the ellipsoid drops below the ENU
        tangent plane with distance (~30 m at 20 km — enough to matter)."""
        right, up, back = self.V[0], self.V[1], self.V[2]
        sx = sx - self.SCREEN_OFFSET[0]
        sy = sy - self.SCREEN_OFFSET[1]
        base = sx * right + (-sy) * up
        z = 0.0
        lon = lat = 0.0
        for _ in range(4):
            t = (z - base[2]) / back[2]
            enu = base + t * back
            ecef = enu @ self.to_enu + self.origin_ecef
            lon, lat = _ecef_to_lonlat(ecef[0], ecef[1], ecef[2])
            surf = np.array(_lonlat_to_ecef(lon, lat, 0.0))
            z = ((surf - self.origin_ecef) @ self.to_enu.T)[2]
        return lon, lat

    def tile_for_screen(self, sx: float, sy: float) -> tuple[int, int]:
        return int(sx // self.tile_m), int(sy // self.tile_m)

    def tile_fetch_region(
        self, min_ti: int, min_tj: int, max_ti: int, max_tj: int,
        max_h: float = 650.0, margin_m: float = 64.0,
    ):
        """Ground lon/lat Region whose geometry can appear in a screen-tile
        rect. Tall geometry at height h projects UP the screen by
        h*cos(elevation): expand the window downward-in-sy by max_h*cos(el)
        so leaning bases are included, then inverse-project the corners."""
        from .tiles3d import Region

        el = math.radians(self.city.camera.elevation_deg)
        x0 = min_ti * self.tile_m - margin_m
        x1 = (max_ti + 1) * self.tile_m + margin_m
        y0 = min_tj * self.tile_m - margin_m
        y1 = (max_tj + 1) * self.tile_m + margin_m + max_h * math.cos(el)
        corners = [self.screen_to_lonlat(x, y) for x in (x0, x1) for y in (y0, y1)]
        lons = [c[0] for c in corners]
        lats = [c[1] for c in corners]
        return Region(west=min(lons), south=min(lats), east=max(lons), north=max(lats))


def load_mesh_vertices(glb_path: Path) -> list[tuple[np.ndarray, np.ndarray, np.ndarray | None, np.ndarray | None]]:
    """Load a glb: list of (vertices ECEF, faces, uv, texture image array)."""
    scene = trimesh.load(str(glb_path), process=False)
    out = []
    geoms = scene.geometry.values() if hasattr(scene, "geometry") else [scene]
    graph = scene.graph if hasattr(scene, "graph") else None
    # apply node transforms so vertices land in scene (ECEF) space
    transforms = {}
    if graph is not None:
        for node_name in scene.graph.nodes_geometry:
            T, gname = scene.graph[node_name]
            transforms.setdefault(gname, T)
    for name, g in (scene.geometry.items() if hasattr(scene, "geometry") else [("m", scene)]):
        v = g.vertices.copy()
        T = transforms.get(name)
        if T is not None:
            v = (np.hstack([v, np.ones((len(v), 1))]) @ T.T)[:, :3]
        # glTF is Y-up: 3D Tiles glbs store ECEF rotated as (x, z, -y).
        # Undo it: ecef = (gx, -gz, gy).
        v = np.column_stack([v[:, 0], -v[:, 2], v[:, 1]])
        uv = None
        tex = None
        try:
            uv = np.asarray(g.visual.uv) if g.visual.uv is not None else None
            img = g.visual.material.baseColorTexture
            if img is None:
                img = getattr(g.visual.material, "image", None)
            if img is not None:
                tex = np.asarray(img.convert("RGB"))
        except Exception:
            pass
        out.append((v, np.asarray(g.faces), uv, tex))
    return out


def render_screen_block(
    frame: ScreenFrame,
    min_ti: int,
    min_tj: int,
    max_ti: int,
    max_tj: int,
    glb_paths: list[Path],
    supersample: int = 1,
) -> Image.Image:
    """Render an inclusive SCREEN-TILE rect in the global frame.

    Because every render shares the frame, blocks rendered separately are
    pixel-exactly composable: tile (ti, tj) shows identical content no matter
    which render it was cropped from.
    """
    g = frame.city.grid
    n_x = max_ti - min_ti + 1
    n_y = max_tj - min_tj + 1
    px_w = g.quadrant_px * n_x * supersample
    px_h = g.quadrant_px * n_y * supersample
    m_per_px = g.meters_per_px / supersample
    sx0 = min_ti * frame.tile_m
    sy0 = min_tj * frame.tile_m

    img_buf = np.zeros((px_h, px_w, 3), dtype=np.uint8)
    zbuf = np.full((px_h, px_w), -np.inf, dtype=np.float64)

    for path in glb_paths:
        for verts_ecef, faces, uv, tex in load_mesh_vertices(path):
            s = frame.ecef_to_screen(verts_ecef)
            xs_all = (s[:, 0] - sx0) / m_per_px
            ys_all = (s[:, 1] - sy0) / m_per_px
            depth = s[:, 2]  # cam z = -(enu . forward): larger = closer

            for f in faces:
                xs, ys, zs = xs_all[f], ys_all[f], depth[f]
                if (xs.max() < 0 or xs.min() >= px_w
                        or ys.max() < 0 or ys.min() >= px_h):
                    continue
                _raster_tri(img_buf, zbuf, xs, ys, zs,
                            uv[f] if uv is not None else None, tex)

    img = Image.fromarray(img_buf)
    if supersample > 1:
        img = img.resize((g.quadrant_px * n_x, g.quadrant_px * n_y), Image.LANCZOS)
    return img


def crop_tile(
    frame: ScreenFrame,
    block_img: Image.Image,
    min_ti: int,
    min_tj: int,
    ti: int,
    tj: int,
) -> Image.Image:
    """Cut one screen tile out of a render_screen_block image."""
    p = frame.city.grid.quadrant_px
    x0 = (ti - min_ti) * p
    y0 = (tj - min_tj) * p
    return block_img.crop((x0, y0, x0 + p, y0 + p))


def _raster_tri(img, zbuf, xs, ys, zs, uvs, tex):
    """Rasterize one textured triangle with barycentric interpolation."""
    min_x = max(int(np.floor(xs.min())), 0)
    max_x = min(int(np.ceil(xs.max())), img.shape[1] - 1)
    min_y = max(int(np.floor(ys.min())), 0)
    max_y = min(int(np.ceil(ys.max())), img.shape[0] - 1)
    if min_x > max_x or min_y > max_y:
        return
    x0, y0, x1, y1, x2, y2 = xs[0], ys[0], xs[1], ys[1], xs[2], ys[2]
    denom = (y1 - y2) * (x0 - x2) + (x2 - x1) * (y0 - y2)
    if abs(denom) < 1e-12:
        return
    gx, gy = np.meshgrid(
        np.arange(min_x, max_x + 1) + 0.5, np.arange(min_y, max_y + 1) + 0.5
    )
    w0 = ((y1 - y2) * (gx - x2) + (x2 - x1) * (gy - y2)) / denom
    w1 = ((y2 - y0) * (gx - x2) + (x0 - x2) * (gy - y2)) / denom
    w2 = 1 - w0 - w1
    inside = (w0 >= 0) & (w1 >= 0) & (w2 >= 0)
    if not inside.any():
        return
    z = w0 * zs[0] + w1 * zs[1] + w2 * zs[2]
    region_z = zbuf[min_y:max_y + 1, min_x:max_x + 1]
    visible = inside & (z > region_z)
    if not visible.any():
        return
    region_z[visible] = z[visible]

    if uvs is not None and tex is not None:
        u = w0 * uvs[0, 0] + w1 * uvs[1, 0] + w2 * uvs[2, 0]
        v = w0 * uvs[0, 1] + w1 * uvs[1, 1] + w2 * uvs[2, 1]
        th, tw = tex.shape[:2]
        ti = np.clip(((1 - v) * (th - 1)).astype(int), 0, th - 1)
        tj = np.clip((u * (tw - 1)).astype(int), 0, tw - 1)
        colors = tex[ti[visible], tj[visible]]
    else:
        colors = np.array([180, 180, 180], dtype=np.uint8)
    img[min_y:max_y + 1, min_x:max_x + 1][visible] = colors
