# Q&A Agent

Interactive assistant powered by Claude. Loads user preferences from the session service to personalize responses.

## Setup

```bash
pip install anthropic requests
export ANTHROPIC_API_KEY=...
export INTERNAL_TOKEN=...
```

## Usage

```bash
python agent.py --session <session-id>
```

The agent will prompt for questions interactively. Press Ctrl+C to exit.

## Configuration

| Variable | Description |
|----------|-------------|
| `ANTHROPIC_API_KEY` | Anthropic API key |
| `INTERNAL_TOKEN` | Token for session service authentication |

The session service is expected at `http://session-service:8080`. Override by setting the hostname in your environment or `docker-compose.yml`.
