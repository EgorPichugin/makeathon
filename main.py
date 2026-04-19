import os
import tempfile

import uvicorn

# If a service account JSON is provided via env (e.g. Railway), materialize it to disk and
# point google SDKs at it via GOOGLE_APPLICATION_CREDENTIALS. This is the standard ADC
# pattern for container deploys where `gcloud auth application-default login` is not possible.
_sa_json = os.getenv("GOOGLE_APPLICATION_CREDENTIALS_JSON")
if _sa_json and not os.getenv("GOOGLE_APPLICATION_CREDENTIALS"):
    _sa_path = os.path.join(tempfile.gettempdir(), "gcp-sa.json")
    with open(_sa_path, "w", encoding="utf-8") as _f:
        _f.write(_sa_json)
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = _sa_path

from core.app import create_app


app = create_app()

if __name__ == "__main__":
   uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
