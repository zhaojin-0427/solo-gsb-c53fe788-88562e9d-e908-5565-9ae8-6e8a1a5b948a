"""Tests: example cases, replay validity and fuzz comparison vs brute force."""

from __future__ import annotations

import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.planner import plan_moves  # noqa: E402

sys.path.insert(1, os.path.dirname(os.path.abspath(__file__)))
from brute import brute_force  # noqa: E402


def replay(capacity, segs, reserved, moves):
    """Validate a plan step by step; return (ok, reason)."""
    pos = {s["id"]: s["start"] for s in segs}
    length = {s["id"]: s["length"] for s in segs}
    for step, m in enumerate(moves):
        sid, src, dst = m["id"], m["src"], m["dst"]
        if pos.get(sid) is None:
            return False, f"step {step}: unknown id {sid}"
        if pos[sid] != src:
            return False, f"step {step}: wrong source for {sid}"
        length_l = length[sid]
        s, d, e = src, dst, dst + length_l
        if d < 0 or e > capacity:
            return False, f"step {step}: out of bounds"
        # source and destination must not overlap
        if d < src + length_l and src < e:
            return False, f"step {step}: dst overlaps src"
        # dst must not touch other segments or reserved regions
        for other, p in pos.items():
            if other == sid:
                continue
            os_, oe = p, p + length[other]
            if d < oe and os_ < e:
                return False, f"step {step}: dst hits {other}"
        for rlo, rhi in reserved:
            if d < rhi and rlo < e:
                return False, f"step {step}: dst hits reserved"
        # copy completes before the old location is released
        pos[sid] = dst
    for s in segs:
        if pos[s["id"]] != s["target"]:
            return False, f"{s['id']} not at target"
    return True, ""


def written_and_steps(segs, moves):
    length = {s["id"]: s["length"] for s in segs}
    return sum(length[m["id"]] for m in moves), len(moves)


def test_problem_example():
    # capacity 5: A:[0,2)->[2,4), B:[2,3)->[0,1); B must move first to [4,5)
    segs = [
        {"id": "A", "length": 2, "start": 0, "target": 2},
        {"id": "B", "length": 1, "start": 2, "target": 0},
    ]
    moves = plan_moves(5, segs, [])
    assert moves == [
        {"id": "B", "src": 2, "dst": 4},
        {"id": "A", "src": 0, "dst": 2},
        {"id": "B", "src": 4, "dst": 0},
    ]
    ok, reason = replay(5, segs, [], moves)
    assert ok, reason
    assert written_and_steps(segs, moves) == (4, 3)


def test_already_placed():
    segs = [{"id": "X", "length": 3, "start": 1, "target": 1}]
    assert plan_moves(4, segs, []) == []


def test_empty_volume():
    assert plan_moves(0, [], []) == []


def test_infeasible_no_free_space():
    # full volume swap of two length-1 segments, capacity 2: nowhere to go
    segs = [
        {"id": "A", "length": 1, "start": 0, "target": 1},
        {"id": "B", "length": 1, "start": 1, "target": 0},
    ]
    assert plan_moves(2, segs, []) is None


def test_infeasible_fragmented():
    # A length 2 must move, but only two isolated free blocks of length 1
    # C=4: A:[0,2)->[2,4); reserved [3,4); free is only [2,3)
    segs = [{"id": "A", "length": 2, "start": 0, "target": 2}]
    assert plan_moves(4, segs, [(3, 4)]) is None


def test_reserved_region_blocks_buffer():
    # C=6: A[0,2)->[2,4), B[2,3)->[0,1), free [3,6) length 3.
    # Reserving [4,6) leaves only [3,4) for B to buffer, but then B's
    # temp slot [3,4) blocks A's target [2,4): B cannot be placed
    # anywhere else and the cycle cannot be broken => infeasible.
    segs = [
        {"id": "A", "length": 2, "start": 0, "target": 2},
        {"id": "B", "length": 1, "start": 2, "target": 0},
    ]
    assert plan_moves(6, segs, [(4, 6)]) is None

    # With [5,6) reserved, B can buffer at 4 ([4,5)) out of A's target:
    # B 2->4, A 0->2, B 4->0 is feasible.
    moves = plan_moves(6, segs, [(5, 6)])
    assert moves is not None
    ok, reason = replay(6, segs, [(5, 6)], moves)
    assert ok, reason


