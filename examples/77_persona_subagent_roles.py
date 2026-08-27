"""Select a named subagent persona template."""

from super_harness import Persona

tester = Persona("Tester", "test specialist", "Verify acceptance criteria")
lead = Persona("Lead", "delivery lead", "Ship safely", subagent_roles={"tester": tester})
print(lead.subagent("tester").metadata())

