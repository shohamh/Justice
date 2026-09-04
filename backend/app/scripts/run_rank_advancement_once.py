"""One-shot rank-advancement pass. Runs the same promotion logic the daily
worker runs, without waiting for its poll interval. Safe to run manually
in any environment -- it only promotes soldiers already due.

``_promote_due_soldiers`` opens and commits its own ``session_scope()``
internally (see ``app/rank_advancement_worker.py``), so this wrapper takes
no session of its own -- doing so would open a second, unused session.
"""
from app.rank_advancement_worker import _promote_due_soldiers


def main() -> None:
    _promote_due_soldiers()


if __name__ == "__main__":
    main()
