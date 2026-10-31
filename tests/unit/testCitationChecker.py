from evals.citationChecker import CitationChecker


class TestCitationParsing:
    report = """
# Brief
Attention replaces recurrence [arXiv:1706.03762v7]. Residual links help depth [1512.03385].
StruQ separates prompts from data (arXiv: 2402.06363v2), and again [2402.06363].

## References
1. [Attention Is All You Need](https://arxiv.org/abs/1706.03762v7)
2. [Deep residual learning for image recognition.](https://arxiv.org/abs/1512.03385)
3. [A Paper That Is Not This One](https://arxiv.org/abs/2402.06363v2)
"""

    def testFindsEveryCitationOnceWithoutVersion(self):
        assert CitationChecker.citedIds(self.report) == ["1512.03385", "1706.03762", "2402.06363"]

    def testReadsTitlesFromReferenceLinks(self):
        titles = CitationChecker.referenceTitles(self.report)
        assert titles["1706.03762"] == "Attention Is All You Need"
        assert titles["2402.06363"] == "A Paper That Is Not This One"

    def testTitleMatchIgnoresCaseAndPunctuation(self):
        assert CitationChecker.titlesMatch("Deep residual learning for image recognition.", "Deep Residual Learning for Image Recognition")
        assert not CitationChecker.titlesMatch("A Paper That Is Not This One", "StruQ: Defending Against Prompt Injection with Structured Queries")

    def testReportWithoutCitations(self):
        assert CitationChecker.citedIds("No sources here. Year 2024 and 3.14159 are not ids.") == []
