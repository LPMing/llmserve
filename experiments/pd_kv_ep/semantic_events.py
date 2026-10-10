"""Role-safe predicates for the KV-versus-Decode-EP study.

Event type alone is not sufficient: a P/D MoE simulation can emit a Prefill
MoE collective with the same dispatch/combine event codes as Decode EP.  New
native telemetry therefore carries ``serving_role`` and all paper-facing
analysis must select it explicitly.
"""


def is_p2d_kv(row):
    """Return whether a timeline row is a Prefill-originated P2D KV flow."""
    return (row.get("event_type") == "P2D_KV" and
            row.get("serving_role") == "PREFILL")


def is_decode_ep(row):
    """Return whether a timeline row belongs to Decode-side MoE EP."""
    return (row.get("event_type") in ("EP_DISPATCH", "EP_COMBINE") and
            row.get("serving_role") == "DECODE")


def is_study_communication(row):
    """Return whether a row is one of the two data-plane study classes."""
    return is_p2d_kv(row) or is_decode_ep(row)
