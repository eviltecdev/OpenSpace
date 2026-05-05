"""OpenSpace local_server — DEPRECATED, use ruflo.local_server instead."""
# Lazy imports
def __getattr__(name):
    if name == "create_app":
        from ruflo.local_server.main import create_app
        return create_app
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = ["create_app"]
