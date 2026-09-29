"""Provider-agnostic LLM interface. LLMs extract, classify, summarise and draft —
they NEVER make eligibility decisions (that is app.eligibility only).

Every call uses a versioned prompt from prompts/ and a Pydantic schema; output that
fails validation is discarded (callers fall back to deterministic extractors).
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Protocol, TypeVar

from pydantic import BaseModel, ValidationError

from app.core.config import settings

log = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)


@dataclass
class Prompt:
    name: str
    version: str
    system: str
    user_template: str

    def render(self, **vars: str) -> str:
        out = self.user_template
        for k, v in vars.items():
            out = out.replace("{{" + k + "}}", v)
        return out


@lru_cache(maxsize=64)
def load_prompt(name: str) -> Prompt:
    """prompts/<name>.md with front-matter `version:` and `## system` / `## user` sections."""
    path = settings.prompts_dir / f"{name}.md"
    text = path.read_text(encoding="utf-8")
    version = re.search(r"^version:\s*(\S+)", text, re.M)
    system = re.search(r"^## system\s*\n(.*?)(?=^## user)", text, re.S | re.M)
    user = re.search(r"^## user\s*\n(.*)", text, re.S | re.M)
    if not (version and system and user):
        raise ValueError(f"Malformed prompt file {path}")
    return Prompt(name, version.group(1), system.group(1).strip(), user.group(1).strip())


@dataclass
class LLMResult:
    data: BaseModel | None
    model: str
    prompt_version: str
    raw: str
    error: str | None = None


class LLMProvider(Protocol):
    name: str

    def structured(self, prompt_name: str, schema: type[T], **vars: str) -> LLMResult: ...


class NullProvider:
    """No LLM configured: callers use deterministic extractors only."""
    name = "none"

    def structured(self, prompt_name: str, schema: type[T], **vars: str) -> LLMResult:
        return LLMResult(None, "none", load_prompt(prompt_name).version, "", "no LLM provider configured")


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, api_key: str | None, model: str):
        import anthropic
        self._anthropic = anthropic
        self.client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()
        self.model = model

    def structured(self, prompt_name: str, schema: type[T], **vars: str) -> LLMResult:
        prompt = load_prompt(prompt_name)
        try:
            response = self.client.beta.messages.create(
                model=self.model,
                max_tokens=16000,
                system=prompt.system,
                messages=[{"role": "user", "content": prompt.render(**vars)}],
                output_config={"effort": "medium", "format": {"type": "json_schema", "schema": _strict_schema(schema)}},
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
        except self._anthropic.RateLimitError as e:
            return LLMResult(None, self.model, prompt.version, "", f"rate limited: {e}")
        except self._anthropic.APIStatusError as e:
            return LLMResult(None, self.model, prompt.version, "", f"API error {e.status_code}: {e.message}")
        except self._anthropic.APIConnectionError as e:
            return LLMResult(None, self.model, prompt.version, "", f"connection error: {e}")
        if response.stop_reason == "refusal":
            cat = response.stop_details.category if response.stop_details else None
            return LLMResult(None, response.model, prompt.version, "", f"refused (category={cat})")
        if response.stop_reason == "max_tokens":
            return LLMResult(None, response.model, prompt.version, "", "output truncated (max_tokens)")
        text = next((b.text for b in response.content if b.type == "text"), "")
        try:
            return LLMResult(schema.model_validate_json(text), response.model, prompt.version, text)
        except ValidationError as e:
            log.warning("LLM output failed schema validation for %s: %s", prompt_name, e)
            return LLMResult(None, response.model, prompt.version, text, "schema validation failed")


def _strict_schema(schema: type[BaseModel]) -> dict:
    """Pydantic JSON schema → strict structured-output schema (no extra keys, all required)."""
    s = schema.model_json_schema()

    def fix(node: dict) -> None:
        if node.get("type") == "object" or "properties" in node:
            node["additionalProperties"] = False
            node["required"] = list(node.get("properties", {}))
        for v in list(node.get("properties", {}).values()) + list(node.get("$defs", {}).values()):
            fix(v)
        for key in ("items", "anyOf"):
            sub = node.get(key)
            if isinstance(sub, dict):
                fix(sub)
            elif isinstance(sub, list):
                for x in sub:
                    fix(x)
        node.pop("default", None)
        node.pop("title", None)
    fix(s)
    return json.loads(json.dumps(s))


_provider: LLMProvider | None = None


def get_llm() -> LLMProvider:
    global _provider
    if _provider is None:
        if settings.llm_provider == "anthropic":
            _provider = AnthropicProvider(settings.anthropic_api_key, settings.anthropic_model)
        else:
            _provider = NullProvider()
    return _provider


def set_llm(provider: LLMProvider | None) -> None:
    """Test hook."""
    global _provider
    _provider = provider
