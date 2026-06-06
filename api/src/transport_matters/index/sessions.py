"""Session correlation helpers: frozen namespace plus deterministic synth."""

import uuid

# Frozen namespace for read-back session_id synthesis. Seeded into schema_meta.session_ns and
# gated on boot, so bumping it is a schema-version change (§3.2/§3.4).
SESSION_NS = uuid.UUID("a3f1c2d4-5e6b-4a7c-8d9e-0f1a2b3c4d5e")


def synth_session_id(run_id: str, provider: str, native_session_id: str) -> str:
    """Synthesize a read-back session_id (§3.4): ``uuid5`` over the frozen ``SESSION_NS``.

    Pure, so a read-back provider's wire correlation and transcript adapter independently compute
    the same value over the same ``(run_id, provider, native_session_id)`` and the pivot joins.
    """
    return str(uuid.uuid5(SESSION_NS, f"{run_id}|{provider}|{native_session_id}"))
