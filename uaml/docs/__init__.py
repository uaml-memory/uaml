"""UAML bundled documentation for AI agents."""

import importlib.resources as _res


def get_guide() -> str:
    """Return the full AI Agent Integration Guide as a string."""
    return _res.files(__package__).joinpath("AGENT_GUIDE.md").read_text(encoding="utf-8")


def get_api_reference() -> str:
    """Return the API quick reference as a string."""
    return _res.files(__package__).joinpath("API_REFERENCE.md").read_text(encoding="utf-8")


def get_feature_matrix() -> str:
    """Return the license tier feature matrix as a string."""
    return _res.files(__package__).joinpath("FEATURE_MATRIX.md").read_text(encoding="utf-8")


def list_docs() -> dict[str, str]:
    """Return a mapping of bundled doc names → first-line descriptions."""
    docs = {}
    for name in ("AGENT_GUIDE.md", "API_REFERENCE.md", "FEATURE_MATRIX.md"):
        try:
            text = _res.files(__package__).joinpath(name).read_text(encoding="utf-8")
            first_line = text.split("\n", 1)[0].lstrip("# ").strip()
            docs[name] = first_line
        except Exception:
            pass
    return docs
