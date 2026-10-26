"""App-aware ranking for interactive tool search, not automatic preloading.

Adapted from the upstream toolset-aware index. Only the current request's
registry is searched; ranking cannot attach tools or change authorization.
"""
from __future__ import annotations

import re
from collections import deque
from typing import TYPE_CHECKING

from app.agent_loop_lib.tools.index import ToolIndex, ToolMatch, _toolset_membership

if TYPE_CHECKING:
    from app.agent_loop_lib.tools.base import ToolSummary
    from app.agent_loop_lib.tools.registry import ToolRegistry, ToolsetGroup

_STOPWORDS = frozenset("a about all an and any are at be by for from i in into is it its me my of on or our please some that the their these this those to use using via we with you your".split())
_GENERIC = frozenset("attached context mcp model protocol server servers tool tools toolset".split())
_WORDS = re.compile(r"[a-z0-9]+")
_CAMEL = re.compile(r"([a-z0-9])([A-Z])")


def _fold(word: str) -> str:
    if len(word) <= 3:
        return word
    if word.endswith("ies") and len(word) > 4:
        return word[:-3] + "y"
    if word.endswith(("sses", "uses")):
        return word[:-2]
    if word.endswith("s") and not word.endswith(("ss", "us", "is")):
        return word[:-1]
    return word


def _ordered_terms(text: str) -> list[str]:
    text = _CAMEL.sub(r"\1 \2", text).lower()
    return [_fold(word) for word in _WORDS.findall(text) if word not in _STOPWORDS]


def _terms(text: str) -> set[str]:
    return set(_ordered_terms(text))


def _app_phrases(group: ToolsetGroup) -> set[tuple[str, ...]]:
    names = [group.name.replace("_", " ")]
    if " — " in group.description:
        names.append(group.description.split(" — ", 1)[0])
    return {
        tuple(word for word in _ordered_terms(name) if len(word) >= 3 and word not in _GENERIC)
        for name in names
    } - {()}


def _mentions(terms: list[str], app_words: set[str]) -> list[tuple[set[str], set[str], list[str]]]:

    spots: list[tuple[int, int, set[str]]] = []
    for index, term in enumerate(terms):
        if term not in app_words:
            continue
        if spots and spots[-1][1] == index - 1:
            first, _, names = spots[-1]
            spots[-1] = (first, index, names | {term})
        else:
            spots.append((index, index, {term}))
    mentions = []
    for index, (first, last, names) in enumerate(spots):
        lower = (spots[index - 1][1] + first) / 2 if index else -1
        upper = (last + spots[index + 1][0]) / 2 if index + 1 < len(spots) else len(terms)
        wanted = {term for pos, term in enumerate(terms) if lower < pos <= upper and term not in app_words}
        mentions.append((names, wanted, terms[first:last + 1]))
    return mentions


def _score(wanted: set[str], summary: ToolSummary, own_words: set[str]) -> float:
    if not wanted:
        return 1.0
    name_terms = _terms(summary.name.replace("_", " ")) - own_words
    corpus = name_terms | _terms(summary.short_description) | _terms(" ".join(f"{tag.key} {tag.value}" for tag in summary.tags))
    matched = wanted & corpus
    if not matched:
        return 0.0
    in_name = wanted & name_terms
    score = (len(matched) + 0.5 * len(in_name)) / len(wanted)
    return score + (0.25 * len(in_name) / len(name_terms) if name_terms else 0.0)


class ToolsetAwareToolIndex(ToolIndex):
    """Rank named apps by nearby capabilities, interleaving cross-source hits."""

    async def search(self, registry: ToolRegistry, query: str, limit: int = 5) -> list[ToolMatch]:
        terms = _ordered_terms(query)
        if not terms or limit <= 0:
            return []
        membership = _toolset_membership(registry)
        words_of_tool: dict[str, set[str]] = {}
        phrases_of_tool: dict[str, set[tuple[str, ...]]] = {}
        for group in registry.toolsets():
            phrases = _app_phrases(group)
            words = set().union(*phrases) if phrases else set()
            for tool_name in group.tool_names:
                words_of_tool.setdefault(tool_name, set()).update(words)
                phrases_of_tool.setdefault(tool_name, set()).update(phrases)
        app_words = set().union(*words_of_tool.values()) if words_of_tool else set()
        summaries = registry.discover()

        def ranked(wanted: set[str], candidates: list[ToolSummary]) -> list[tuple[float, ToolSummary]]:
            scored = [(_score(wanted, summary, words_of_tool.get(summary.name, set())), summary) for summary in candidates]
            return sorted((pair for pair in scored if pair[0] > 0), key=lambda pair: (-pair[0], pair[1].name))

        queues = []
        for names, wanted, mention in _mentions(terms, app_words):
            candidates = [summary for summary in summaries if words_of_tool.get(summary.name, set()) & names]
            complete = [
                summary for summary in candidates
                if any(
                    mention[i:i + len(phrase)] == list(phrase)
                    for phrase in phrases_of_tool.get(summary.name, set())
                    for i in range(len(mention) - len(phrase) + 1)
                )
            ]
            queues.append(deque(ranked(wanted, complete or candidates)))
        picked: list[tuple[float, ToolSummary]] = []
        chosen: set[str] = set()
        while len(picked) < limit and any(queues):
            for queue in queues:
                while queue and queue[0][1].name in chosen:
                    queue.popleft()
                if queue and len(picked) < limit:
                    score, summary = queue.popleft()
                    picked.append((score, summary))
                    chosen.add(summary.name)
        if other_words := set(terms) - app_words:
            picked += ranked(other_words, [summary for summary in summaries if summary.name not in chosen])[:max(0, limit - len(picked))]
        return [ToolMatch(summary=summary, relevance=round(score, 3), toolset=membership.get(summary.name))
                for score, summary in picked]
