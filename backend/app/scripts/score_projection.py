from __future__ import annotations

import argparse
import uuid


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill persisted scoring projections")
    parser.add_argument("--batch-size", type=int, default=500, metavar="N")
    parser.add_argument("--resume-after", type=uuid.UUID, default=None, metavar="SOLDIER_UUID")
    parser.add_argument(
        "--until-complete",
        action="store_true",
        help="Continue batch-by-batch until the projection backfill is complete",
    )
    args = parser.parse_args()

    from app.db.session import SessionLocal
    from app.services.score_projection import backfill_score_projection

    resume_after = args.resume_after
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
                f"resume_after={state.resume_after_soldier_id}"
            )
            if not args.until_complete or state.backfill_complete:
                break
            resume_after = state.resume_after_soldier_id


if __name__ == "__main__":
    main()
