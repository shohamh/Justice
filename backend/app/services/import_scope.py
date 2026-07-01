from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.auth.authz import scope_root_ids
from app.db.models import HierarchyNode, Soldier


def is_node_in_actor_scope(*, session: Session, actor: Soldier, node_id: uuid.UUID | None) -> bool:
    """True if `actor` may import a row targeting `node_id`.

    Admins are unrestricted, regardless of `node_id` (including an
    unresolved/None node — an admin importing a row whose node hasn't been
    resolved yet is still allowed to proceed on the scope axis; other
    validation layers are responsible for rejecting an unresolved node).

    Duty managers (and commanders, via the same `scope_root_ids` roots) must
    have `node_id` within one of their managed subtrees. A `None` node_id is
    never in scope for a non-admin actor — an unresolved node can't be
    verified as within scope and must be resolved to a real node first.
    """
    if actor.role == "admin":
        return True
    if node_id is None:
        return False
    roots = scope_root_ids(session, actor)
    if not roots:
        return False
    node = session.get(HierarchyNode, node_id)
    if node is None:
        return False
    return any(r in node.path_ids for r in roots)
