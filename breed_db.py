"""Trie-backed breed lookup used for pet profile suggestions."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path


 # pylint: disable=too-few-public-methods
class TrieNode:
    """A single node in the breed prefix trie."""

    __slots__ = ("children", "breeds")

    def __init__(self) -> None:
        self.children: dict[str, TrieNode] = {}
        self.breeds: list[dict] = []


 # pylint: disable=too-few-public-methods
class BreedTrie:
    """Prefix trie for fast breed-name lookup."""

    def __init__(self) -> None:
        self.root = TrieNode()

    def insert(self, breed: dict) -> None:
        """Insert a breed record into the trie."""
        node = self.root
        for ch in breed["name"].lower():
            if ch not in node.children:
                node.children[ch] = TrieNode()
            node = node.children[ch]
        node.breeds.append(breed)

    def search(self, prefix: str, max_results: int = 8) -> list[dict]:
        """Return breeds whose names match the provided prefix."""
        node = self.root
        for ch in prefix.lower():
            if ch not in node.children:
                return []
            node = node.children[ch]
        results: list[dict] = []
        self._collect(node, results, max_results)
        return results

    def _collect(self, node: TrieNode, results: list[dict], limit: int) -> None:
        """Depth-first traversal that collects matching breeds up to limit."""
        results.extend(node.breeds)
        for child in node.children.values():
            if len(results) >= limit:
                return
            self._collect(child, results, limit)


@lru_cache(maxsize=1)
def get_trie() -> BreedTrie:
    """Load the shared breed trie from the bundled JSON dataset."""
    path = Path(__file__).parent / "breeds.json"
    trie = BreedTrie()
    for breed in json.loads(path.read_text(encoding="utf-8")):
        trie.insert(breed)
    return trie
