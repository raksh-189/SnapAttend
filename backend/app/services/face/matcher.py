"""Pure matching logic: threshold classification and cross-image dedupe.

No I/O, no DB — operates on values produced by the engine and the
embedding repository, so it is unit-testable with synthetic data.
"""

import uuid
from dataclasses import dataclass, field

from app.models.enums import MatchStatus

# Faces detected below this score in classroom photos are kept as evidence
# (crop + detection row) but never auto-matched — small/blurry faces produce
# unreliable embeddings. Lower than the enrollment bar on purpose: classroom
# faces are far from the camera.
MIN_SESSION_DET_SCORE = 0.40


@dataclass
class FaceOutcome:
    """Classification of one detected face within a session.

    `student_id`/`confidence` are set for matched (and duplicate) faces;
    unknown and low_quality faces carry only the evidence crop.
    """

    image_index: int  # which session image the face came from
    face_index: int  # index within that image's detections
    status: MatchStatus
    student_id: uuid.UUID | None = None
    confidence: float | None = None
    # Runner-up candidates, useful for the review UI later.
    candidates: list[tuple[uuid.UUID, float]] = field(default_factory=list)


def classify_face(
    det_score: float,
    candidates: list[tuple[uuid.UUID, float]],
    *,
    image_index: int,
    face_index: int,
    threshold: float,
) -> FaceOutcome:
    """Classify one face given its ANN candidates (best-first).

    low_quality: detector wasn't confident enough to trust the embedding.
    matched:     best candidate clears the cosine-similarity threshold.
    unknown:     nobody in the class gallery is close enough.
    """
    if det_score < MIN_SESSION_DET_SCORE:
        return FaceOutcome(
            image_index=image_index, face_index=face_index, status=MatchStatus.LOW_QUALITY
        )
    if candidates and candidates[0][1] >= threshold:
        student_id, similarity = candidates[0]
        return FaceOutcome(
            image_index=image_index,
            face_index=face_index,
            status=MatchStatus.MATCHED,
            student_id=student_id,
            confidence=similarity,
            candidates=candidates[1:],
        )
    return FaceOutcome(
        image_index=image_index,
        face_index=face_index,
        status=MatchStatus.UNKNOWN,
        candidates=candidates,
    )


def dedupe_across_images(outcomes: list[FaceOutcome]) -> list[FaceOutcome]:
    """Cross-image dedupe: a student appearing in several photos keeps exactly
    one MATCHED outcome (highest confidence); the rest become DUPLICATE.

    Mutates statuses in place and returns the same list for convenience.
    """
    best_by_student: dict[uuid.UUID, FaceOutcome] = {}
    for outcome in outcomes:
        if outcome.status is not MatchStatus.MATCHED or outcome.student_id is None:
            continue
        current = best_by_student.get(outcome.student_id)
        if current is None or (outcome.confidence or 0.0) > (current.confidence or 0.0):
            if current is not None:
                current.status = MatchStatus.DUPLICATE
            best_by_student[outcome.student_id] = outcome
        else:
            outcome.status = MatchStatus.DUPLICATE
    return outcomes
