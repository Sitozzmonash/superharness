from super_harness import SkillCatalog

catalog = SkillCatalog.discover(cwd=".")
skill = catalog.activate("code-review")
print(skill.instructions)
# Supporting files stay unloaded until explicitly requested:
# print(skill.read_resource("references/checklist.md").decode())
