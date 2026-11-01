"""Shared token-policy accessor.

One home for the profile -> token-policy field mapping, used by
orchestration-gatekeeper.py.
"""


def token_policy_from_profile(profile: dict) -> dict:
    """Return the token-policy fields for a single repo profile dict.

    Shape is declared in docs/TOKEN-POLICY.md: a `token_policy` object holding
    ignore_globs, doc_priority_hints, generated_artifact_dirs. Missing fields
    come back as empty lists, and so does a null `token_policy`, so callers can validate rather than KeyError.
    """
    tp = profile.get("token_policy") or {}  # a null policy declares nothing
    return {
        "ignore_globs": tp.get("ignore_globs", []),
        "doc_priority_hints": tp.get("doc_priority_hints", []),
        "generated_artifact_dirs": tp.get("generated_artifact_dirs", []),
    }
