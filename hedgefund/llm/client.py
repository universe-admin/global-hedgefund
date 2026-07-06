"""Thin Anthropic wrapper with a hard offline guarantee.

Every agent asks the desk's ``LLMClient`` for a narrative. When the Anthropic
SDK + API key are present the narrative is written by Claude; otherwise
``complete`` returns ``None`` and the caller falls back to its deterministic
quant template. The desk therefore *always* produces a verdict — the LLM
upgrades the prose and judgment, it is never a hard dependency.
"""

from __future__ import annotations

import os
from typing import Optional

from hedgefund.config import Config, DEFAULT_CONFIG

try:  # pragma: no cover
    import anthropic as _anthropic
except Exception:
    _anthropic = None


class LLMClient:
    def __init__(self, config: Config = DEFAULT_CONFIG):
        self.config = config
        self._client = None
        if (
            config.llm_mode != "off"
            and _anthropic is not None
            and os.environ.get("ANTHROPIC_API_KEY")
        ):  # pragma: no cover - needs live key
            try:
                self._client = _anthropic.Anthropic()
            except Exception:
                self._client = None

    @property
    def enabled(self) -> bool:
        return self._client is not None

    def complete(self, system: str, prompt: str) -> Optional[str]:
        """Return the model's reply, or None when running offline."""
        if self._client is None:
            return None
        try:  # pragma: no cover - needs live key
            msg = self._client.messages.create(
                model=self.config.llm_model,
                max_tokens=self.config.llm_max_tokens,
                system=system,
                messages=[{"role": "user", "content": prompt}],
            )
            return "".join(
                block.text for block in msg.content if block.type == "text"
            ).strip()
        except Exception:
            return None
