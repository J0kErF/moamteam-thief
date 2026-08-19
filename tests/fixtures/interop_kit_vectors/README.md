# Interop-kit conformance vectors (vendored)

Source: https://github.com/Imreec/copthief-league-protocol (Team ImreEyal, with
anrbj666), commit `ad65576`, vendored 2026-08-13. MIT-style open kit for the
course league; vectors are the kit's own synthetic fixtures — no book text or
reference code is copied. See the repo's SPEC.md for the mapping of each vector
to a chapter of the binding book (police_thief_p2p.pdf v3.0.0).

Consumed by `tests/test_interop_kit_conformance.py`: our implementation must
reproduce every CORE construction byte-for-byte (canonical JSON, commit-reveal,
terms signature, game_uid/game_id, report consensus signature) and answer the
behaviour truth tables (pairing declaration, at-least-once delivery) the same
way. Update by re-vendoring from the kit repo; do not edit by hand.
