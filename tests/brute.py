"""Exhaustive small-capacity reference solver (test only).

Unlike the production planner this solver enumerates *every* block-aligned
destination in a free gap, which is only feasible for tiny capacities.  It
serves as an independent reference in fuzz tests.
"""

from __future__ import annotations

import heapq
from itertools import combinations


def brute_force(capacity, segs, reserved):
    """segs: list of (id, length, start, target) sorted by id."""
    ids = [s[0] for s in segs]
    lens = [s[1] for s in segs]
    start = tuple(s[2] for s in segs)
    goal = tuple(s[3] for s in segs)
    res = sorted(reserved)

    heap = [(0, 0, (), start)]
    best = {start: (0, 0, ())}
    while heap:
        written, steps, seq, pos = heapq.heappop(heap)
        if best.get(pos) != (written, steps, seq):
            continue
        if pos == goal:
            cur = list(start)
            moves = []
            for sid, dst in seq:
                i = ids.index(sid)
                moves.append({"id": sid, "src": cur[i], "dst": dst})
                cur[i] = dst
            return moves, written, steps
        occ = sorted(
            [(p, p + lens[i]) for i, p in enumerate(pos)] + list(res)
        )
        # free blocks
        free = [True] * capacity
        for lo, hi in occ:
            for b in range(lo, hi):
                free[b] = False
        for i, length in enumerate(lens):
            s = pos[i]
            # Copy-in-place semantics: the source stays occupied until the
            # copy completes, so the destination must be free *in addition*
            # to the source and must not overlap it.
            free_i = list(free)
            for d in range(0, capacity - length + 1):
                if all(free_i[b] for b in range(d, d + length)) and d != s:
                    npos = pos[:i] + (d,) + pos[i + 1 :]
                    nseq = seq + ((ids[i], d),)
                    key = (written + length, steps + 1, nseq)
                    old = best.get(npos)
                    if old is None or key < old:
                        best[npos] = key
                        heapq.heappush(heap, (*key, npos))
    return None, None, None
