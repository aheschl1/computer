

import os
from pathlib import Path
import logging
from typing import Optional

logger = logging.getLogger(__name__) 

class Skill:
    
    def __init__(self, name: str, description: str, metadata: dict, path: Path):
        self.name = name
        self.description = description
        self.metadata = metadata
        self.path = path
    
    @staticmethod
    def load_skill(path: Path) -> Optional["Skill"]:
        assert path.is_dir(), f"Expected a directory for skill, got {path}"
        if not os.path.exists(path / "SKILL.md"):
            return None
        
        with open(path / "SKILL.md", "r") as f:
            # parse header
            # expected format:
            # ---
            # name: Skill Name
            # description: A brief description of the skill
            # any_other_metadata: value
            # ---
            # body
            lines = f.read().splitlines()
            if lines[0].strip() != "---":
                return None
            metadata = {}
            i = 1
            while i < len(lines) and lines[i].strip() != "---":
                line = lines[i].strip()
                if ":" in line:
                    key, value = line.split(":", 1)
                    metadata[key.strip()] = value.strip()
                else:
                    # invalid metadata line
                    return None
                i += 1
            if i >= len(lines):
                return None
            name = metadata.pop("name", None)
            description = metadata.pop("description", None)
            if not name or not description:
                return None
        return Skill(name, description, metadata, path)
                

def load_skills() -> list[Skill]:
    skills_root = Path(os.environ.get("SKILLS_PATH", "skills"))
    skills = []
    if not skills_root.exists():
        logger.info(f"Skills directory {skills_root} does not exist.")
        return skills
    for item in skills_root.iterdir():
        if item.is_dir():
            skill = Skill.load_skill(item)
            if skill:
                skills.append(skill)
            else:
                logger.warning(f"Failed to load skill from {item}")
    return skills

def load_skill_by_name(name: str) -> Optional[Skill]:
    skills = load_skills()
    for skill in skills:
        if skill.name == name:
            return skill
    return None
    