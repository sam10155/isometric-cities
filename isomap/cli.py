"""isomap CLI — thin commands over the core libraries.

Follows the CLI -> library -> application pattern: everything here is a few
lines of glue; all logic lives in gridlib/tilelib/store.

Usage:
  python -m isomap.cli info <city>
  python -m isomap.cli locate <city> <lon> <lat>
  python -m isomap.cli plan <city> --bbox <min_lon,min_lat,max_lon,max_lat>
  python -m isomap.cli plan <city> --pilot [--commit]
  python -m isomap.cli status <city>
"""

from __future__ import annotations

import argparse
import sys

from . import gridlib
from .config import load_city
from .store import QuadrantStore
from .tilelib import QState, Rect, Unfillable, plan_rect


def cmd_info(args) -> int:
    city = load_city(args.city)
    g = city.grid
    print(f"{city.display_name} ({city.name})")
    print(f"  CRS: {city.crs}")
    print(f"  quadrant: {g.quadrant_px}px, {g.meters_per_quadrant} m "
          f"({g.meters_per_px:.3f} m/px)")
    print(f"  grid origin (CRS m): ({g.origin_x}, {g.origin_y})")
    sqx, sqy = gridlib.lonlat_to_quadrant(city, *city.seed_lonlat)
    print(f"  seed point quadrant: ({sqx}, {sqy})")
    if city.pilot_bbox_lonlat:
        r = gridlib.bbox_lonlat_to_quadrant_range(city, city.pilot_bbox_lonlat)
        w, h = r[2] - r[0] + 1, r[3] - r[1] + 1
        print(f"  pilot region: quadrants ({r[0]},{r[1]})..({r[2]},{r[3]}) "
              f"= {w}x{h} = {w*h} quadrants")
    print(f"  db: {city.db_path} ({'exists' if city.db_path.exists() else 'not created'})")
    return 0


def cmd_locate(args) -> int:
    city = load_city(args.city)
    qx, qy = gridlib.lonlat_to_quadrant(city, args.lon, args.lat)
    b = gridlib.quadrant_bounds_xy(city, qx, qy)
    clon, clat = gridlib.quadrant_center_lonlat(city, qx, qy)
    print(f"quadrant: ({qx}, {qy})")
    print(f"  CRS bounds: x [{b.min_x:.1f}, {b.max_x:.1f}]  y [{b.min_y:.1f}, {b.max_y:.1f}]")
    print(f"  center lon/lat: ({clon:.6f}, {clat:.6f})")
    return 0


def _parse_bbox(s: str) -> tuple[float, float, float, float]:
    parts = [float(p) for p in s.split(",")]
    if len(parts) != 4:
        raise argparse.ArgumentTypeError("bbox must be min_lon,min_lat,max_lon,max_lat")
    return tuple(parts)


def cmd_plan(args) -> int:
    city = load_city(args.city)
    if args.pilot:
        if not city.pilot_bbox_lonlat:
            print(f"error: {city.name} has no pilot_bbox_lonlat configured", file=sys.stderr)
            return 1
        bbox = city.pilot_bbox_lonlat
    elif args.bbox:
        bbox = args.bbox
    else:
        print("error: provide --bbox or --pilot", file=sys.stderr)
        return 1

    rng = gridlib.bbox_lonlat_to_quadrant_range(city, bbox)
    rect = Rect(*rng)
    with QuadrantStore(city.db_path) as store:
        state = store.load_grid_state()
        try:
            plan = plan_rect(state, rect)
        except Unfillable as e:
            print(f"unfillable: {e}", file=sys.stderr)
            return 2

        print(f"rect: ({rect.min_qx},{rect.min_qy})..({rect.max_qx},{rect.max_qy}) "
              f"= {rect.width}x{rect.height}")
        print(f"plan: {plan.calls} model calls, {plan.new_quadrants} new quadrants")
        for i, w in enumerate(plan.windows[: args.show]):
            print(f"  {i+1:4d}: window ({w.qx},{w.qy})")
        if plan.calls > args.show:
            print(f"  ... {plan.calls - args.show} more")

        if args.commit:
            for w in plan.windows:
                for q in w.quadrants():
                    if state.get(q) is QState.EMPTY:
                        state.set(q, QState.PENDING)
                        store.set_state(q, QState.PENDING, batch_id=args.batch_id)
            print(f"committed: {plan.new_quadrants} quadrants marked pending "
                  f"(batch: {args.batch_id})")
    return 0


def cmd_status(args) -> int:
    city = load_city(args.city)
    if not city.db_path.exists():
        print(f"no database yet for {city.name}")
        return 0
    with QuadrantStore(city.db_path) as store:
        counts = store.counts()
    total = sum(counts.values())
    print(f"{city.name}: {total} tracked quadrants")
    for state, n in sorted(counts.items()):
        print(f"  {state}: {n}")
    return 0


def cmd_budget(args) -> int:
    from .apibudget import ApiBudget, FREE_TIER

    with ApiBudget() as b:
        sessions = b.status("map_tiles_session")
        raw = b.status("map_tiles")
    print("Google Maps API budget (session-billing model — verify vs console SKU report)")
    print(f"  sessions (assumed billable): {sessions}")
    print(f"  raw requests (diagnostic):   {raw}")
    print(f"  free tier: {FREE_TIER} billable units/month")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="isomap")
    sub = p.add_subparsers(dest="command", required=True)

    sp = sub.add_parser("info", help="show city configuration and grid facts")
    sp.add_argument("city")
    sp.set_defaults(func=cmd_info)

    sp = sub.add_parser("locate", help="lon/lat -> quadrant")
    sp.add_argument("city")
    sp.add_argument("lon", type=float)
    sp.add_argument("lat", type=float)
    sp.set_defaults(func=cmd_locate)

    sp = sub.add_parser("plan", help="plan seam-free generation for a region")
    sp.add_argument("city")
    sp.add_argument("--bbox", type=_parse_bbox,
                    help="min_lon,min_lat,max_lon,max_lat (WGS84)")
    sp.add_argument("--pilot", action="store_true", help="use the configured pilot region")
    sp.add_argument("--show", type=int, default=10, help="windows to print (default 10)")
    sp.add_argument("--commit", action="store_true",
                    help="mark planned quadrants pending in the DB")
    sp.add_argument("--batch-id", default="manual", help="batch id for --commit")
    sp.set_defaults(func=cmd_plan)

    sp = sub.add_parser("status", help="quadrant state counts from the DB")
    sp.add_argument("city")
    sp.set_defaults(func=cmd_status)

    sp = sub.add_parser("budget", help="Google API budget status (sessions + raw)")
    sp.set_defaults(func=cmd_budget)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
