# Canvas GPT

Canvas GPT is a small, local-first conversation graph for exploring ideas without silently changing
the context behind earlier answers. It provides a Windows/macOS desktop canvas and a Python CLI over
the same graph and provider logic.

```text
[Research] ──branch──> [Alternative]
      │                      │
      └──────────┬───────────┘
                 v
          [Merge synthesis]
```

The project is an alpha prototype. Graph data stays in the current workspace as readable JSON, and
API credentials are read only from environment variables.

## Core model

Each node stores only the messages created locally in that discussion. Structural edges store a
snapshot boundary describing exactly which source messages were inherited. Context is reconstructed
when needed, so shared history is stored once and shared ancestors are deduplicated.

Nodes have three user-facing states:

| State | Meaning | Allowed actions |
| --- | --- | --- |
| **Draft** | No local conversation yet | Rename, delete, add/remove up to 8 context sources, send the first message |
| **Active** | Has local messages and no children | Continue chatting or create a child |
| **Frozen** | Has one or more structural children | Create more children, rename, inspect history; chat is disabled |

Creating the first child freezes its source discussion. This prevents later messages from silently
changing the context seen by existing children. A Frozen discussion can still seed more children,
up to 50 total.

Important invariants:

- A Draft cannot have children. Send its first message before branching from it.
- Once a discussion has local messages, its captured context sources cannot be added, removed, or
  replaced.
- To add context to an existing discussion, create a new Merge Draft whose sources are the existing
  discussion and the new context. The originals remain unchanged.
- Structural operations reject cycles before saving, and context reconstruction also detects
  malformed cyclic data defensively.
- A Draft accepts at most 8 parents; a discussion can have at most 50 structural children.
- Typed relationship edges such as `supports` and `reference` do not affect model context or freeze
  either endpoint.

## Desktop canvas

The canvas is available without an API key, but chat requires the configured provider. Because a
Draft cannot have children, a new graph needs at least one successful conversation before it can
branch. The DEV build includes a Fake context provider for testing this workflow without paid calls.

Desktop gestures:

- Drag from a discussion to empty canvas to create a Branch Draft.
- Drag from a discussion onto a Draft to add it as another context source.
- Drag from one existing discussion onto another existing discussion to create a new Merge Draft.
  Neither original is modified.
- Draft source edges are editable until the first message. Captured edges are immutable afterward.
- Reaching the 8-parent or 50-child limit produces an explicit notification instead of silently
  disabling the gesture.

The right panel shows the reconstructed conversation context. Frozen discussions explain why their
composer is unavailable and direct the user to continue in a child branch.

### Run from source

Canvas GPT requires Python 3.10 or newer and Node.js for frontend development.

```powershell
git clone <your-repo-url>
cd canvas-gpt
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev,desktop]"
npm --prefix ui install
npm --prefix ui run build
canvas-gpt-desktop --root .
```

On macOS or Linux, activate the environment with `source .venv/bin/activate`.

For frontend development, run Vite and point the desktop shell at it:

```powershell
npm --prefix ui run dev
canvas-gpt-desktop --root . --dev-url http://localhost:5173 --debug
```

Loading a Vite `--dev-url` enables the development-only **Fake context** provider. It echoes the
actual system prompt and ordered messages that would be sent to a real provider. Fake replies are
saved like normal assistant messages, so repeated Fake turns intentionally grow quickly.

### Windows builds

```powershell
python -m pip install -e ".[desktop,build]"
.\scripts\build_windows.ps1
```

Release outputs:

```text
dist\CanvasGPT\CanvasGPT.exe
dist\CanvasGPT-windows-x64.zip
```

Build the development executable with Fake context included:

```powershell
.\scripts\build_windows.ps1 -Flavor Dev
.\dist\CanvasGPT-Dev\CanvasGPT-Dev.exe
```

The DEV executable keeps a console open for diagnostics. The Release build is windowed and excludes
the Fake provider module.

