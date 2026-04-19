import json
import os
import sys
import tempfile

import uvicorn


def _bootstrap_adc_from_env() -> None:
    """If a service account JSON is provided via env (e.g. Railway), materialize it to disk and
    point google SDKs at it via GOOGLE_APPLICATION_CREDENTIALS.

    Handles both forms Railway may deliver:
      - raw multiline JSON (what you get if the value preserved newlines)
      - a JSON-escaped string (what you get if the UI turned newlines into `\\n`)
    """
    sa_json = os.getenv("GOOGLE_APPLICATION_CREDENTIALS_JSON")
    print(
        f"[boot] GOOGLE_APPLICATION_CREDENTIALS_JSON present={bool(sa_json)} "
        f"len={len(sa_json) if sa_json else 0}",
        file=sys.stderr, flush=True,
    )
    print(
        f"[boot] USE_VERTEX_AI={os.getenv('USE_VERTEX_AI')} "
        f"GOOGLE_CLOUD_PROJECT={os.getenv('GOOGLE_CLOUD_PROJECT')} "
        f"GOOGLE_CLOUD_LOCATION={os.getenv('GOOGLE_CLOUD_LOCATION')}",
        file=sys.stderr, flush=True,
    )

    if not sa_json:
        return
    if os.getenv("GOOGLE_APPLICATION_CREDENTIALS"):
        print("[boot] GOOGLE_APPLICATION_CREDENTIALS already set; skipping materialization",
              file=sys.stderr, flush=True)
        return

    sa_path = os.path.join(tempfile.gettempdir(), "gcp-sa.json")
    try:
        parsed = json.loads(sa_json)
        with open(sa_path, "w", encoding="utf-8") as f:
            json.dump(parsed, f)
        print(f"[boot] Wrote parsed SA JSON to {sa_path} "
              f"(client_email={parsed.get('client_email', '?')})",
              file=sys.stderr, flush=True)
    except json.JSONDecodeError as e:
        print(f"[boot] json.loads failed ({e}); writing raw content", file=sys.stderr, flush=True)
        with open(sa_path, "w", encoding="utf-8") as f:
            f.write(sa_json)
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = sa_path
    print(f"[boot] GOOGLE_APPLICATION_CREDENTIALS={sa_path}", file=sys.stderr, flush=True)


_bootstrap_adc_from_env()

from core.app import create_app


app = create_app()

if __name__ == "__main__":
   uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
