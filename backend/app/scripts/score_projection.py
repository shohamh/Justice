from __future__ import annotations

import argparse
from datetime import date
import uuid


def _parse_resume_after_args(
    parser: argparse.ArgumentParser, args: argparse.Namespace
) -> tuple[uuid.UUID, date] | None:
    has_soldier = args.resume_after_soldier is not None
    has_quarter = args.resume_after_quarter is not None
    if has_soldier != has_quarter:
        parser.error(
            "--resume-after-soldier and --resume-after-quarter must be supplied together"
        )
    if not has_soldier:
        return None
    return (args.resume_after_soldier, args.resume_after_quarter)


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill persisted scoring projections")
    parser.add_argument("--batch-size", type=int, default=500, metavar="N")
    parser.add_argument("--resume-after-soldier", type=uuid.UUID, default=None, metavar="SOLDIER_UUID")
    parser.add_argument(
        "--resume-after-quarter",
        type=date.fromisoformat,
        default=None,
        metavar="YYYY-MM-DD",
    )
    parser.add_argument(
        "--until-complete",
        action="store_true",
        help="Continue batch-by-batch until the projection backfill is complete",
    )
    args = parser.parse_args()

    from app.db.session import SessionLocal
    from app.services.score_projection import backfill_score_projection

    resume_after = _parse_resume_after_args(parser, args)
    with SessionLocal() as session:
        while True:
            state = backfill_score_projection(
                session,
                batch_size=args.batch_size,
                resume_after=resume_after,
            )
            session.commit()
            print(
                f"version={state.canonical_version} "
                f"complete={state.backfill_complete} "
                f"resume_after_soldier={state.resume_after_soldier_id} "
                f"resume_after_quarter={state.resume_after_quarter_start}"
            )
            if not args.until_complete or state.backfill_complete:
                break
            resume_after = None


if __name__ == "__main__":
    main()
