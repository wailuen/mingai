"""
Version bump logic for agent templates and skills.

Used by the Platform Admin Template Studio (TODO-20) to detect breaking
changes between two template snapshots and compute the next semver label.

ChangeType rules:
  major  — required_credentials changed, auth_mode changed
  minor  — system_prompt changed, guardrails changed, llm_policy changed,
            attached_tools changed, attached_skills changed
  patch  — name, description, icon, avatar, tags, category,
            recommended_kb_categories, kb_policy changed

When multiple field categories change simultaneously the highest severity wins.
"""
from __future__ import annotations

import re
from typing import Literal

import structlog

logger = structlog.get_logger()

ChangeType = Literal["initial", "major", "minor", "patch"]

# Fields that trigger major bumps
_MAJOR_FIELDS: frozenset[str] = frozenset(
    {"required_credentials", "auth_mode"}
)

# Fields that trigger minor bumps (if no major change detected)
_MINOR_FIELDS: frozenset[str] = frozenset(
    {"system_prompt", "guardrails", "llm_policy", "attached_tools", "attached_skills"}
)

# Semver pattern for validation
_SEMVER_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


def detect_breaking_changes(old: dict, new: dict) -> ChangeType:
    """
    Compare two template snapshots and return the change severity.

    Args:
        old: Previous template snapshot dict.
        new: New template snapshot dict.

    Returns:
        'initial'  — no previous snapshot (old is empty / new template)
        'major'    — required_credentials or auth_mode changed
        'minor'    — system_prompt, guardrails, llm_policy, tools, skills changed
        'patch'    — only cosmetic/metadata fields changed
    """
    if not old:
        return "initial"

    changed_fields: set[str] = set()
    all_keys = set(old.keys()) | set(new.keys())
    for key in all_keys:
        if old.get(key) != new.get(key):
            changed_fields.add(key)

    if not changed_fields:
        # No fields changed — treat as patch (caller still needs to bump)
        return "patch"

    if changed_fields & _MAJOR_FIELDS:
        logger.info(
            "template_breaking_change_detected",
            change_type="major",
            changed_fields=sorted(changed_fields & _MAJOR_FIELDS),
        )
        return "major"

    if changed_fields & _MINOR_FIELDS:
        logger.info(
            "template_breaking_change_detected",
            change_type="minor",
            changed_fields=sorted(changed_fields & _MINOR_FIELDS),
        )
        return "minor"

    logger.info(
        "template_breaking_change_detected",
        change_type="patch",
        changed_fields=sorted(changed_fields),
    )
    return "patch"


def bump_version(current: str, change_type: ChangeType) -> str:
    """
    Increment a semver string according to the change_type.

    Args:
        current: Current version string (e.g. "1.2.3").
        change_type: 'initial' | 'major' | 'minor' | 'patch'.

    Returns:
        New semver string.

    Raises:
        ValueError: If current is not a valid semver string.
    """
    if change_type == "initial":
        return "1.0.0"

    match = _SEMVER_RE.match(str(current or "").strip())
    if not match:
        # Default to 1.0.0 if current version is malformed
        logger.warning(
            "template_version_malformed",
            current_version=current,
            fallback="1.0.0",
        )
        return "1.0.0"

    major, minor, patch = int(match.group(1)), int(match.group(2)), int(match.group(3))

    if change_type == "major":
        return f"{major + 1}.0.0"
    if change_type == "minor":
        return f"{major}.{minor + 1}.0"
    # patch
    return f"{major}.{minor}.{patch + 1}"
