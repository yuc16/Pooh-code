from __future__ import annotations

from pathlib import Path

from .models import Skill
from .paths import SKILLS_DIR, ensure_runtime_dirs


class SkillsManager:
    def __init__(self) -> None:
        ensure_runtime_dirs()
        self.skills: list[Skill] = []

    def _parse_frontmatter(self, text: str) -> tuple[dict[str, str], str]:
        if not text.startswith("---"):
            return {}, text.strip()
        parts = text.split("---", 2)
        if len(parts) < 3:
            return {}, text.strip()
        meta: dict[str, str] = {}
        for line in parts[1].splitlines():
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            meta[key.strip()] = value.strip()
        return meta, parts[2].strip()

    def discover(self) -> list[Skill]:
        skills: list[Skill] = []
        for child in sorted(SKILLS_DIR.iterdir() if SKILLS_DIR.exists() else []):
            if not child.is_dir():
                continue
            skill_file = child / "SKILL.md"
            if not skill_file.exists():
                continue
            try:
                raw = skill_file.read_text(encoding="utf-8")
            except Exception:
                continue
            meta, body = self._parse_frontmatter(raw)
            name = meta.get("name") or child.name
            description = meta.get("description", "")
            skills.append(
                Skill(
                    name=name,
                    description=description,
                    body=body,
                    path=str(skill_file),
                )
            )
        self.skills = skills
        return skills

    def list_names(self) -> list[str]:
        if not self.skills:
            self.discover()
        return [skill.name for skill in self.skills]

    def render_for_prompt(self, query: str | None = None, limit: int = 6) -> str:
        if not self.skills:
            self.discover()
        if not self.skills:
            return ""
        ranked = self.skills
        if query:
            terms = {part.lower() for part in query.split() if part.strip()}
            if terms:
                ranked = sorted(
                    self.skills,
                    key=lambda skill: sum(
                        term in f"{skill.name} {skill.description} {skill.body}".lower()
                        for term in terms
                    ),
                    reverse=True,
                )
        lines = ["## Skills"]
        for skill in ranked[:limit]:
            lines.append(f"### {skill.name}")
            if skill.description:
                lines.append(skill.description)
            if skill.body:
                lines.append(skill.body)
            lines.append("")
        return "\n".join(lines).strip()
