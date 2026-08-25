"""Minimal synchronous DeepSeek agent."""

from super_harness import Agent, DeepSeekProvider


def main() -> None:
    provider = DeepSeekProvider()
    agent = Agent(provider, instructions="Answer clearly and briefly.")
    response = agent.run("Explain what an agent runtime does in one sentence.")
    print(response.text)


if __name__ == "__main__":
    main()
