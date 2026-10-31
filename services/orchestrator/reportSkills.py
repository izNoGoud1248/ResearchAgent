import re
from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class ReportSkill:
    name: str
    title: str
    description: str
    rules: str
    checklist: tuple[str, ...]
    template: str


class ReportSkills:
    """Report styles kept as files: each folder in skills/ holds a SKILL.md (rules and checklist) and a template.md.

    The planner picks one from the descriptions, the writer follows its rules and template, and the critic scores
    against its checklist. Adding a style is adding a folder.
    """

    default = "researchBrief"
    folder = Path(__file__).parent / "skills"

    def __init__(self, folder: Path | None = None):
        self.skills = {skill.name: skill for skill in map(self.load, sorted((folder or self.folder).glob("*/SKILL.md")))}

    @staticmethod
    def load(path: Path) -> ReportSkill:
        _, frontMatter, body = path.read_text(encoding="utf-8").split("---", 2)
        meta = yaml.safe_load(frontMatter)
        rules, _, checklist = body.partition("## Checklist")
        return ReportSkill(
            name=meta["name"],
            title=meta["title"],
            description=meta["description"],
            rules=rules.strip(),
            checklist=tuple(re.findall(r"^- (.+)$", checklist, flags=re.MULTILINE)),
            template=(path.parent / "template.md").read_text(encoding="utf-8").strip(),
        )

    def menu(self) -> str:
        return "\n".join(f"- {skill.name}: {skill.description}" for skill in self.skills.values())

    def get(self, name: str | None) -> ReportSkill:
        return self.skills.get(name or "", self.skills[self.default])
