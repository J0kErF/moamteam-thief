"""End-of-game report emission: write the four artifacts, then (when enabled) mail
them through the Gatekeeper. Each peer sends its OWN report — rule #35: a side
that does not report earns nothing, board result notwithstanding.

League convention (interop kit §6.1, played 2026-08-04): ONE email per team per
counted SERIES — the result JSON as the body (exact canonical bytes, never a
pretty-print) and the same file as the single attachment. Declaration, configs
and logs are published in the repos, reached via ``links.github``, never mailed.
Per-sub-game emission stays for artifact WRITING; the mail belongs to the series.
"""

import logging
from pathlib import Path

from moamteam.report.artifacts import ReportBundle
from moamteam.report.series_result import result_bytes
from moamteam.shared.gatekeeper import Gatekeeper

logger = logging.getLogger(__name__)


def emit_series_report(report: dict, *, email_config: dict,
                       gatekeeper: Gatekeeper, reports_dir: str | Path,
                       sender=None) -> dict:
    """Write ``result_<game_id>.json`` as the EXACT canonical bytes and (when
    enabled) mail those bytes as the body with the file attached."""
    reports_dir = Path(reports_dir)
    reports_dir.mkdir(parents=True, exist_ok=True)
    body = result_bytes(report)
    path = reports_dir / f"result_{report['game_id']}.json"
    path.write_bytes(body)
    summary: dict = {"written": [str(path)], "emailed": False}

    if not email_config.get("enabled", False):
        summary["skipped"] = "email disabled in private config"
        return summary
    verdict = gatekeeper.admit()
    if not verdict.allowed:
        summary["skipped"] = f"gatekeeper refused at gate {verdict.gate!r}"
        logger.warning("series report NOT sent: %s", summary["skipped"])
        return summary
    if sender is None:
        from moamteam.infra.email_sender import GmailSender

        sender = GmailSender(
            email_config.get("credentials_path", "credentials.json"),
            email_config.get("token_path", "token.json"),
        )
    counted = report.get("league", {}).get("counted", False)
    summary["message_id"] = sender.send_with_backoff(
        to=email_config["recipient"],
        subject=(f"[{report['game_id']}] final series result — "
                 f"{'counted' if counted else 'friendly'}"),
        body=body.decode("utf-8"),
        attachments=[path],
        max_retries=3,
        backoff_seconds=5,
    )
    summary["emailed"] = True
    return summary


def emit_match_reports(bundle: ReportBundle, *, email_config: dict,
                       gatekeeper: Gatekeeper, reports_dir: str | Path,
                       sender=None) -> dict:
    """Write artifacts; mail them if [email].enabled. Returns a summary dict that
    the caller logs — emission must NEVER crash the runtime."""
    written = bundle.write_all(reports_dir)
    summary: dict = {"written": [str(path) for path in written], "emailed": False}

    if not email_config.get("enabled", False):
        summary["skipped"] = "email disabled in private config"
        return summary

    verdict = gatekeeper.admit()
    if not verdict.allowed:
        summary["skipped"] = f"gatekeeper refused at gate {verdict.gate!r}"
        logger.warning("report NOT sent: %s", summary["skipped"])
        return summary

    if sender is None:
        from moamteam.infra.email_sender import GmailSender

        sender = GmailSender(
            email_config.get("credentials_path", "credentials.json"),
            email_config.get("token_path", "token.json"),
        )
    message_id = sender.send_with_backoff(
        to=email_config["recipient"],
        subject=f"[{bundle.group_id}] game report {bundle.game_id} "
                f"g{bundle.sub_game_number:02d} — {bundle.outcome}",
        body=(
            f"Automated game report from group {bundle.group_id} ({bundle.role}).\n"
            f"game_id: {bundle.game_id}\nsub_game: {bundle.sub_game_number}\n"
            f"outcome: {bundle.outcome}\nscore: {bundle.score}\n"
            f"llm_tokens_used: {bundle.llm_tokens_used}\n"
            "The four JSON artifacts are attached (machine-readable)."
        ),
        attachments=written,
        max_retries=3,
        backoff_seconds=5,
    )
    summary["emailed"] = True
    summary["message_id"] = message_id
    return summary
