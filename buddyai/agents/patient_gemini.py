"""PatientGemini: a Gemini model that waits and tries again when Google is busy."""

import asyncio
from typing import ClassVar

from google.adk.models import Gemini


def is_busy_error(exc):
    """Return True for Gemini's temporary '503 high demand' answer."""
    return getattr(exc, "code", None) == 503 or "UNAVAILABLE" in str(exc).upper()


# Inheritance & Polymorphism: overrides one method of ADK's Gemini class. The
# agents call it exactly as before; only the behaviour on a busy answer changes.
class PatientGemini(Gemini):
    """Gemini that retries a request when the model says it is under high demand.

    A "503 high demand" answer usually clears within seconds, so a short wait
    is better than giving up. Any other error is passed on unchanged.
    """

    # ClassVar: ADK models are pydantic classes, which treat a plain class
    # attribute as a data field unless it is marked as a class-level constant.
    BUSY_RETRIES: ClassVar[int] = 2
    BUSY_WAIT_SECONDS: ClassVar[float] = 3

    async def generate_content_async(self, llm_request, stream=False):
        for attempt in range(self.BUSY_RETRIES + 1):
            answered = False
            try:
                async for response in super().generate_content_async(llm_request, stream):
                    answered = True
                    yield response
                return
            except Exception as exc:
                last_try = attempt == self.BUSY_RETRIES
                # Never repeat a request that already produced part of an answer.
                if answered or last_try or not is_busy_error(exc):
                    raise
                await asyncio.sleep(self.BUSY_WAIT_SECONDS)
