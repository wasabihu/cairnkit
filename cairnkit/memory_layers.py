"""Host-owned fact ordering and lossless grouping, independent of storage or clocks.

Rank original facts, never summary rows. Hosts supply stable source order, topic,
protection and a reversible renderer. Unknown origins remain detailed/protected.
"""

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class LayeredFact:
    text: str
    order: tuple[float, str] | None
    topic: str
    protected: bool = False


@dataclass(frozen=True)
class MemoryLayers:
    facts: tuple[LayeredFact, ...]
    levels: dict[str, str]

    def level(self, text: str) -> str:
        return self.levels[text]

    def protected(self, text: str) -> bool:
        return self.levels[text] == "recent" or next(
            f.protected for f in self.facts if f.text == text
        )

    def compact(self, render: Callable[[list[str], str], str], *, max_group: int = 16) -> list[str]:
        if max_group < 1:
            raise ValueError("max_group must be positive")
        groups: dict[tuple[str, str], list[str]] = defaultdict(list)
        result = []
        for fact in self.facts:
            level = self.level(fact.text)
            if level == "recent" or not fact.topic:
                result.append(fact.text)
            else:
                groups[level, fact.topic].append(fact.text)
        for (level, _), texts in groups.items():
            for offset in range(0, len(texts), max_group):
                part = texts[offset : offset + max_group]
                try:
                    text = render(part, level)
                    if not isinstance(text, str) or not text.strip():
                        raise ValueError("empty rendering")
                    if len(text) > len("\n§\n".join(part)):
                        result.extend(part)
                    else:
                        result.append(text)
                except ValueError:
                    result.extend(part)
        return result


def layer_facts(facts: list[LayeredFact], *, recent_count: int, middle_count: int) -> MemoryLayers:
    if not 0 < recent_count <= middle_count:
        raise ValueError("require 0 < recent_count <= middle_count")
    if len({f.text for f in facts}) != len(facts):
        raise ValueError("facts must be unique before ranking")
    ordered = sorted(facts, key=lambda f: (f.order is not None, f.order or (0, ""), f.text))
    known = sorted(
        (f for f in facts if f.order is not None), key=lambda f: (f.order, f.text), reverse=True
    )
    levels = {f.text: "recent" for f in facts}
    for rank, fact in enumerate(known):
        levels[fact.text] = (
            "recent" if rank < recent_count else "middle" if rank < middle_count else "distant"
        )
    return MemoryLayers(tuple(ordered), levels)
