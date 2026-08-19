"""LLM hint providers (App. F table 21) — every one optional, every one wrapped
by ``SafeTalk`` in ``talk.py`` so a slow or dead model can never cost the turn.

  ollama     — local model via the Ollama HTTP API (0 API tokens).
  claude_api — a small Anthropic cloud model (counted against the token budget).
  claude_cli — ``claude -p`` subprocess (highest cost).
"""

import json
import subprocess
import urllib.request

from moamteam.constants import Direction


def llm_prompt(true_direction: Direction | None, intent: str, max_words: int) -> str:
    moved = true_direction.name.lower() if true_direction else "nowhere (stayed put)"
    goal = ("state your true direction" if intent == "truth"
            else "mislead about your direction (claim a different one)")
    return (
        f"You are a fugitive taunting a chasing cop in a grid pursuit game. "
        f"You actually moved {moved}. In ONE sentence of at most {max_words} words, "
        f"{goal}. Mention exactly one compass word (north/south/east/west) unless you "
        f"stayed put and are being truthful. No quotes, no explanations."
    )


def _clip_words(text: str, max_words: int) -> str:
    return " ".join(text.split()[:max_words])


class OllamaTalk:
    """Local model via Ollama's generate endpoint — free and unlimited."""

    def __init__(self, url: str, model: str, hint_max_words: int, timeout: float):
        self._url = url
        self._model = model
        self._max_words = hint_max_words
        self._timeout = timeout

    def say(self, true_direction: Direction | None, intent: str) -> str:
        prompt = llm_prompt(true_direction, intent, self._max_words)
        body = json.dumps({"model": self._model, "prompt": prompt, "stream": False})
        request = urllib.request.Request(
            self._url, data=body.encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=self._timeout) as response:
            reply = json.loads(response.read().decode("utf-8"))
        return _clip_words(reply.get("response", "").strip(), self._max_words)


class ClaudeApiTalk:
    """Small Anthropic cloud model; consumption counts against the series budget."""

    def __init__(self, model: str, hint_max_words: int, timeout: float):
        self._model = model
        self._max_words = hint_max_words
        self._timeout = timeout

    def say(self, true_direction: Direction | None, intent: str) -> str:
        import anthropic  # optional dependency; ImportError falls back to template

        client = anthropic.Anthropic(timeout=self._timeout)
        response = client.messages.create(
            model=self._model,
            max_tokens=60,
            messages=[{"role": "user",
                       "content": llm_prompt(true_direction, intent, self._max_words)}],
        )
        return _clip_words(response.content[0].text.strip(), self._max_words)


class ClaudeCliTalk:
    """``claude -p`` subprocess — highest cost; provided for completeness."""

    def __init__(self, executable: str, hint_max_words: int, timeout: float):
        self._executable = executable
        self._max_words = hint_max_words
        self._timeout = timeout

    def say(self, true_direction: Direction | None, intent: str) -> str:
        result = subprocess.run(
            [self._executable, "-p", llm_prompt(true_direction, intent, self._max_words)],
            capture_output=True, text=True, timeout=self._timeout, check=True,
        )
        return _clip_words(result.stdout.strip(), self._max_words)
