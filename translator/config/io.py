"""Locating, reading, and writing the config file."""

from __future__ import annotations

import logging
import os
from pathlib import Path

import yaml

from .defaults import DEFAULT_CONFIG
from .legacy import looks_legacy
from .models import AppConfig
from .overlay import apply_overlay, build_overlay

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = "config.yml"
CONFIG_PATH_ENV = "TRANSLATOR_CONFIG"


def resolve_config_path(path: str | Path | None = None) -> Path:
    return Path(path or os.environ.get(CONFIG_PATH_ENV) or DEFAULT_CONFIG_PATH)


def load_config(path: str | Path | None = None) -> AppConfig:
    """Load config from ``path``, $TRANSLATOR_CONFIG, or ./config.yml.

    Without a config file the built-in defaults apply — no file is needed to
    get started. When a file exists it is a *sparse overlay* on those defaults
    (see ``overlay``): its entries merge onto the defaults by id, so newly
    added or updated default providers/engines reach the install automatically
    instead of the file going stale. Legacy flat configs are loaded standalone.

    Structural validation only: per-kind ``settings`` are checked by
    :func:`translator.engines.validate_config`, which ``ConfigStore`` runs.
    """
    resolved = resolve_config_path(path)
    if not resolved.exists():
        logger.info("no config file at %s — using built-in defaults", resolved)
        return AppConfig.model_validate(DEFAULT_CONFIG)
    with resolved.open("r", encoding="utf-8") as fp:
        data = yaml.safe_load(fp) or {}
    if looks_legacy(data):
        logger.info("loading legacy flat config at %s (defaults not merged)", resolved)
        return AppConfig.model_validate(data)
    return AppConfig.model_validate(apply_overlay(DEFAULT_CONFIG, data))


def save_config(config: AppConfig, path: str | Path) -> None:
    """Write the sparse overlay for ``config`` as YAML, atomically where the
    filesystem allows.

    Only what differs from the built-in defaults is written, so the file stays
    small and defaults keep flowing in on load. Falls back to an in-place write
    when rename fails — e.g. a Docker single-file bind mount, where the target
    cannot be replaced (EBUSY).
    """
    resolved = Path(path)
    text = yaml.safe_dump(build_overlay(config), sort_keys=False, allow_unicode=True)
    tmp = resolved.with_name(resolved.name + ".tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(resolved)
    except OSError:
        tmp.unlink(missing_ok=True)
        resolved.write_text(text, encoding="utf-8")
