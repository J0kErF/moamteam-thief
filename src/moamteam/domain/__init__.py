"""Pure game domain: board geometry, physics rules, engine, scoring.

No I/O, no network, no LLM — this layer is deterministic and fully unit-testable
(PRD-01). Quantitative values always arrive via ``moamteam.shared.config``.
"""