def test_lex_tiebreak_id_then_dst():
    # C=4: A:[0,1)->[1,2), B:[1,2)->[0,1), free [2,4) len2
    # cheapest is 3 writes: buffer one len1 segment at dst 2 or 3.
    # B at [1,2) can go directly? B target [0,1) blocked by A.
    # A target [1,2) blocked by B. Buffer first: lexicographically the
    # first action is ("A", 2) vs ("B", 2): ids order A first -> buffer A.
    segs = [
        {"id": "A", "length": 1, "start": 0, "target": 1},
        {"id": "B", "length": 1, "start": 1, "target": 0},
    ]
    moves = plan_moves(4, segs, [])
    assert written_and_steps(segs, moves) == (3, 3)
    assert moves[0]["id"] == "A" and moves[0]["dst"] == 2
    ok, _ = replay(4, segs, [], moves)
    assert ok


def test_happy_segment_must_relocate_temporarily():
    # C=5 full volume: A len2 [0,2)->[2,4), B len2 [2,4)->[0,2), C len1
    # happy at [4,5). There is no free block at all => infeasible even
    # though C would be willing to move.
    segs = [
        {"id": "A", "length": 2, "start": 0, "target": 2},
        {"id": "B", "length": 2, "start": 2, "target": 0},
        {"id": "C", "length": 1, "start": 4, "target": 4},
    ]
    assert plan_moves(5, segs, []) is None

    # With two extra free blocks C=7, C moves to [6,7), giving contiguous
    # [4,6) length-2 buffer; a feasible plan exists.
    segs2 = [
        {"id": "A", "length": 2, "start": 0, "target": 2},
        {"id": "B", "length": 2, "start": 2, "target": 0},
        {"id": "C", "length": 1, "start": 4, "target": 4},
    ]
    moves = plan_moves(7, segs2, [])
    assert moves is not None
    ok, reason = replay(7, segs2, [], moves)
    assert ok, reason


def _random_instance(rng):
    capacity = rng.randint(2, 8)
    n = rng.randint(1, 3)

    def place(lengths, blocked=None):
        blocked = sorted(blocked or [])
        for _ in range(200):
            intervals = []
            used = list(blocked)
            ok = True
            for length in lengths:
                choices = [
                    d
                    for d in range(0, capacity - length + 1)
                    if all(
                        not (d < ue and us < d + length) for us, ue in used
                    )
                ]
                if not choices:
                    ok = False
                    break
                d = rng.choice(choices)
                interval = (d, d + length)
                intervals.append(d)
                used.append(interval)
            if ok:
                return intervals
        return None

    for _ in range(200):
        lengths = [rng.randint(1, max(1, capacity // n + 1)) for _ in range(n)]
        if sum(lengths) > capacity:
            continue
        # reserved blocks: pick a random disjoint reserved region
        reserved = []
        if rng.random() < 0.5 and capacity >= 2:
            rlo = rng.randint(0, capacity - 1)
            rhi = rng.randint(rlo + 1, min(capacity, rlo + 2))
            reserved = [(rlo, rhi)]
        starts = place(lengths, reserved)
        if starts is None:
            continue
        targets = place(lengths, reserved)
        if targets is None:
            continue
        ids = [chr(ord("A") + i) for i in range(n)]
        segs = [
            {"id": ids[i], "length": lengths[i], "start": starts[i],
             "target": targets[i]}
            for i in range(n)
        ]
        return capacity, segs, reserved
    return None


def test_fuzz_against_bruteforce():
    rng = random.Random(20261006)
    checked = 0
    for _ in range(400):
        inst = _random_instance(rng)
        if inst is None:
            continue
        capacity, segs, reserved = inst
        fast = plan_moves(capacity, segs, reserved)
        tuple_segs = [
            (s["id"], s["length"], s["start"], s["target"]) for s in segs
        ]
        slow, b_written, b_steps = brute_force(capacity, tuple_segs, reserved)
        if slow is None:
            assert fast is None, (capacity, segs, reserved, fast)
        else:
            assert fast is not None, (capacity, segs, reserved)
            ok, reason = replay(capacity, segs, reserved, fast)
            assert ok, (capacity, segs, reserved, fast, reason)
            f_written, f_steps = written_and_steps(segs, fast)
            assert (f_written, f_steps) == (b_written, b_steps), (
                capacity,
                segs,
                reserved,
                fast,
                slow,
            )
            # identical lexicographic order: rebuild slow action sequence
            cur = {s["id"]: s["start"] for s in segs}
            slow_seq = []
            for m in slow:
                slow_seq.append((m["id"], m["dst"]))
                cur[m["id"]] = m["dst"]
            fast_seq = [(m["id"], m["dst"]) for m in fast]
            assert fast_seq == slow_seq, (
                capacity,
                segs,
                reserved,
                fast_seq,
                slow_seq,
            )
        checked += 1
    assert checked >= 100, checked
