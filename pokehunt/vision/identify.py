"""Run listing photos through the vision model and get structured identities."""

from __future__ import annotations

import asyncio
import logging

from anthropic import AsyncAnthropic

from ..config import VisionConfig
from .schema import IDENTIFY_TOOL, SYSTEM_PROMPT, LotIdentification

log = logging.getLogger(__name__)


class VisionIdentifier:
    def __init__(self, config: VisionConfig, client: AsyncAnthropic | None = None) -> None:
        self._config = config
        self._client = client or AsyncAnthropic(api_key=config.api_key)

    def _build_content(self, image_urls: list[str], title: str) -> list[dict]:
        content: list[dict] = []
        for index, url in enumerate(image_urls):
            content.append({"type": "text", "text": f"Photo {index}:"})
            content.append(
                {"type": "image", "source": {"type": "url", "url": url}}
            )
        content.append(
            {
                "type": "text",
                "text": (
                    "The seller titled this listing:\n"
                    f"{title!r}\n\n"
                    "Treat the title as an unreliable hint only. Identify the "
                    "cards from the photos and call report_cards."
                ),
            }
        )
        return content

    async def identify(
        self,
        image_urls: list[str],
        title: str,
        max_images: int = 8,
        retries: int = 2,
    ) -> LotIdentification:
        images = image_urls[:max_images]
        if not images:
            return LotIdentification(model=self._config.model, error="no images on listing")

        last_error: Exception | None = None
        for attempt in range(retries + 1):
            try:
                response = await self._client.messages.create(
                    model=self._config.model,
                    max_tokens=self._config.max_tokens,
                    system=SYSTEM_PROMPT,
                    tools=[IDENTIFY_TOOL],
                    tool_choice={"type": "tool", "name": IDENTIFY_TOOL["name"]},
                    messages=[{"role": "user", "content": self._build_content(images, title)}],
                )
                for block in response.content:
                    if getattr(block, "type", None) == "tool_use":
                        return LotIdentification.from_payload(
                            dict(block.input), self._config.model
                        )
                return LotIdentification(
                    model=self._config.model,
                    error="model returned no tool_use block",
                )
            except Exception as exc:  # noqa: BLE001 - surfaced on the alert
                last_error = exc
                if attempt < retries:
                    await asyncio.sleep(2**attempt)
                    continue
                log.warning("vision identify failed: %s", exc)

        return LotIdentification(model=self._config.model, error=str(last_error))
