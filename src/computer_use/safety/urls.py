"""Conservative URL normalization for the first local target integration."""

from urllib.parse import urlsplit


def split_url(url: str) -> tuple[str, str]:
    if not isinstance(url, str) or any(c.isspace() or ord(c) < 32 for c in url) or "\\" in url:
        raise ValueError("Invalid URL")
    parts = urlsplit(url)
    if (
        parts.scheme not in {"http", "https"}
        or not parts.hostname
        or parts.username
        or parts.password
        or parts.query
        or parts.fragment
        or "%" in parts.path
        or any(p in {".", ".."} for p in parts.path.split("/"))
        or "//" in parts.path
    ):
        raise ValueError("URL outside supported canonical form")
    port = parts.port or (443 if parts.scheme == "https" else 80)
    host = parts.hostname.lower()
    if ":" in host:
        host = f"[{host}]"
    suffix = "" if port == (443 if parts.scheme == "https" else 80) else f":{port}"
    return f"{parts.scheme}://{host}{suffix}", parts.path or "/"
