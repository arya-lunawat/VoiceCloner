import importlib
import sys


def test_backend_module_imports():
    sys.modules.pop("backend.main", None)
    sys.modules.pop("backend.database", None)
    sys.modules.pop("backend.preprocessing", None)
    sys.modules.pop("backend.tts_engine", None)
    sys.modules.pop("backend.watermark", None)

    main = importlib.import_module("backend.main")

    assert main.app is not None
