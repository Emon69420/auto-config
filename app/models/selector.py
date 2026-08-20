"""Selector inventory model (spec section 2.2 and 4.3).

An inventory aggregates every id, class, and tag observed across the rendered
pages, with the number of pages it appeared on. The LLM compiler consumes this
to pick site-wide boilerplate.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class SelectorInventory(BaseModel):
    """Aggregated selector usage across a batch of rendered pages.

    `ids`/`classes` map a CSS selector string ("#id" / ".class") to the number
    of pages it appeared on. `tags` maps a tag name to the same page count.
    """

    model_config = ConfigDict(extra="allow")

    ids: dict[str, int] = Field(default_factory=dict)
    classes: dict[str, int] = Field(default_factory=dict)
    tags: dict[str, int] = Field(default_factory=dict)

    def top(self, ids: int, classes: int, tags: int) -> "SelectorInventory":
        """Return a new inventory limited to the most frequent entries.

        Keeps generation/DRY logic out of the prompt builder: the analyzer
        stores full counts; the LLM compiler asks for the subset it needs.
        """
        def take(counts: dict[str, int], n: int) -> dict[str, int]:
            return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:n])

        return SelectorInventory(
            ids=take(self.ids, ids),
            classes=take(self.classes, classes),
            tags=take(self.tags, tags),
        )

    def total(self) -> int:
        """Total number of distinct selectors observed."""
        return len(self.ids) + len(self.classes) + len(self.tags)