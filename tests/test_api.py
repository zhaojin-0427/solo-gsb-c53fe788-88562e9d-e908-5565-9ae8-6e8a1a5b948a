"""HTTP-level tests for /plans using FastAPI's TestClient."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

client = TestClient(app)


def post(payload):
    return client.post("/plans", json=payload)


EXAMPLE = {
    "capacity": 5,
    "segments": [
        {"id": "A", "start": 0, "length": 2, "target": 2},
        {"id": "B", "start": 2, "length": 1, "target": 0},
    ],
    "reserved": [],
}


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_example_response():
    r = post(EXAMPLE)
    assert r.status_code == 200
    body = r.json()
    assert body["feasible"] is True
    assert body["steps"] == 3
    assert body["written_blocks"] == 4
    assert body["moves"] == [
        {"id": "B", "src": 2, "dst": 4},
        {"id": "A", "src": 0, "dst": 2},
        {"id": "B", "src": 4, "dst": 0},
    ]


def test_already_planned_empty():
    r = post(
        {
            "capacity": 4,
            "segments": [
                {"id": "A", "start": 0, "length": 2, "target": 0}
            ],
        }
    )
    assert r.status_code == 200
    body = r.json()
    assert body["feasible"] is True
    assert body["moves"] == []
    assert body["steps"] == 0
    assert body["written_blocks"] == 0


def test_infeasible_response():
    # full volume swap, no buffer
    r = post(
        {
            "capacity": 2,
            "segments": [
                {"id": "A", "start": 0, "length": 1, "target": 1},
                {"id": "B", "start": 1, "length": 1, "target": 0},
            ],
        }
    )
    assert r.status_code == 200
    assert r.json() == {"feasible": False}


def test_reserved_ok():
    r = post(
        {
            "capacity": 5,
            "segments": [
                {"id": "A", "start": 0, "length": 2, "target": 2}
            ],
            "reserved": [[4, 5]],
        }
    )
    assert r.status_code == 200
    assert r.json()["feasible"] is True


def _assert_422(payload):
    r = post(payload)
    assert r.status_code == 422, r.text
    return r.json()


def test_422_zero_length():
    p = {
        "capacity": 4,
        "segments": [{"id": "A", "start": 0, "length": 0, "target": 1}],
    }
    _assert_422(p)


def test_422_negative_and_overflow():
    _assert_422(
        {"capacity": -1, "segments": []}
    )
    _assert_422(
        {
            "capacity": 5,
            "segments": [
                {"id": "A", "start": 0, "length": 6, "target": 0}
            ],
        }
    )
    _assert_422(
        {
            "capacity": 5,
            "segments": [
                {"id": "A", "start": 2, "length": 4, "target": 0}
            ],
        }
    )
    _assert_422(
        {
            "capacity": 1 << 64,
            "segments": [],
        }
    )


def test_422_current_overlap():
    _assert_422(
        {
            "capacity": 5,
            "segments": [
                {"id": "A", "start": 0, "length": 3, "target": 0},
                {"id": "B", "start": 2, "length": 1, "target": 3},
            ],
        }
    )


def test_422_target_overlap():
    _assert_422(
        {
            "capacity": 5,
            "segments": [
                {"id": "A", "start": 0, "length": 1, "target": 2},
                {"id": "B", "start": 1, "length": 1, "target": 2},
            ],
        }
    )


def test_422_touch_reserved_is_ok_but_overlap_is_not():
    # touching endpoints is fine
    ok = post(
        {
            "capacity": 5,
            "segments": [
                {"id": "A", "start": 0, "length": 2, "target": 2}
            ],
            "reserved": [[2, 3]],
        }
    )
    # A's target [2,4) overlaps reserved [2,3) -> 422
    assert ok.status_code == 422
    # merely touching: reserved [4,5), target [2,4)
    fine = post(
        {
            "capacity": 5,
            "segments": [
                {"id": "A", "start": 0, "length": 2, "target": 2}
            ],
            "reserved": [[4, 5]],
        }
    )
    assert fine.status_code == 200


def test_422_duplicate_ids():
    _assert_422(
        {
            "capacity": 5,
            "segments": [
                {"id": "A", "start": 0, "length": 1, "target": 0},
                {"id": "A", "start": 1, "length": 1, "target": 1},
            ],
        }
    )


def test_422_empty_id():
    _assert_422(
        {
            "capacity": 3,
            "segments": [{"id": "", "start": 0, "length": 1, "target": 0}],
        }
    )


def test_422_bad_types_boolean_and_float():
    _assert_422(
        {
            "capacity": 5,
            "segments": [
                {"id": "A", "start": True, "length": 1, "target": 0}
            ],
        }
    )
    _assert_422(
        {
            "capacity": 5.0,
            "segments": [
                {"id": "A", "start": 0, "length": 1, "target": 0}
            ],
        }
    )
    _assert_422(
        {
            "capacity": 5,
            "segments": [
                {"id": 4, "start": 0, "length": 1, "target": 0}
            ],
        }
    )


def test_422_missing_field():
    _assert_422({"capacity": 5})
    _assert_422(
        {
            "capacity": 5,
            "segments": [{"id": "A", "start": 0, "length": 1}],
        }
    )


def test_422_bad_reserved():
    _assert_422(
        {
            "capacity": 5,
            "segments": [],
            "reserved": [[3, 2]],
        }
    )
    _assert_422(
        {
            "capacity": 5,
            "segments": [],
            "reserved": [[2, 9]],
        }
    )
