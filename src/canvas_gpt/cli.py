from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from . import __version__
from .errors import CanvasGPTError
from .models import DEFAULT_MODELS, Config, Graph, Message, Node
from .providers import Provider, build_provider
from .service import CONNECT_EDGE_TYPES, GraphService
from .storage import Workspace


ProviderFactory = Callable[[Config], Provider]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="canvas-gpt",
        description="Branch, connect, and merge AI conversations from your terminal.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)

    init_parser = commands.add_parser("init", help="Initialize Canvas GPT in this folder.")
    init_parser.add_argument("--provider", choices=tuple(DEFAULT_MODELS), default=None)
    init_parser.add_argument("--model", help="Provider model ID.")
    init_parser.add_argument("--max-output-tokens", type=int, default=2048)
    init_parser.add_argument("--force", action="store_true", help="Reset existing local graph data.")

    new_parser = commands.add_parser("new", help="Create an empty conversation node.")
    new_parser.add_argument("title")

    chat_parser = commands.add_parser("chat", help="Chat inside a node.")
    chat_parser.add_argument("node_id")
    chat_parser.add_argument("message", nargs="?", help="Omit to enter interactive chat mode.")

    branch_parser = commands.add_parser("branch", help="Fork a node with its conversation context.")
    branch_parser.add_argument("source_id")
    branch_parser.add_argument("title")

    merge_parser = commands.add_parser("merge", help="Synthesize any two or more nodes.")
    merge_parser.add_argument("source_ids", nargs="+")
    merge_parser.add_argument("--title")
    merge_parser.add_argument("--instruction", help="Tell the model how to synthesize the sources.")

    connect_parser = commands.add_parser("connect", help="Create a typed edge between any nodes.")
    connect_parser.add_argument("source_id")
    connect_parser.add_argument("target_id")
    connect_parser.add_argument(
        "--type", choices=CONNECT_EDGE_TYPES, default="reference", dest="edge_type"
    )

    commands.add_parser("graph", help="Show all nodes and connections.")

    show_parser = commands.add_parser("show", help="Show one node and its conversation.")
    show_parser.add_argument("node_id")

    config_parser = commands.add_parser("config", help="Show or update provider configuration.")
    config_parser.add_argument("--provider", choices=tuple(DEFAULT_MODELS))
    config_parser.add_argument("--model")
    config_parser.add_argument("--max-output-tokens", type=int)
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    root: Path | str | None = None,
    provider_factory: ProviderFactory = build_provider,
) -> int:
    args = build_parser().parse_args(argv)
    workspace = Workspace(root or Path.cwd())
    try:
        if args.command == "init":
            return _run_init(workspace, args)
        if args.command == "config":
            return _run_config(workspace, args)

        workspace.require_initialized()
        service = GraphService(workspace)
        if args.command == "new":
            node = service.new_node(args.title)
            print(f"Created {node.id}: {node.title}")
        elif args.command == "branch":
            node = service.branch(args.source_id, args.title)
            print(f"Created {node.id} from {args.source_id}: {node.title}")
        elif args.command == "connect":
            edge = service.connect(args.source_id, args.target_id, args.edge_type)
            print(f"Connected {edge.source} --{edge.type}--> {edge.target}")
        elif args.command == "graph":
            _print_graph(workspace.load_graph())
        elif args.command == "show":
            node = service.get_node(args.node_id)
            _print_node(node, service.context_messages(args.node_id))
        elif args.command in {"chat", "merge"}:
            config = workspace.load_config()
            service.provider = provider_factory(config)
            if args.command == "chat":
                _run_chat(service, args.node_id, args.message)
            else:
                node, response = service.merge(
                    args.source_ids, title=args.title, instruction=args.instruction
                )
                print(response)
                print(f"\nCreated merge node {node.id}: {node.title}")
        return 0
    except CanvasGPTError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


def _run_init(workspace: Workspace, args: argparse.Namespace) -> int:
    provider = args.provider or _choose_provider()
    model = args.model or DEFAULT_MODELS[provider]
    if args.max_output_tokens < 1:
        raise CanvasGPTError("--max-output-tokens must be greater than zero.")
    config = Config(provider=provider, model=model, max_output_tokens=args.max_output_tokens)
    workspace.initialize(config, force=args.force)
    env_name = "OPENAI_API_KEY" if provider == "openai" else "ANTHROPIC_API_KEY"
    print(f"Initialized Canvas GPT in {workspace.data_dir}")
    print(f"Provider: {provider} ({model})")
    print(f"Set {env_name} before running chat or merge.")
    return 0


def _choose_provider() -> str:
    if not sys.stdin.isatty():
        return "openai"
    value = input("Provider [openai/anthropic] (openai): ").strip().lower() or "openai"
    if value not in DEFAULT_MODELS:
        raise CanvasGPTError("Provider must be 'openai' or 'anthropic'.")
    return value


def _run_config(workspace: Workspace, args: argparse.Namespace) -> int:
    config = workspace.load_config()
    changed = False
    if args.provider:
        if args.provider != config.provider and not args.model:
            config.model = DEFAULT_MODELS[args.provider]
        config.provider = args.provider
        changed = True
    if args.model:
        config.model = args.model
        changed = True
    if args.max_output_tokens is not None:
        if args.max_output_tokens < 1:
            raise CanvasGPTError("--max-output-tokens must be greater than zero.")
        config.max_output_tokens = args.max_output_tokens
        changed = True
    if changed:
        workspace.save_config(config)
        print("Configuration updated.")
    print(f"Provider: {config.provider}")
    print(f"Model: {config.model}")
    print(f"Max output tokens: {config.max_output_tokens}")
    return 0


def _run_chat(service: GraphService, node_id: str, message: str | None) -> None:
    if message is not None:
        print(service.chat(node_id, message))
        return
    node = service.get_node(node_id)
    print(f"Chatting in {node.id}: {node.title}. Type /exit to stop.")
    while True:
        try:
            user_text = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if user_text.lower() in {"/exit", "/quit"}:
            return
        if not user_text:
            continue
        print(f"ai> {service.chat(node_id, user_text)}")


def _print_graph(graph: Graph) -> None:
    if not graph.nodes:
        print("Graph is empty. Create a node with `canvas-gpt new \"My topic\"`.")
        return
    print("Nodes")
    for node in sorted(graph.nodes.values(), key=_node_sort_key):
        print(
            f"  [{node.id}] {node.title} "
            f"({node.kind}, {len(node.local_messages)} local messages)"
        )
    print("Edges")
    if not graph.edges:
        print("  (none)")
    else:
        for edge in graph.edges:
            print(f"  {edge.source} --{edge.type}--> {edge.target}")


def _print_node(node: Node, context_messages: list[Message]) -> None:
    print(f"[{node.id}] {node.title}")
    print(f"Kind: {node.kind}")
    print(f"Updated: {node.updated_at}")
    inherited_count = len(context_messages) - len(node.local_messages)
    print(f"Inherited messages: {inherited_count}")
    print(f"Local messages: {len(node.local_messages)}")
    if not context_messages:
        print("\n(no messages)")
        return
    for index, message in enumerate(context_messages):
        origin = "inherited" if index < inherited_count else "local"
        print(f"\n{message.role.upper()} ({origin})\n{message.content}")


def _node_sort_key(node: Node) -> tuple[int, str]:
    if node.id.startswith("n") and node.id[1:].isdigit():
        return int(node.id[1:]), node.id
    return sys.maxsize, node.id


def entrypoint() -> None:
    raise SystemExit(main())


if __name__ == "__main__":
    entrypoint()
