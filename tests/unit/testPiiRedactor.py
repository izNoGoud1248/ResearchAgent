from libs.guardrails.piiRedactor import PiiRedactor


class TestPiiRedactor:
    redactor = PiiRedactor()

    def testRedactsCommonPii(self):
        result = self.redactor.redact(
            "Mail jane.doe@example.com or call +1 415-555-0132, card 4111 1111 1111 1111, ssn 123-45-6789."
        )
        assert "jane.doe" not in result.value
        assert "415-555-0132" not in result.value
        assert "4111" not in result.value
        assert "123-45-6789" not in result.value
        assert result.found == {"email": 1, "phone": 1, "card": 1, "ssn": 1}

    def testKeepsNumbersThatFailLuhn(self):
        result = self.redactor.redact("order 1234 5678 9012 3456")
        assert result.value == "order 1234 5678 9012 3456"
        assert result.found == {}

    def testKeepsArxivIdsAndDates(self):
        text = "See arXiv:2401.12345v2 published 2024-01-15."
        assert self.redactor.redact(text).value == text

    def testRedactsApiKeysAndIps(self):
        result = self.redactor.redact("key sk-proj-abcdefghijklmnopqrstuvwx from 10.0.0.12, version 1.2.3.999")
        assert result.found == {"apiKey": 1, "ipAddress": 1}
        assert "1.2.3.999" in result.value

    def testWalksNestedToolPayloads(self):
        result = self.redactor.redact({"papers": [{"author": "x@y.org", "year": 2024}]})
        assert result.value == {"papers": [{"author": "[REDACTED:email]", "year": 2024}]}
