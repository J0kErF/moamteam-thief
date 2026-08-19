"""Verbal layer: word cap, landmarks, truth/lie semantics, provider fallback."""

import random

import pytest

from moamteam.constants import Direction
from moamteam.strategy.talk import (
    SafeTalk,
    TemplateTalk,
    build_talk,
    clip_words,
    extract_compass,
)

pytestmark = pytest.mark.unit


def make_template(seed=0, max_words=15, area="New York"):
    return TemplateTalk(area, max_words, random.Random(seed))


def test_hints_respect_the_word_cap():
    talk = make_template(max_words=15)
    for seed in range(20):
        talk = make_template(seed=seed)
        hint = talk.say(Direction.NORTH, "truth")
        assert len(hint.split()) <= 15


def test_truthful_hint_names_the_true_direction():
    for seed in range(10):
        hint = make_template(seed=seed).say(Direction.EAST, "truth")
        assert extract_compass(hint) is Direction.EAST


def test_lying_hint_never_names_the_true_direction():
    for seed in range(10):
        hint = make_template(seed=seed).say(Direction.EAST, "lie")
        assert extract_compass(hint) is not Direction.EAST
        assert extract_compass(hint) is not None  # a lie still claims something


def test_truthful_stay_hint_claims_no_direction():
    hint = make_template().say(None, "truth")
    assert extract_compass(hint) is None


def test_map_area_landmarks_are_used():
    hints = {make_template(seed=s).say(Direction.NORTH, "truth") for s in range(12)}
    known = ("Times Square", "Central Park", "Brooklyn Bridge", "Wall Street",
             "Grand Central", "Fifth Avenue")
    assert any(any(landmark in hint for landmark in known) for hint in hints)


def test_unknown_map_area_falls_back_to_generic_landmarks():
    hint = make_template(area="Atlantis").say(Direction.SOUTH, "truth")
    assert extract_compass(hint) is Direction.SOUTH  # still a valid hint


def test_extract_compass_variants():
    assert extract_compass("Heading NORTH past the bridge") is Direction.NORTH
    assert extract_compass("Northern lights") is None      # word boundary respected
    assert extract_compass("") is None
    assert extract_compass(None) is None


def test_clip_words():
    assert clip_words("one two three four", 2) == "one two"


class ExplodingProvider:
    def say(self, true_direction, intent):
        raise ConnectionError("model is down")


def test_safe_talk_falls_back_to_template_on_provider_failure():
    fallback = make_template()
    talk = SafeTalk(ExplodingProvider(), fallback)
    hint = talk.say(Direction.WEST, "truth")
    assert extract_compass(hint) is Direction.WEST  # template answered instead


def test_safe_talk_every_n_steps_throttles_the_provider():
    calls = []

    class CountingProvider:
        def say(self, true_direction, intent):
            calls.append(1)
            return "Provider says: going west now."

    talk = SafeTalk(CountingProvider(), make_template(), every_n_steps=3)
    for _ in range(6):
        talk.say(Direction.WEST, "truth")
    assert len(calls) == 2  # steps 3 and 6 only


def test_build_talk_default_is_pure_template():
    talk = build_talk({}, "New York", 15, random.Random(0))
    hint = talk.say(Direction.NORTH, "truth")
    assert extract_compass(hint) is Direction.NORTH
