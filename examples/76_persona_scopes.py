"""Apply explicit tool and Skill scopes."""

from super_harness import Persona, tool


@tool(namespace="repo")
def inspect(path: str) -> str:
    """Inspect one repository path."""
    return path


persona = Persona(
    "Reviewer", "code reviewer", "Review safely", tool_scopes=("repo.*",), skill_scopes=("code-*",)
)
print([item.qualified_name for item in persona.select_tools((inspect,))], persona.skill_scopes)

