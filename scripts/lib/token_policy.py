"""Shared token-policy normalization.

Used by both orchestration-gatekeeper.py and apply-token-policy.py, which
previously carried independent copies of this logic and could drift.
"""


def token_policy_from_profile(profile: dict) -> dict:
    """Return normalized token-policy fields for a single repo profile dict.
    Reads from the token_policy wrapper first, falls back to flat camelCase
    fields for backward compat."""
    tp = profile.get("token_policy", {})
    return {
        "ignore_globs": tp.get("ignore_globs") or profile.get("ignoreGlobs", []),
        "doc_priority_hints": tp.get("doc_priority_hints") or profile.get("docPriorityHints", []),
        "generated_artifact_dirs": tp.get("generated_artifact_dirs") or profile.get("generatedArtifactDirs", []),
    }
