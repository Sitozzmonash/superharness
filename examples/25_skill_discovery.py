from super_harness import SkillCatalog

catalog = SkillCatalog.discover(cwd=".")
for skill in catalog.list():
    print(skill.name, skill.description, skill.source)
