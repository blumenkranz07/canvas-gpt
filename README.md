# Canvas GPT

Branch, connect, and merge AI conversations from your terminal.

Canvas GPT is a tiny local-first context graph for nonlinear conversations. A node is an
independent discussion. You can fork it, connect it to any other node, or synthesize any two or
more nodes into a new canonical context.

```text
[n1: Research question] ----branch----> [n2: Alternative]
          \                                  /
           +------------merge---------------+
                            |
                            v
                    [n3: Unified result]
```

## v0.1 features

- Local JSON graph stored inside the current project
- OpenAI Responses API and Anthropic Messages API
- One-shot or interactive chat inside a node
- Branch a node while preserving its conversation context
- Merge any 2+ nodes, regardless of their position in the graph
- Typed arbitrary connections: `supports`, `contradicts`, `extends`, and `reference`
- API keys read only from environment variables

## Install for development

Canvas GPT requires Python 3.10 or newer.

```bash
git clone <your-repo-url>
cd canvas-gpt
python -m venv .venv
```

Activate the environment and install the package:

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

On macOS or Linux, activate it with `source .venv/bin/activate` instead.

## Quick start

Initialize the current folder with OpenAI:

```powershell
canvas-gpt init --provider openai
$env:OPENAI_API_KEY = "your-key"
```

Or initialize with Anthropic:

```powershell
canvas-gpt init --provider anthropic
$env:ANTHROPIC_API_KEY = "your-key"
```

The short `cc` command is equivalent to `canvas-gpt`:

```powershell
cc new "Design the context model"
cc chat n1 "What should a node store?"
cc branch n1 "Alternative: immutable nodes"
cc rename n2 "Immutable-node alternative"
cc chat n2 "Explore the tradeoffs"
cc merge n1 n2 --title "Canonical node design"
cc graph
```

Enter an interactive node session by omitting the message:

```powershell
cc chat n1
```

Type `/exit` or `/quit` to leave it.

## Desktop canvas

The desktop prototype keeps the canvas available without an API key; chat is disabled until the
configured provider key is present in the environment.

```powershell
python -m pip install -e ".[dev,desktop]"
npm --prefix ui install
npm --prefix ui run build
canvas-gpt-desktop --root .
```

For frontend development, run Vite and point the desktop shell at it:

```powershell
npm --prefix ui run dev
canvas-gpt-desktop --root . --dev-url http://localhost:5173 --debug
```

## Commands

```text
canvas-gpt init [--provider openai|anthropic] [--model MODEL]
canvas-gpt new "TITLE"
canvas-gpt chat NODE_ID ["MESSAGE"]
canvas-gpt branch SOURCE_ID "TITLE"
canvas-gpt rename NODE_ID "TITLE"
canvas-gpt merge NODE_ID NODE_ID [NODE_ID ...] [--title TITLE]
canvas-gpt connect SOURCE_ID TARGET_ID --type supports
canvas-gpt graph
canvas-gpt show NODE_ID
canvas-gpt config [--provider PROVIDER] [--model MODEL]
```

`merge` also accepts an instruction:

```powershell
cc merge n1 n4 n7 --instruction "Resolve contradictions and recommend one design."
```

## Configuration and local data

Running `init` creates:

```text
.canvas-gpt/
├── config.json
└── graph.json
```

This directory is ignored by Git. `config.json` contains only the provider, model ID, and output
token limit. Credentials are never written into it.
`graph.json` uses schema version 3: each node stores only `local_messages` and records whether its
title is manual, a UI placeholder, or automatic, while a branch edge records the exact inherited
message boundary. Version 1 and 2 graphs are migrated automatically.

Defaults:

| Provider | Environment variable | Default model |
| --- | --- | --- |
| OpenAI | `OPENAI_API_KEY` | `gpt-5.6-terra` |
| Anthropic | `ANTHROPIC_API_KEY` | `claude-sonnet-5` |

Change provider or model without resetting the graph:

```powershell
cc config --provider anthropic --model claude-sonnet-5
```

## v0.1 semantics

- **Branch:** stores only messages added after the fork. Inherited context is reconstructed by
  following the node's `branch` lineage and its saved fork boundary, so later parent messages do not
  leak into the branch and shared history is not duplicated on disk.
- **Connect:** adds a typed graph edge without changing either node's conversation.
- **Merge:** sends each unique lineage segment once, describes the exact selected source paths,
  creates a synthesis node, and adds a `merge` edge from every source to that node. Shared ancestors
  are not repeated in the model input.
- **Continue after merge:** the synthesis becomes the seed context for subsequent chat in the new
  node.

This deliberately avoids a server, database, authentication system, embeddings, retrieval, and a
visual canvas. Those can be added after the graph interaction model proves useful.

## Test

```powershell
python -m pytest
```

The test suite uses fake providers and never makes paid API calls.

## License

MIT
