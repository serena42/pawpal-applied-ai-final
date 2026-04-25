from __future__ import annotations
import json
from pathlib import Path


class TrieNode:
    __slots__ = ("children", "breeds")

    def __init__(self) -> None:
        self.children: dict[str, TrieNode] = {}
        self.breeds: list[dict] = []


class BreedTrie:
    def __init__(self) -> None:
        self.root = TrieNode()

    def insert(self, breed: dict) -> None:
        node = self.root
        for ch in breed["name"].lower():
            if ch not in node.children:
                node.children[ch] = TrieNode()
            node = node.children[ch]
        node.breeds.append(breed)

    def search(self, prefix: str, max_results: int = 8) -> list[dict]:
        node = self.root
        for ch in prefix.lower():
            if ch not in node.children:
                return []
            node = node.children[ch]
        results: list[dict] = []
        self._collect(node, results, max_results)
        return results

    def _collect(self, node: TrieNode, results: list[dict], limit: int) -> None:
        results.extend(node.breeds)
        for child in node.children.values():
            if len(results) >= limit:
                return
            self._collect(child, results, limit)


_trie: BreedTrie | None = None


def get_trie() -> BreedTrie:
    global _trie
    if _trie is None:
        path = Path(__file__).parent / "breeds.json"
        _trie = BreedTrie()
        for breed in json.loads(path.read_text(encoding="utf-8")):
            _trie.insert(breed)
    return _trie