## CLI quick start

Install the package and initialize graph data in the current folder:

```powershell
python -m pip install -e ".[dev]"
canvas-gpt init --provider openai
$env:OPENAI_API_KEY = "your-key"
```

For Anthropic, use `--provider anthropic` and set `ANTHROPIC_API_KEY`. The short `cc` command is an
alias for `canvas-gpt`.

```powershell
cc new "Design the context model"
cc chat n1 "What should a node store?"
cc branch n1 "Alternative: immutable history"
cc chat n2 "Explore the tradeoffs"
cc merge n1 n2 --title "Canonical design"
cc graph
cc show n3
```

After `cc branch n1 ...`, `n1` is Frozen and cannot accept more chat messages. Continue in `n2` or
create another branch from `n1`.

Available commands:

```text
canvas-gpt init [--provider openai|anthropic] [--model MODEL]
canvas-gpt new "TITLE"
canvas-gpt chat NODE_ID ["MESSAGE"]
canvas-gpt branch SOURCE_ID "TITLE"
canvas-gpt rename NODE_ID "TITLE"
canvas-gpt merge NODE_ID NODE_ID [NODE_ID ...] [--title TITLE]
canvas-gpt connect SOURCE_ID TARGET_ID --type supports|contradicts|extends|reference
canvas-gpt graph
canvas-gpt show NODE_ID
canvas-gpt config [--provider PROVIDER] [--model MODEL]
```

Omit the message from `chat` to open an interactive session; use `/exit` or `/quit` to leave it.
`merge` also accepts a synthesis instruction:

```powershell
cc merge n1 n4 n7 --instruction "Resolve contradictions and recommend one design."
```

CLI `branch` and `merge` use the same Draft, Frozen, parent-limit, child-limit, and cycle rules as
the desktop application. `connect` creates a descriptive relationship only and never changes model
context.

## Configuration and local data

Running `init` creates:

```text
.canvas-gpt/
├── config.json
├── graph.json
└── ui.json       # created by the desktop app when layout is saved
```

The directory is ignored by Git. `config.json` stores provider settings but never credentials.
`graph.json` currently uses schema version 3:

- Nodes contain `local_messages`, title metadata, kind, and timestamps.
- `branch` and `merge` edges contain source/target IDs plus the captured `context_path` and message
  boundary.
- Descendant context is reconstructed from those paths; message bodies are not copied into every
  child.
- Version 1 and 2 graphs migrate automatically.

Provider defaults:

| Provider | Environment variable | Default model |
| --- | --- | --- |
| OpenAI | `OPENAI_API_KEY` | `gpt-5.6-terra` |
| Anthropic | `ANTHROPIC_API_KEY` | `claude-sonnet-5` |

Change provider or model without resetting the graph:

```powershell
cc config --provider anthropic --model claude-sonnet-5
```

## Context behavior

### Branch

A Branch Draft captures the source's complete context at the moment the edge is created. Only new
messages are stored locally in the child. The source becomes Frozen while the edge exists. Deleting
an unsubmitted child or removing its editable edge can make the source Active again if it has no
other structural children.

### Merge

A Merge Draft has two to eight captured sources. Its first message is used as the synthesis goal.
Each unique lineage segment is sent once, shared ancestors are deduplicated, and the synthesis is
stored locally in the new merge node. Source nodes are not modified.

The CLI `merge` command performs this synthesis immediately. On the desktop, a Merge Draft can be
wired without an API and is committed when its first message is successfully submitted.

### Failure safety

Provider failures do not append messages or commit a Merge Draft. Graph files are written through a
temporary file and atomically replaced. API keys are never written into graph data.

## Tests

```powershell
python -m pytest
```

The test suite uses local fake providers and does not make paid API calls. Frontend types can be
checked without producing a build:

```powershell
cd ui
.\node_modules\.bin\tsc.cmd --noEmit -p tsconfig.app.json
```

## License

MIT
