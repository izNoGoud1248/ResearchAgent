from services.mcpSearch.searchServer import SearchServer


class TestSearchQuery:
    def testPlainKeywordsMustAllMatch(self):
        assert SearchServer.allTerms("EAGLE speculative decoding") == "all:EAGLE AND all:speculative AND all:decoding"

    def testHyphenatedTermsStayWhole(self):
        assert SearchServer.allTerms("mixture-of-experts routing") == "all:mixture-of-experts AND all:routing"

    def testQueriesWithFieldsOrOperatorsAreLeftAlone(self):
        assert SearchServer.allTerms("ti:attention AND cat:cs.CL") == "ti:attention AND cat:cs.CL"
        assert SearchServer.allTerms("LoRA OR QLoRA") == "LoRA OR QLoRA"

    def testOneWordIsLeftAlone(self):
        assert SearchServer.allTerms("transformers") == "transformers"
