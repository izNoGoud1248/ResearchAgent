from services.mcpSearch.searchServer import SearchServer


class TestSearchQuery:
    def testPlainKeywordsMustAllMatch(self):
        assert SearchServer.allTerms("EAGLE speculative decoding") == "all:EAGLE AND all:speculative AND all:decoding"

    def testHyphenatedTermsStayWhole(self):
        assert SearchServer.allTerms("mixture-of-experts routing") == "all:mixture-of-experts AND all:routing"

    def testQueriesWithFieldsOrOperatorsAreLeftAlone(self):
        assert SearchServer.allTerms("ti:attention AND cat:cs.CL") == "ti:attention AND cat:cs.CL"
        assert SearchServer.allTerms("LoRA OR QLoRA") == "LoRA OR QLoRA"

    def testTopUpsMustShareHalfTheTerms(self):
        galaxy = {"title": "The EAGLE simulations of galaxy formation", "summary": "Cosmological hydrodynamical simulations."}
        medusa = {"title": "Medusa", "summary": "A speculative decoding framework with multiple decoding heads."}
        assert not SearchServer.coversHalf("EAGLE speculative decoding", galaxy)
        assert SearchServer.coversHalf("EAGLE speculative decoding", medusa)

    def testOneWordIsLeftAlone(self):
        assert SearchServer.allTerms("transformers") == "transformers"
