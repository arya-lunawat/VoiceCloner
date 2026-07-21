import importlib
import os
import sys


def test_backend_module_imports():
    # Ensure the backend directory is on sys.path so we can import modules
    backend_dir = os.path.join(os.path.dirname(__file__), "..", "backend")
    if backend_dir not in sys.path:
        sys.path.insert(0, backend_dir)

    sys.modules.pop("main", None)
    sys.modules.pop("database", None)
    sys.modules.pop("preprocessing", None)
    sys.modules.pop("tts_engine", None)
    sys.modules.pop("watermark", None)

    main = importlib.import_module("main")

    assert main.app is not None
