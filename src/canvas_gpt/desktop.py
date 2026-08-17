from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

from .ui_bridge import DesktopAPI


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Launch the Canvas GPT desktop UI.")
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="Workspace directory.")
    parser.add_argument("--dev-url", help="Load a running Vite development server.")
    parser.add_argument("--debug", action="store_true", help="Enable WebView debugging.")
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    default_fake_provider: bool = False,
) -> int:
    args = build_parser().parse_args(argv)
    try:
        import webview
    except ImportError as exc:
        raise SystemExit(
            'pywebview is not installed. Run `python -m pip install -e ".[desktop]"`.'
        ) from exc

    use_local_server = args.dev_url is None
    if args.dev_url:
        entrypoint = args.dev_url
    else:
        index_path = Path(__file__).resolve().parent / "ui_dist" / "index.html"
        if not index_path.is_file():
            raise SystemExit(
                "Desktop UI has not been built. Run `npm --prefix ui install` and "
                "`npm --prefix ui run build`."
            )
        entrypoint = str(index_path)

    api = DesktopAPI(
        args.root,
        allow_fake_provider=default_fake_provider or args.dev_url is not None,
    )
    window = webview.create_window(
        "Canvas GPT",
        url=entrypoint,
        js_api=api,
        width=1360,
        height=840,
        min_size=(900, 600),
        frameless=True,
        easy_drag=False,
        text_select=True,
        shadow=True,
        background_color="#f4f5f7",
    )
    api._attach_window(window)
    webview.start(debug=args.debug, http_server=use_local_server)
    return 0


def entrypoint(*, default_fake_provider: bool = False) -> None:
    raise SystemExit(main(default_fake_provider=default_fake_provider))


if __name__ == "__main__":
    entrypoint()
