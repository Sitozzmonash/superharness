"""Compose stable Agent identity instructions."""

from super_harness import Persona

persona = Persona("Ari", "release reviewer", "Find release blockers", constraints=("Cite evidence",))
print(persona.compose_instructions("Review the candidate."))

