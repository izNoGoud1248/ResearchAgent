from datetime import UTC, datetime

from libs.knowledge.knowledgeGraph import KnowledgeGraph
from libs.knowledge.knowledgeVault import KnowledgeVault, VaultReport

report = """# Speculative Decoding Compared

Medusa adds decoding heads [arXiv:2401.10774v3]. Drafting is covered in [arXiv:2203.16487v6 §Results].

## References

1. [Medusa: Simple LLM Inference Acceleration](https://arxiv.org/abs/2401.10774v3)
2. [Speculative Decoding](https://arxiv.org/abs/2203.16487)
"""


class TestKnowledgeVault:
    def vault(self, tmp_path) -> KnowledgeVault:
        return KnowledgeVault(tmp_path, llm=None)  # type: ignore[arg-type]

    def testCitationsBecomeLinksToPaperNotes(self, tmp_path):
        linked = self.vault(tmp_path).linked(report)
        assert "[[arXiv 2401.10774|arXiv:2401.10774v3]]" in linked
        assert "[[arXiv 2203.16487|arXiv:2203.16487v6 §Results]]" in linked
        assert "](https://arxiv.org/abs/2203.16487)" in linked

    def testPapersTakeTitlesFromFindingsThenReferences(self, tmp_path):
        record = VaultReport("run1", "q", report, datetime.now(UTC), papers=[{"id": "2401.10774v3", "title": "Medusa", "published": "2024-01-19T00:00:00"}])
        papers = self.vault(tmp_path).papers(record)
        assert papers["2401.10774"]["title"] == "Medusa"
        assert papers["2401.10774"]["published"] == "2024-01-19"
        assert papers["2203.16487"]["title"] == "Speculative Decoding"
        assert papers["2203.16487"]["published"] == ""

    def testNoteNamesAreSafeForObsidianAndWindows(self):
        assert KnowledgeVault.fileName('What is "RAG"? A/B tests: #1 [draft]') == "What is RAG A B tests 1 draft"
        assert KnowledgeVault.fileName("???") == "Untitled"

    def testGraphLinksReportsPapersTopicsAndHandWrittenNotes(self, tmp_path):
        vault = self.vault(tmp_path)
        vault.write(vault.path("report", "2026-10-31 Speculative Decoding Compared"), {"type": "report", "title": "Speculative Decoding Compared", "runId": "run1"},
                    "Topics: [[Speculative Decoding]]\n\n" + vault.linked(report))
        vault.write(vault.path("paper", "arXiv 2401.10774"), {"type": "paper", "title": "Medusa"}, "# Medusa\n")
        vault.write(vault.path("topic", "Speculative Decoding"), {"type": "topic"}, "# Speculative Decoding\n")
        (tmp_path / "My idea.md").write_text("Try [[Speculative Decoding]] on small models. [[Missing note]]", encoding="utf-8")

        graph = KnowledgeGraph(tmp_path).build()
        types = {node["id"]: node["type"] for node in graph["nodes"]}
        assert types == {"2026-10-31 Speculative Decoding Compared": "report", "arXiv 2401.10774": "paper", "Speculative Decoding": "topic", "My idea": "note"}
        edges = {(edge["source"], edge["target"]) for edge in graph["edges"]}
        # Links to notes that do not exist (the unread paper, "Missing note") are not edges.
        assert edges == {
            ("2026-10-31 Speculative Decoding Compared", "Speculative Decoding"),
            ("2026-10-31 Speculative Decoding Compared", "arXiv 2401.10774"),
            ("My idea", "Speculative Decoding"),
        }
        labels = {node["id"]: node["label"] for node in graph["nodes"]}
        assert labels["arXiv 2401.10774"] == "Medusa"
        assert next(node for node in graph["nodes"] if node["id"] == "Speculative Decoding")["links"] == 2

    def testEmptyOrMissingVaultGivesAnEmptyGraph(self, tmp_path):
        assert KnowledgeGraph(tmp_path / "absent").build() == {"nodes": [], "edges": []}
