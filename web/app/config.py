"""Settings, read once from the environment at import of the app factory.

Everything the portal needs is an environment variable, because the portal runs as a
Compose service and Compose has exactly one ergonomic way to configure a container.
There are no config files and no defaults for secrets: a missing PORTAL_SECRET_KEY or
PORTAL_DB_PASSWORD raises at startup, before the socket is bound, so a misconfigured
deploy is a container that never becomes healthy rather than a portal that quietly
signs cookies with "changeme".
"""

from __future__ import annotations

import ipaddress
import os
from dataclasses import dataclass, field
from pathlib import Path


class ConfigError(RuntimeError):
    """Raised at startup for a missing or nonsensical environment."""


def _req(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ConfigError(f"{name} is required and empty. See web/README.md.")
    return value


def _opt(name: str, default: str) -> str:
    value = os.environ.get(name)
    return default if value is None or value.strip() == "" else value.strip()


def _int(name: str, default: int) -> int:
    raw = _opt(name, str(default))
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer, got {raw!r}") from exc


def _bool(name: str, default: bool) -> bool:
    raw = _opt(name, "1" if default else "0").lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    raise ConfigError(f"{name} must be a boolean (0/1), got {raw!r}")


def _networks(raw: str) -> tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]:
    nets = []
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            nets.append(ipaddress.ip_network(chunk, strict=False))
        except ValueError as exc:
            raise ConfigError(f"PORTAL_TRUSTED_PROXIES: {chunk!r} is not a CIDR") from exc
    return tuple(nets)


@dataclass(frozen=True)
class Settings:
    # --- identity -------------------------------------------------------------
    server_name: str
    realmlist: str
    """The literal address a friend types after `set realmlist `. This is display
    copy, not a connection setting: the portal never talks to the game servers."""

    # --- secrets --------------------------------------------------------------
    secret_key: str

    # --- database -------------------------------------------------------------
    db_host: str
    db_port: int
    db_user: str
    db_password: str
    db_auth: str
    db_characters: str
    db_connect_timeout: int
    db_read_timeout: int

    # --- downloads ------------------------------------------------------------
    download_root: Path
    manifest_path: Path
    download_mode: str  # "xaccel" | "direct"
    xaccel_prefix: str

    # --- sessions / hardening -------------------------------------------------
    tls: bool
    session_max_age: int
    trusted_proxies: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]
    login_window: int
    login_max_per_ip: int
    login_max_per_user: int

    # --- derived --------------------------------------------------------------
    cookie_secure: bool = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "cookie_secure", self.tls)


def load_settings() -> Settings:
    secret = _req("PORTAL_SECRET_KEY")
    # 32 characters is not cryptography, it is a tripwire. The failure this catches is
    # somebody pasting a placeholder like "secret" into deploy/.env and shipping a
    # cookie signature anybody can forge.
    if len(secret) < 32:
        raise ConfigError(
            "PORTAL_SECRET_KEY must be at least 32 characters. Generate one with:\n"
            "    LC_ALL=C tr -dc 'A-Za-z0-9' < /dev/urandom | head -c 48; echo"
        )

    mode = _opt("PORTAL_DOWNLOAD_MODE", "xaccel").lower()
    if mode not in {"xaccel", "direct", "redirect"}:
        raise ConfigError(
            f"PORTAL_DOWNLOAD_MODE must be xaccel, direct or redirect, got {mode!r}")

    root = Path(_opt("PORTAL_DOWNLOAD_ROOT", "/srv/wow/dist")).resolve()
    # downloads.json, the name scripts/package-extras.sh writes. The contract says the
    # manifest travels in the same directory as the files it describes, so the default
    # is derived from the root rather than being a second independent path to get wrong.
    manifest = Path(_opt("PORTAL_MANIFEST", str(root / "downloads.json")))

    prefix = _opt("PORTAL_XACCEL_PREFIX", "/_dist/")
    if not prefix.startswith("/") or not prefix.endswith("/"):
        raise ConfigError("PORTAL_XACCEL_PREFIX must start and end with '/', e.g. /_dist/")

    return Settings(
        server_name=_opt("PORTAL_SERVER_NAME", "wowserver"),
        realmlist=_req("PORTAL_REALMLIST"),
        secret_key=secret,
        db_host=_opt("PORTAL_DB_HOST", "mysql"),
        db_port=_int("PORTAL_DB_PORT", 3306),
        db_user=_opt("PORTAL_DB_USER", "acore_web"),
        db_password=_req("PORTAL_DB_PASSWORD"),
        db_auth=_opt("PORTAL_DB_AUTH", "acore_auth"),
        db_characters=_opt("PORTAL_DB_CHARACTERS", "acore_characters"),
        db_connect_timeout=_int("PORTAL_DB_CONNECT_TIMEOUT", 5),
        db_read_timeout=_int("PORTAL_DB_READ_TIMEOUT", 10),
        download_root=root,
        manifest_path=manifest,
        download_mode=mode,
        xaccel_prefix=prefix,
        tls=_bool("PORTAL_TLS", False),
        session_max_age=_int("PORTAL_SESSION_MAX_AGE", 14 * 24 * 3600),
        # Defaults cover the RFC1918 space plus loopback. The portal is only ever
        # reached through the front proxy on the Compose network, so the direct peer
        # is always a private address; a client on the public internet cannot forge a
        # private source address over TCP, so trusting X-Forwarded-For *only* from
        # these ranges cannot be abused from outside. Without this the rate limiter
        # would see one IP (nginx) for the whole world and lock everybody out at once.
        trusted_proxies=_networks(
            _opt(
                "PORTAL_TRUSTED_PROXIES",
                "127.0.0.0/8,::1/128,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,fc00::/7",
            )
        ),
        login_window=_int("PORTAL_LOGIN_WINDOW", 900),
        login_max_per_ip=_int("PORTAL_LOGIN_MAX_PER_IP", 20),
        login_max_per_user=_int("PORTAL_LOGIN_MAX_PER_USER", 8),
    )
