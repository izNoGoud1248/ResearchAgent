from services.orchestrator.reportSkills import ReportSkills


class TestReportSkills:
    skills = ReportSkills()

    def testLoadsEverySkillFolder(self):
        assert set(self.skills.skills) == {"researchBrief", "comparisonReport", "literatureReview"}
        for skill in self.skills.skills.values():
            assert skill.title and skill.description and skill.rules and skill.template
            assert len(skill.checklist) >= 3
            assert "## Checklist" not in skill.rules

    def testMenuListsEachSkillOnce(self):
        menu = self.skills.menu().splitlines()
        assert len(menu) == 3
        assert all(line.startswith("- ") and ": " in line for line in menu)

    def testUnknownChoiceFallsBackToDefault(self):
        assert self.skills.get("madeUpStyle").name == "researchBrief"
        assert self.skills.get(None).name == "researchBrief"
        assert self.skills.get("comparisonReport").name == "comparisonReport"
