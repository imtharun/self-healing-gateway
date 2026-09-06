# built-in
import asyncio
import ipaddress
import os
import socket
from urllib.parse import urlsplit, urlunsplit


def _private_upstreams_allowed() -> bool:
    return os.getenv("GATEWAY_ALLOW_PRIVATE_UPSTREAMS", "false").lower() == "true"


def _is_disallowed_address(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    return any(
        (
            ip.is_private,
            ip.is_loopback,
            ip.is_link_local,
            ip.is_multicast,
            ip.is_reserved,
            ip.is_unspecified,
        )
    )


async def validate_upstream_url(value: str) -> str:
    """Normalize a URL and reject common SSRF targets before registration."""
    candidate = value.strip().rstrip("/")
    parsed = urlsplit(candidate)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Upstream URL must be an absolute HTTP or HTTPS URL")
    if parsed.username or parsed.password:
        raise ValueError("Upstream URL cannot contain credentials")
    if parsed.query or parsed.fragment:
        raise ValueError("Upstream URL cannot contain a query or fragment")
    if parsed.path not in {"", "/"}:
        raise ValueError("Upstream URL must not contain a path")

    try:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError as exc:
        raise ValueError("Upstream URL contains an invalid port") from exc

    if not _private_upstreams_allowed():
        try:
            addresses = await asyncio.to_thread(
                socket.getaddrinfo,
                parsed.hostname,
                port,
                type=socket.SOCK_STREAM,
            )
        except socket.gaierror as exc:
            raise ValueError("Upstream hostname could not be resolved") from exc

        resolved_addresses = {item[4][0] for item in addresses}
        if not resolved_addresses or any(
            _is_disallowed_address(address) for address in resolved_addresses
        ):
            raise ValueError("Private, local, and reserved upstream addresses are blocked")

    return urlunsplit(
        (parsed.scheme, parsed.netloc.lower(), parsed.path.rstrip("/"), "", "")
    )
