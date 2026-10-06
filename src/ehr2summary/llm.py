"""Chat model adapters behind one interface, and the guard that keeps real records on local endpoints."""

from __future__ import annotations

import math
from typing import Protocol
from urllib.parse import urlparse

import httpx

from .config import ModelSettings

Message = dict[str, str]
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}


class LLMError(RuntimeError):
    pass


class PrivacyError(RuntimeError):
    """A real (not synthetic) record must not go to a remote endpoint without explicit permission."""


class ChatModel(Protocol):
    identity: str
    is_local: bool

    def complete(self, messages: list[Message], *, temperature: float = 0.0, seed: int = 0,
                 json_mode: bool = False, max_tokens: int = 1200) -> str: ...


def is_local_url(url: str) -> bool:
    return (urlparse(url).hostname or "") in LOCAL_HOSTS


def check_privacy(model: ChatModel, synthetic: bool, allow_remote: bool) -> None:
    if not synthetic and not model.is_local and not allow_remote:
        raise PrivacyError(
            f"{model.identity} is not a local endpoint. Real records stay local unless "
            "EHR2SUMMARY_ALLOW_REMOTE_RECORDS=true and your data use agreement permits it."
        )


class OpenAICompatibleChatModel:
    """Any /chat/completions endpoint: Ollama, vLLM, llama.cpp server, OpenAI."""

    def __init__(self, settings: ModelSettings, transport: httpx.BaseTransport | None = None):
        if not settings.model:
            raise LLMError("set the model name (EHR2SUMMARY_GENERATOR_MODEL or EHR2SUMMARY_JUDGE_MODEL)")
        self.identity = settings.identity
        self.is_local = is_local_url(settings.base_url)
        self._model = settings.model
        self._url = settings.base_url.rstrip("/") + "/chat/completions"
        headers = {"Authorization": f"Bearer {settings.api_key}"} if settings.api_key else {}
        self._client = httpx.Client(timeout=settings.timeout_s, headers=headers, transport=transport)

    def _post(self, body: dict) -> dict:
        last: Exception | None = None
        for _ in range(2):
            try:
                r = self._client.post(self._url, json=body)
            except httpx.HTTPError as exc:
                last = exc
                continue
            if r.status_code >= 500:
                last = LLMError(f"server error {r.status_code}")
                continue
            if r.status_code >= 400:
                raise LLMError(f"request refused with status {r.status_code}: {r.text[:200]}")
            return r.json()
        raise LLMError(f"endpoint not reachable: {last}")

    def complete(self, messages, *, temperature=0.0, seed=0, json_mode=False, max_tokens=1200) -> str:
        body = {"model": self._model, "messages": messages, "temperature": temperature, "seed": seed,
                "max_tokens": max_tokens}
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        try:
            return self._post(body)["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError("reply has no choices[0].message.content") from exc

    def score_distribution(self, messages: list[Message], seed: int = 0) -> dict[int, float]:
        """Probability of each integer score 0..10 in the first reply token (G-Eval weighting)."""
        body = {"model": self._model, "messages": messages, "temperature": 0, "seed": seed, "max_tokens": 2,
                "logprobs": True, "top_logprobs": 20}
        data = self._post(body)
        try:
            top = data["choices"][0]["logprobs"]["content"][0]["top_logprobs"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError("the endpoint returned no logprobs") from exc
        return score_distribution_from_top_logprobs(top)


def score_distribution_from_top_logprobs(top: list[dict]) -> dict[int, float]:
    probs: dict[int, float] = {}
    for entry in top:
        tok = str(entry.get("token", "")).strip()
        if tok.isdigit() and 0 <= int(tok) <= 10:
            probs[int(tok)] = probs.get(int(tok), 0.0) + math.exp(float(entry["logprob"]))
    total = sum(probs.values())
    if total <= 0:
        raise LLMError("no score token in the top logprobs")
    return {k: v / total for k, v in sorted(probs.items())}


class HFChatModel:  # pragma: no cover - needs the optional "hf" extra and a GPU for 7B models
    """Local Hugging Face model. Uses the model chat template and returns only the new text."""

    def __init__(self, settings: ModelSettings):
        try:
            from transformers import pipeline
        except ImportError as exc:
            raise LLMError("install the extra: pip install 'ehr2summary[hf]'") from exc
        self.identity = settings.identity
        self.is_local = True
        self._pipe = pipeline("text-generation", model=settings.model, device_map="auto", torch_dtype="auto")

    def complete(self, messages, *, temperature=0.0, seed=0, json_mode=False, max_tokens=1200) -> str:
        from transformers import set_seed

        set_seed(seed)
        kwargs = {"max_new_tokens": max_tokens, "return_full_text": False}
        if temperature > 0:
            kwargs.update(do_sample=True, temperature=temperature)
        else:
            kwargs.update(do_sample=False)
        out = self._pipe(messages, **kwargs)
        return out[0]["generated_text"]


class ScriptedChatModel:
    def __init__(self, replies: list[str], identity: str = "scripted:test", is_local: bool = True):
        self.replies = list(replies)
        self.identity = identity
        self.is_local = is_local
        self.calls: list[dict] = []

    def complete(self, messages, *, temperature=0.0, seed=0, json_mode=False, max_tokens=1200) -> str:
        self.calls.append({"messages": messages, "temperature": temperature, "seed": seed})
        if not self.replies:
            raise LLMError("no scripted reply left")
        return self.replies.pop(0)


def build_chat_model(settings: ModelSettings) -> ChatModel:
    if settings.provider == "openai":
        return OpenAICompatibleChatModel(settings)
    if settings.provider == "hf":
        return HFChatModel(settings)
    raise LLMError(f"provider {settings.provider!r} has no chat model (the offline provider uses no model)")
