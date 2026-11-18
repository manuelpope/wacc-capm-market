"""A minimal OpenAI-compatible client.

The same client talks to Ollama, llmlite, llama.cpp and the OpenAI API: they
all expose ``/v1/chat/completions``. Two details matter in practice:

* some llama.cpp builds return the answer in ``reasoning_content`` instead of
  ``content``, so an empty ``content`` falls back to that field;
* those builds need the plain ``/v1/completions`` endpoint with a hand-written
  prompt, which is what ``mode="completions"`` does.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass


class LLMError(RuntimeError):
    """The model could not be reached or did not answer."""


@dataclass(frozen=True)
class LLMConfig:
    base_url: str = "http://127.0.0.1:11434/v1"
    model: str = "qwen3.5:9b-mlx"
    api_key: str | None = None
    timeout: float = 180.0
    mode: str = "chat"  # "chat" for /v1/chat/completions, "completions" for llama.cpp


class OpenAICompatibleClient:
    def __init__(self, config: LLMConfig) -> None:
        self.config = config

    # ------------------------------------------------------------------ public
    def complete(self, prompt: str, system: str | None = None) -> str:
        if self.config.mode == "completions":
            text = self._post_completions(prompt, system)
        else:
            text = self._post_chat(prompt, system)
        text = text.strip()
        if not text:
            raise LLMError("the model returned an empty response")
        return text

    def available(self) -> bool:
        """Cheap reachability check, used to decide whether to warn."""
        try:
            self._post("/models", None)
            return True
        except LLMError:
            return False

    # ----------------------------------------------------------------- private
    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        return headers

    def _post(self, path: str, payload: dict | None) -> dict:
        url = f"{self.config.base_url.rstrip('/')}{path}"
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            url, data=body, headers=self._headers(), method="GET" if payload is None else "POST"
        )
        try:
            with urllib.request.urlopen(request, timeout=self.config.timeout) as response:
                raw = response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            detail = exc.read()[:200].decode("utf-8", errors="replace")
            raise LLMError(f"{url} returned HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise LLMError(f"could not reach {url}: {exc.reason}") from exc
        except TimeoutError as exc:
            raise LLMError(f"{url} timed out after {self.config.timeout}s") from exc
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise LLMError(f"{url} returned a non-JSON payload") from exc

    def _post_chat(self, prompt: str, system: str | None) -> str:
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        base = {
            "model": self.config.model,
            "messages": messages,
            "temperature": 0,
            "stream": False,
        }
        # The reasoning mode and the default context size make a structured
        # extraction take minutes instead of seconds, so they are turned off
        # when the server understands the parameters. Servers that reject an
        # unknown field fall back to the plainer payloads.
        payloads = [
            {
                **base,
                "response_format": {"type": "json_object"},
                "reasoning_effort": "none",
                "options": {"num_ctx": 8192, "num_predict": 600},
            },
            {**base, "response_format": {"type": "json_object"}},
            base,
        ]
        data: dict = {}
        last_error: LLMError | None = None
        for payload in payloads:
            try:
                data = self._post("/chat/completions", payload)
                break
            except LLMError as exc:
                last_error = exc
        if not data:
            raise last_error or LLMError("the model could not be reached")

        choices = data.get("choices") or []
        if not choices:
            raise LLMError("the model returned no choices")
        message = choices[0].get("message") or {}
        content = (message.get("content") or "").strip()
        if not content:
            content = (message.get("reasoning_content") or "").strip()
        if not content:
            content = (choices[0].get("text") or "").strip()
        return content

    def _post_completions(self, prompt: str, system: str | None) -> str:
        full_prompt = f"{system}\n\n{prompt}" if system else prompt
        payload = {
            "model": self.config.model,
            "prompt": full_prompt,
            "temperature": 0,
            "stream": False,
            "max_tokens": 900,
        }
        data = self._post("/completions", payload)
        choices = data.get("choices") or []
        if not choices:
            raise LLMError("the model returned no choices")
        return (choices[0].get("text") or "").strip()
