"""Segment relocation planner.

The planner works purely on interval endpoints.  It never enumerates the
blocks of a volume, so a capacity close to 2**64 is as cheap as a capacity
of a few blocks.

State representation
--------------------
A state is a tuple ``pos`` with ``pos[i]`` equal to the current start block
of segment ``i`` (indices follow the request order, which is sorted by
segment id).

For a segment of length ``L`` sitting inside a free gap ``[left, right)``,
a destination start ``d`` (``left <= d <= right - L``) is characterised,
for planning purposes, only by *which target intervals it overlaps*:

    [d, d + L) intersects target k  <=>  t_k - L + 1 <= d <= t_k + l_k - 1

Between two consecutive pattern boundaries all placements block exactly
the same target intervals.  Within such a region, an interior placement
splits the remaining free space into two chunks; either extremal
placement leaves one chunk whose size is the sum of both, which can hold
everything the two chunks could hold (target alignment is recomputed in
later states).  Extremal placements are therefore sufficient for
feasibility and for the total-write / step objectives, while keeping the
leftmost placement of every region preserves the lexicographically
smallest action.

Two extra "anchor" placements per target are kept regardless of region
geometry: a start exactly equal to a target's start (the only placement
that finishes that segment) and the start that right-aligns with a target,
either of which may lie strictly inside a constant-pattern region.

The state search is a lexicographic Dijkstra over the cost
``(written_blocks, steps, action_sequence)``; it expands states symbolically
and its complexity depends only on the number of segments, never on the
volume capacity.
"""

from __future__ import annotations

import heapq
from typing import Sequence

#: maximum addressable block index / capacity (unsigned 64-bit integer)
MAX_U64 = (1 << 64) - 1


def _merge(intervals: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Merge a list of disjoint/adjacent ``[start, end)`` intervals."""
    intervals = sorted(intervals)
    merged: list[tuple[int, int]] = []
    for start, end in intervals:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _free_gaps(
    capacity: int,
    occupied: Sequence[tuple[int, int]],
) -> list[tuple[int, int]]:
    """Return the maximal free ``[start, end)`` intervals of the volume."""
    gaps: list[tuple[int, int]] = []
    cursor = 0
    for start, end in _merge(list(occupied)):
        if start > cursor:
            gaps.append((cursor, start))
        cursor = max(cursor, end)
    if cursor < capacity:
        gaps.append((cursor, capacity))
    return gaps


def _destinations(
    gaps: list[tuple[int, int]],
    length: int,
    targets: Sequence[int],
    lengths: Sequence[int],
) -> list[int]:
    """Candidate destination starts for a segment of ``length``.

    Gaps exclude the moving segment's own interval, so a destination in a
    gap never overlaps the source or any other occupied interval.
    """
    result: list[int] = []
    for left, right in gaps:
        if right - left < length:
            continue
        lo, hi = left, right - length

        # Pattern boundaries: within [p, next_p - 1] the set of target
        # intervals overlapped by [d, d + length) is constant.
        bounds = {lo, hi + 1}
        for t, other_len in zip(targets, lengths):
            bounds.add(t - length + 1)  # first d overlapping target k
            bounds.add(t + other_len)  # first d no longer overlapping it
        # Bounds inside [lo, hi] are genuine pattern starts; hi + 1 is a
        # sentinel that merely closes the last region.
        points = sorted(p for p in bounds if lo <= p <= hi + 1)

        # A placement that lands exactly on a target interval is the only
        # way a segment can finish; its start / right-aligned start may sit
        # in the interior of a constant-pattern region, so add them as
        # anchors explicitly.
        cands: set[int] = {lo}
        for t, other_len in zip(targets, lengths):
            if lo <= t <= hi:
                cands.add(t)
            right_aligned = t + other_len - length
            if lo <= right_aligned <= hi:
                cands.add(right_aligned)

        for idx, p in enumerate(points):
            if p > hi:
                break
            # Region [p, region_end] has a constant target-overlap pattern.
            region_end = min(points[idx + 1] - 1, hi)
            cands.add(p)  # leftmost placement of this region
            cands.add(region_end)  # rightmost placement
        result.extend(cands)
    return sorted(set(result))


def plan_moves(
    capacity: int,
    segments: list[dict],
    reserved: list[tuple[int, int]],
) -> list[dict] | None:
    """Compute an optimal relocation plan.

    ``segments`` is a list of dicts with keys ``id``, ``length``, ``start``
    (current start) and ``target`` (desired start), sorted by id.

    Returns a list of moves ``{"id", "src", "dst"}`` in execution order,
    an empty list when every segment is already at its target, or ``None``
    when no feasible plan exists.
    """
    n = len(segments)
    ids = [s["id"] for s in segments]
    lengths = [s["length"] for s in segments]
    targets = [s["target"] for s in segments]
    start = tuple(s["start"] for s in segments)
    goal = tuple(targets)

    if start == goal:
        return []

    reserved_merged = _merge(reserved)

    # Heap entries carry the full action prefix, which is also the final
    # lexicographic tie-break key: (written_blocks, steps, sequence).
    # An action is identified by (segment id, destination); the source is
    # determined by the predecessor state.
    heap: list[tuple[int, int, tuple[tuple[str, int], ...], tuple[int, ...]]] = [
        (0, 0, (), start)
    ]
    best: dict[tuple[int, ...], tuple[int, int, tuple[tuple[str, int], ...]]] = {
        start: (0, 0, ())
    }

    while heap:
        written, steps, seq, pos = heapq.heappop(heap)
        if best.get(pos) != (written, steps, seq):
            continue
        if pos == goal:
            return _reconstruct(ids, start, seq)

        occupied: list[tuple[int, int]] = list(reserved_merged)
        for i, p in enumerate(pos):
            occupied.append((p, p + lengths[i]))
        gaps = _free_gaps(capacity, occupied)

        for i in range(n):
            length = lengths[i]
            src = pos[i]
            for dst in _destinations(gaps, length, targets, lengths):
                if dst == src:
                    continue
                new_pos = pos[:i] + (dst,) + pos[i + 1 :]
                new_written = written + length
                new_steps = steps + 1
                new_seq = seq + ((ids[i], dst),)
                old = best.get(new_pos)
                if old is not None and (old[0], old[1], old[2]) <= (
                    new_written,
                    new_steps,
                    new_seq,
                ):
                    continue
                best[new_pos] = (new_written, new_steps, new_seq)
                heapq.heappush(
                    heap, (new_written, new_steps, new_seq, new_pos)
                )

    return None


def _reconstruct(
    ids: Sequence[str],
    start: tuple[int, ...],
    seq: tuple[tuple[str, int], ...],
) -> list[dict]:
    """Replay an action sequence from ``start`` to produce explicit moves.

    Each action carries only (segment id, destination); the source of every
    copy is the segment's position at that point of the replay, so the
    returned plan is fully replayable.
    """
    pos = list(start)
    index = {seg_id: i for i, seg_id in enumerate(ids)}
    moves: list[dict] = []
    for seg_id, dst in seq:
        i = index[seg_id]
        moves.append({"id": seg_id, "src": pos[i], "dst": dst})
        pos[i] = dst
    return moves
