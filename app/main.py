"""HTTP layer for the volume segment relocation service."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
    model_validator,
)

from .planner import MAX_U64, plan_moves

app = FastAPI(
    title="Volume Segment Relocation Planner",
    version="1.0.0",
    description=(
        "Plan whole-segment copies that relocate non-overlapping volume "
        "segments to non-overlapping target intervals while avoiding "
        "reserved regions."
    ),
)


class Segment(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: StrictStr = Field(min_length=1)
    start: StrictInt = Field(ge=0, le=MAX_U64)
    length: StrictInt = Field(ge=0, le=MAX_U64)
    target: StrictInt = Field(ge=0, le=MAX_U64)


class PlanRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    capacity: StrictInt = Field(ge=0, le=MAX_U64)
    segments: list[Segment]
    reserved: list[tuple[StrictInt, StrictInt]] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate(self) -> "PlanRequest":
        # StrictInt covers scalars; range checks on tuples are still needed.
        for lo, hi in self.reserved:
            if not (0 <= lo <= hi <= self.capacity):
                raise ValueError(
                    "reserved region [start, end) must satisfy "
                    "0 <= start <= end <= capacity"
                )

        ids = [seg.id for seg in self.segments]
        if len(set(ids)) != len(ids):
            raise ValueError("segment ids must be unique")

        currents: list[tuple[int, int, str]] = []
        targets: list[tuple[int, int, str]] = []
        for seg in self.segments:
            if seg.length <= 0:
                raise ValueError(f"segment {seg.id!r} length must be positive")
            if seg.start + seg.length > self.capacity:
                raise ValueError(
                    f"segment {seg.id!r} current interval exceeds capacity"
                )
            if seg.target + seg.length > self.capacity:
                raise ValueError(
                    f"segment {seg.id!r} target interval exceeds capacity"
                )
            currents.append((seg.start, seg.start + seg.length, seg.id))
            targets.append((seg.target, seg.target + seg.length, seg.id))

        _check_pairwise_overlap(currents, "current")
        _check_pairwise_overlap(targets, "target")

        for lo, hi in self.reserved:
            for start, end, seg_id in currents:
                if start < hi and lo < end:
                    raise ValueError(
                        f"segment {seg_id!r} current interval intersects a "
                        "reserved region"
                    )
            for start, end, seg_id in targets:
                if start < hi and lo < end:
                    raise ValueError(
                        f"segment {seg_id!r} target interval intersects a "
                        "reserved region"
                    )
        return self


def _check_pairwise_overlap(
    intervals: list[tuple[int, int, str]], kind: str
) -> None:
    ordered = sorted(intervals)
    for (s1, e1, id1), (s2, e2, id2) in zip(ordered, ordered[1:]):
        if s1 < e2 and s2 < e1:
            raise ValueError(
                f"{kind} intervals of segments {id1!r} and {id2!r} overlap"
            )


class Move(BaseModel):
    id: str
    src: int
    dst: int


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/plans")
def create_plan(request: PlanRequest) -> JSONResponse:
    ordered = sorted(request.segments, key=lambda s: s.id)
    result = plan_moves(
        capacity=request.capacity,
        segments=[
            {
                "id": s.id,
                "length": s.length,
                "start": s.start,
                "target": s.target,
            }
            for s in ordered
        ],
        reserved=request.reserved,
    )

    if result is None:
        return JSONResponse(status_code=200, content={"feasible": False})

    length_of = {s.id: s.length for s in request.segments}
    written_blocks = sum(length_of[move["id"]] for move in result)
    return JSONResponse(
        status_code=200,
        content={
            "feasible": True,
            "moves": result,
            "steps": len(result),
            "written_blocks": written_blocks,
        },
    )
