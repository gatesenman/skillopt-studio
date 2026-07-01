"""Authoritative SkillOpt config-key spec + override validation.

SkillOpt's ``--cfg-options`` accepts ``section.key=value`` strings, but
``skillopt.config.apply_overrides`` **silently** creates unknown keys instead
of rejecting them.  That means a typo (e.g. ``optimizer.lr`` instead of
``optimizer.learning_rate``) is accepted by the CLI yet never read by the
trainer — the knob looks wired up but does nothing.

This module exposes the canonical set of valid dotted override keys (taken from
SkillOpt's own ``_FLATTEN_MAP`` plus the loaded config's ``env`` section) so the
Studio can warn the user *before* launching a run that some overrides would be
silently ignored.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

# Keys the Studio sets itself (resolved by the wrapper, not real config keys).
_INTERNAL_PREFIXES = ("_",)


def known_keys(skillopt_root: Optional[Path], config_path: str = "") -> Optional[set[str]]:
    """Return the set of valid dotted override keys, or ``None`` if SkillOpt is
    not importable (in which case validation should be skipped, not failed)."""
    try:
        from skillopt.config import _FLATTEN_MAP  # type: ignore
    except Exception:
        return None

    keys: set[str] = set(_FLATTEN_MAP.keys())
    # Also accept the bare section names (some flat env keys live under env.*).
    keys |= {k.split(".", 1)[0] for k in keys}

    # Merge in env-section keys from the actual config (env.* is pass-through).
    cfg_file = _resolve_config(skillopt_root, config_path)
    if cfg_file is not None:
        try:
            from skillopt.config import load_config  # type: ignore
            cfg = load_config(str(cfg_file))
            env = cfg.get("env", {}) if isinstance(cfg, dict) else {}
            if isinstance(env, dict):
                keys |= {f"env.{k}" for k in env}
        except Exception:
            pass
    return keys


def unknown_overrides(overrides: dict, known: Optional[set[str]]) -> list[str]:
    """List override keys that SkillOpt would silently ignore."""
    if not known:
        return []
    bad: list[str] = []
    for key in overrides:
        if any(key.startswith(p) for p in _INTERNAL_PREFIXES):
            continue
        if key in known:
            continue
        # accept ``env.<anything>`` since the env section is pass-through
        if key.startswith("env."):
            continue
        bad.append(key)
    return bad


def _resolve_config(skillopt_root: Optional[Path], config_path: str) -> Optional[Path]:
    if not config_path:
        return None
    p = Path(config_path)
    if not p.is_absolute() and skillopt_root:
        cand = skillopt_root / config_path
        if cand.exists():
            return cand
    return p if p.exists() else None
