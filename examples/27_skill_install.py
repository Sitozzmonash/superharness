from super_harness import SkillInstaller

installer = SkillInstaller(".super-harness/skills")
installed = installer.install("./my-skill")
print(installed.name, installed.path)
