"""The verbal layer (book §6.5): hints in free natural language, ≤ hint_max_words,
optionally seasoned with map_area landmarks. The move is NEVER decided here.

Four provider modes (private per-peer choice, App. F table 21):
  template   — canned sentences, ZERO tokens, offline. The default.
  ollama     — local model via the Ollama HTTP API (0 API tokens).
  claude_api — a small Anthropic cloud model (counted against the token budget).
  claude_cli — `claude -p` subprocess (highest cost).

Every LLM provider is wrapped in a hard per-step deadline with a silent fallback
to the template, so a slow or dead model can never cost us the turn.
"""

import logging
import random
import re

from moamteam.constants import Direction
from moamteam.strategy.talk_providers import (
    ClaudeApiTalk,
    ClaudeCliTalk,
    OllamaTalk,
    llm_prompt,
)

logger = logging.getLogger(__name__)

_COMPASS_WORDS = {
    "north": Direction.NORTH, "south": Direction.SOUTH,
    "east": Direction.EAST, "west": Direction.WEST,
}
_COMPASS_PATTERN = re.compile(r"\b(north|south|east|west)\b", re.IGNORECASE)

_LANDMARKS: dict[str, list[str]] = {
    "new york": ["Times Square", "Central Park", "Brooklyn Bridge", "Wall Street",
                 "Grand Central", "Fifth Avenue"],
    "london": ["Big Ben", "Camden Market", "the Tube", "Tower Bridge", "Soho"],
    "paris": ["the Louvre", "Montmartre", "the Seine", "Rue de Rivoli"],
    "": ["the old market", "the river bridge", "the clock tower", "the back alleys"],
}

_MOVE_TEMPLATES = [
    "Just slipped {direction} past {landmark}.",
    "You will never catch me — heading {direction} near {landmark}.",
    "Cutting {direction} through {landmark}, try to keep up.",
]
_STAY_TEMPLATES = [
    "Holding my ground in the shadows of {landmark}.",
    "Not moving an inch — {landmark} hides me well.",
]


def extract_compass(hint: str) -> Direction | None:
    """The receiver's parser: first compass word in the hint, if any."""
    match = _COMPASS_PATTERN.search(hint or "")
    return _COMPASS_WORDS[match.group(1).lower()] if match else None


def clip_words(text: str, max_words: int) -> str:
    words = text.split()
    return " ".join(words[:max_words])


class TemplateTalk:
    """Zero-token default: canned sentences carrying a compass cue that is either
    my true last direction (intent 'truth') or a decoy (intent 'lie')."""

    def __init__(self, map_area: str, hint_max_words: int, rng: random.Random):
        self._landmarks = _LANDMARKS.get(map_area.strip().lower(), _LANDMARKS[""])
        self._max_words = hint_max_words
        self._rng = rng

    def say(self, true_direction: Direction | None, intent: str) -> str:
        landmark = self._rng.choice(self._landmarks)
        direction = self._spoken_direction(true_direction, intent)
        if direction is None:
            template = self._rng.choice(_STAY_TEMPLATES)
            return clip_words(template.format(landmark=landmark), self._max_words)
        template = self._rng.choice(_MOVE_TEMPLATES)
        text = template.format(direction=direction.name.lower(), landmark=landmark)
        return clip_words(text, self._max_words)

    def _spoken_direction(self, true_direction: Direction | None,
                          intent: str) -> Direction | None:
        if intent == "truth":
            return true_direction
        decoys = [d for d in Direction if d is not true_direction]
        return self._rng.choice(decoys)


class SafeTalk:
    """Deadline-capped wrapper: any provider failure silently falls back to the
    zero-token template so the verbal layer can never lose us a turn.

    Metering: LLM token consumption is tracked (rule #54 — the totals are sealed
    into the end-of-game reports). The template consumes exactly zero; LLM calls
    are estimated at ~4 chars/token over prompt+reply until provider usage APIs
    are wired per-provider."""

    def __init__(self, provider, fallback: TemplateTalk, *, every_n_steps: int = 1):
        self._provider = provider
        self._fallback = fallback
        self._every = max(1, every_n_steps)
        self._step = 0
        self.provider_calls = 0
        self.tokens_used = 0

    def say(self, true_direction: Direction | None, intent: str) -> str:
        self._step += 1
        if self._provider is None or self._step % self._every:
            return self._fallback.say(true_direction, intent)
        try:
            hint = self._provider.say(true_direction, intent)
            if hint:
                self.provider_calls += 1
                prompt = llm_prompt(true_direction, intent, 15)
                self.tokens_used += (len(prompt) + len(hint)) // 4
                return hint
            return self._fallback.say(true_direction, intent)
        except Exception as exc:  # noqa: BLE001 — any provider failure is non-fatal
            logger.warning("talk provider failed (%s) — falling back to template", exc)
            return self._fallback.say(true_direction, intent)


def build_talk(private_config: dict, map_area: str, hint_max_words: int,
               rng: random.Random) -> SafeTalk:
    """Wire the [trash_talk] private config into a SafeTalk stack."""
    section = private_config.get("trash_talk", {})
    provider_name = section.get("provider", "template")
    timeout = float(section.get("timeout_seconds", 20))
    fallback = TemplateTalk(map_area, hint_max_words, rng)

    provider: OllamaTalk | ClaudeApiTalk | ClaudeCliTalk | None = None
    if provider_name == "ollama":
        provider = OllamaTalk(
            section.get("ollama_url", "http://localhost:11434/api/generate"),
            section.get("model", "llama3.2"), hint_max_words, timeout,
        )
    elif provider_name == "claude_api":
        provider = ClaudeApiTalk(section.get("model", "claude-haiku-4-5"),
                                 hint_max_words, timeout)
    elif provider_name == "claude_cli":
        provider = ClaudeCliTalk(section.get("executable", "claude"),
                                 hint_max_words, timeout)
    return SafeTalk(provider, fallback, every_n_steps=int(section.get("every_n_steps", 1)))
