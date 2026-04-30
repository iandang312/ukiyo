from __future__ import annotations

from functools import lru_cache

from openai import AsyncOpenAI

from ukiyo_service.config import get_settings

EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIMENSIONS = 1536
MAX_BATCH_INPUTS = 2048


class EmbeddingsConfigError(RuntimeError):
    """Raised when embeddings cannot run because configuration is missing."""


@lru_cache(maxsize=1)
def _client() -> AsyncOpenAI:
    api_key = get_settings().OPENAI_API_KEY
    if not api_key:
        raise EmbeddingsConfigError(
            "OPENAI_API_KEY is not set. Add it to .env (or your environment) "
            "before calling embed()/embed_batch()."
        )
    return AsyncOpenAI(api_key=api_key)


async def embed(text: str) -> list[float]:
    """Embed a single string. Returns a 1536-dim vector."""
    [vector] = await embed_batch([text])
    return vector


async def embed_batch(texts: list[str]) -> list[list[float]]:
    """Embed a list of strings in a single HTTP request.

    Order of returned vectors matches the order of `texts`.
    """
    if not texts:
        return []
    if len(texts) > MAX_BATCH_INPUTS:
        raise ValueError(
            f"embed_batch received {len(texts)} inputs; OpenAI caps each call at "
            f"{MAX_BATCH_INPUTS}. Chunk the inputs at the call site."
        )

    response = await _client().embeddings.create(
        model=EMBEDDING_MODEL,
        input=texts,
    )
    return [item.embedding for item in response.data]
