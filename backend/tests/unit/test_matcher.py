"""Unit tests for threshold classification and cross-image dedupe."""

import uuid

from app.models.enums import MatchStatus
from app.services.face.matcher import (
    MIN_SESSION_DET_SCORE,
    FaceOutcome,
    classify_face,
    dedupe_across_images,
)

THRESHOLD = 0.40
S1, S2 = uuid.uuid4(), uuid.uuid4()


def _classify(det_score, candidates):
    return classify_face(
        det_score, candidates, image_index=0, face_index=0, threshold=THRESHOLD
    )


def test_low_det_score_is_low_quality_even_with_strong_candidate():
    outcome = _classify(MIN_SESSION_DET_SCORE - 0.01, [(S1, 0.99)])
    assert outcome.status is MatchStatus.LOW_QUALITY
    assert outcome.student_id is None


def test_above_threshold_matches_best_candidate():
    outcome = _classify(0.9, [(S1, 0.62), (S2, 0.44)])
    assert outcome.status is MatchStatus.MATCHED
    assert outcome.student_id == S1
    assert outcome.confidence == 0.62
    assert outcome.candidates == [(S2, 0.44)]  # runners-up kept for review UI


def test_below_threshold_is_unknown():
    outcome = _classify(0.9, [(S1, THRESHOLD - 0.01)])
    assert outcome.status is MatchStatus.UNKNOWN
    assert outcome.student_id is None
    assert outcome.candidates == [(S1, THRESHOLD - 0.01)]


def test_exactly_at_threshold_matches():
    outcome = _classify(0.9, [(S1, THRESHOLD)])
    assert outcome.status is MatchStatus.MATCHED


def test_no_candidates_is_unknown():
    outcome = _classify(0.9, [])
    assert outcome.status is MatchStatus.UNKNOWN


def _matched(student_id, confidence, image_index=0, face_index=0):
    return FaceOutcome(
        image_index=image_index,
        face_index=face_index,
        status=MatchStatus.MATCHED,
        student_id=student_id,
        confidence=confidence,
    )


def test_dedupe_keeps_highest_confidence():
    weaker = _matched(S1, 0.55, image_index=0)
    stronger = _matched(S1, 0.71, image_index=1)
    dedupe_across_images([weaker, stronger])
    assert weaker.status is MatchStatus.DUPLICATE
    assert stronger.status is MatchStatus.MATCHED


def test_dedupe_order_independent():
    stronger = _matched(S1, 0.71, image_index=0)
    weaker = _matched(S1, 0.55, image_index=1)
    dedupe_across_images([stronger, weaker])
    assert stronger.status is MatchStatus.MATCHED
    assert weaker.status is MatchStatus.DUPLICATE


def test_dedupe_leaves_distinct_students_alone():
    a, b = _matched(S1, 0.6), _matched(S2, 0.6, face_index=1)
    dedupe_across_images([a, b])
    assert a.status is MatchStatus.MATCHED
    assert b.status is MatchStatus.MATCHED


def test_dedupe_ignores_unknown_and_low_quality():
    unknown = FaceOutcome(image_index=0, face_index=0, status=MatchStatus.UNKNOWN)
    lq = FaceOutcome(image_index=0, face_index=1, status=MatchStatus.LOW_QUALITY)
    matched = _matched(S1, 0.6, face_index=2)
    dedupe_across_images([unknown, lq, matched])
    assert unknown.status is MatchStatus.UNKNOWN
    assert lq.status is MatchStatus.LOW_QUALITY
    assert matched.status is MatchStatus.MATCHED


def test_dedupe_three_sightings_single_winner():
    outcomes = [
        _matched(S1, 0.50, image_index=0),
        _matched(S1, 0.80, image_index=1),
        _matched(S1, 0.65, image_index=2),
    ]
    dedupe_across_images(outcomes)
    statuses = [o.status for o in outcomes]
    assert statuses.count(MatchStatus.MATCHED) == 1
    assert statuses.count(MatchStatus.DUPLICATE) == 2
    winner = next(o for o in outcomes if o.status is MatchStatus.MATCHED)
    assert winner.confidence == 0.80
