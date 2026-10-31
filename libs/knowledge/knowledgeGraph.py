import re
from pathlib import Path
from typing import Any

import yaml


class KnowledgeGraph:
    """Builds the vault's graph from the notes themselves: a node per note, an edge per [[wikilink]].

    Reading the files, not a database, means notes people add or link in Obsidian show up too.
    """

    wikilink = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|[^\]]*)?\]\]")
    kinds = {"Reports": "report", "Papers": "paper", "Topics": "topic"}

    def __init__(self, root: Path):
        self.root = root

    @staticmethod
    def split(text: str) -> tuple[dict[str, Any], str]:
        if text.startswith("---\n"):
            frontMatter, _, body = text[4:].partition("\n---")
            meta = yaml.safe_load(frontMatter)
            return (meta if isinstance(meta, dict) else {}), body
        return {}, text

    def build(self) -> dict[str, Any]:
        notes: dict[str, dict[str, Any]] = {}
        links: dict[str, list[str]] = {}
        for path in sorted(self.root.rglob("*.md")) if self.root.exists() else []:
            if ".obsidian" in path.parts or ".trash" in path.parts:
                continue
            meta, body = self.split(path.read_text(encoding="utf-8"))
            kind = self.kinds.get(path.relative_to(self.root).parts[0], "note")
            notes[path.stem] = {
                "id": path.stem,
                "type": kind,
                "label": str(meta.get("title") or meta.get("question") or path.stem) if kind != "topic" else path.stem,
                "meta": {key: meta[key] for key in ("runId", "question", "style", "created", "published", "url", "arxiv") if meta.get(key)},
            }
            links[path.stem] = [target.strip() for target in self.wikilink.findall(body)]
        edges = {
            tuple(sorted((source, target)))
            for source, targets in links.items()
            for target in targets
            if target in notes and target != source
        }
        degree = {note: 0 for note in notes}
        for source, target in edges:
            degree[source] += 1
            degree[target] += 1
        return {
            "nodes": [note | {"links": degree[note["id"]]} for note in notes.values()],
            "edges": [{"source": source, "target": target} for source, target in sorted(edges)],
        }
