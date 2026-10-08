"""Work Order Replay roads: GPS pings snapped to streets so a truck drives on roads instead of cutting corners.

A moving stretch of a driver's track (consecutive pings more than MOVE_MI apart) is sent to OSRM as one route through its
pings. The answer is the road's vertices plus, for every ping, the index of the vertex nearest to it, so the player can
move a truck along the road between two pings. Stretches that are not snapped (stationary, over budget, OSRM down) stay a
straight line between pings. Not Salesforce: roads come from osrm.py.
"""

import math
import time

import osrm
from utils import haversine

MOVE_MI = 0.25          # pings closer than this are the same stop
MAX_RUN_PINGS = 25      # one OSRM request per run; longer runs are cut into pieces that share an end ping
MAX_VERTICES = 1500     # what one run sends to the browser


def moving_runs(track: list) -> list:
    """Split [[t, lat, lon]...] into runs of consecutive pings more than MOVE_MI apart, 2 to MAX_RUN_PINGS pings each."""
    runs, cur = [], []
    for a, b in zip(track, track[1:]):
        if (haversine(a[1], a[2], b[1], b[2]) or 0) > MOVE_MI:
            cur = cur or [a]
            cur.append(b)
        else:
            runs.append(cur)
            cur = []
    runs.append(cur)
    out = []
    for run in runs:
        for k in range(0, max(len(run) - 1, 0), MAX_RUN_PINGS - 1):
            out.append(run[k:k + MAX_RUN_PINGS])
    return out


def _nearest_after(coords: list, point: list, start: int) -> int:
    """Index of the vertex at or after `start` closest to the point (the first one on a tie)."""
    cos = math.cos(math.radians(point[0]))
    best, best_d = start, None
    for j in range(start, len(coords)):
        d = (coords[j][0] - point[0]) ** 2 + ((coords[j][1] - point[1]) * cos) ** 2
        if best_d is None or d < best_d:
            best, best_d = j, d
    return best


def thin(coords: list, keep: list) -> tuple:
    """At most MAX_VERTICES vertices that still include every index in `keep`. Returns (coords, new index of each kept index)."""
    step = max(1, math.ceil(len(coords) / max(MAX_VERTICES - len(keep), 1)))
    wanted = sorted({*keep, *range(0, len(coords), step), len(coords) - 1})
    where = {j: n for n, j in enumerate(wanted)}
    return [coords[j] for j in wanted], [where[j] for j in keep]


def snap_runs(track: list, budget_s: float = 6, max_requests: int = 6) -> list:
    """[{'t': [ping times], 'i': [vertex index of each ping], 'c': [[lat, lon]...]}] for the runs OSRM could snap."""
    deadline = time.monotonic() + budget_s
    out = []
    for run in moving_runs(track)[:max_requests]:
        left = deadline - time.monotonic()
        if left <= 0:
            break
        res = osrm.route([[p[1], p[2]] for p in run], timeout=left)
        if not res or len(res['snapped']) != len(run):
            continue
        idx, at = [], 0
        for w in res['snapped']:
            at = _nearest_after(res['coords'], w, at)
            idx.append(at)
        coords, idx = thin(res['coords'], idx)
        out.append({'t': [p[0] for p in run], 'i': idx, 'c': coords})
    return out


def garage_route(garage: dict | None, member: dict | None, timeout: float = 6) -> dict | None:
    """{'c': road vertices, 'miles', 'minutes'} from the garage to the member, for a Towbook truck or a driver with no GPS."""
    if not garage or not member:
        return None
    res = osrm.route([[garage['lat'], garage['lon']], [member['lat'], member['lon']]], timeout=timeout)
    return res and {'c': thin(res['coords'], [])[0], 'miles': res['miles'], 'minutes': res['minutes']}
