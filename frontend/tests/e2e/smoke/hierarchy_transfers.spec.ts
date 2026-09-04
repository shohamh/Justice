import type { Browser, BrowserContext, Page } from "@playwright/test";

import { expect, test } from "../fixtures/test";
import { journeyActorStorageState, roleStorageState, type Role, type JourneyActor as AuthJourneyActor } from "../fixtures/auth";

/**
 * Task 3 UI seam inventory (every control/endpoint this spec drives, plus
 * corrections to the plan's brief made after reading the real
 * components/services/routes — not guesses, per the same discipline
 * swaps.spec.ts and ranges.spec.ts document for Tasks 1-2):
 *
 * - Page boundary: `/team` (`TeamHierarchyPage`), tree `data-testid="node-tree"`
 *   rendered by `HierarchyTree.tsx`. Every node row is both a dnd-kit
 *   draggable (for node-drag/`moveNode`, out of scope here — see below) and
 *   a dnd-kit droppable (for a soldier dropped onto it), sharing the SAME
 *   ref'd `<div>` for both, so any point inside that row (we target the
 *   `tree-name-{nodeId}` span, per the brief) registers as "over" that node.
 * - Create (click-based, "quick add"): per-node `tree-add-soldier-{nodeId}`
 *   button (rendered only inside the desktop `tree-action-group-{nodeId}`
 *   grid — `hidden sm:grid`, i.e. only visible at >= Tailwind `sm` (640px);
 *   this spec runs under `--project=desktop` so this holds) -> inline
 *   `SoldierSearchAutocomplete` (`soldier-search-input` ->
 *   `soldier-search-result-{personal_number}`) -> since the soldier already
 *   exists, `handleQuickAdd` routes straight into
 *   `openTransferConfirmation` (never `onboardSoldier`) -> `ConfirmDialog`
 *   with reason field `transfer-reason` -> confirm `confirm-dialog-confirm`
 *   -> `POST /api/hierarchy-transfers`.
 * - Create (drag-and-drop): soldier row drag handle — a plain `<span>` with
 *   the dnd-kit `useDraggable` listeners, INSIDE
 *   `tree-soldier-{personal_number}` but with no testid of its own, located
 *   via `span.cursor-grab` scoped to that row (only rendered when the
 *   *source* node's `can_edit` is true) — dropped onto the destination
 *   node's `tree-name-{nodeId}` span -> `handleDragEnd` -> the exact same
 *   `openTransferConfirmation` -> `ConfirmDialog` -> same
 *   `POST /api/hierarchy-transfers`. Confirmed by reading `HierarchyTree.tsx`
 *   directly: `DraggableSoldier` and `DroppableNodeRow` around lines 82-202,
 *   `handleDragEnd` around line 576. Drag simulated via
 *   `hover()`-equivalent `mouse.move()` -> `mouse.down()` -> several small
 *   incremental `mouse.move()` calls (not one large jump, to clear the
 *   `PointerSensor`'s `activationConstraint: { distance: 8 }`) ->
 *   `mouse.up()` — never native HTML5 `dispatchEvent`-based drag, which
 *   dnd-kit's pointer sensor does not listen for at all.
 * - Explicitly OUT OF SCOPE (per the brief): node-drag-to-move (dragging a
 *   node's own `span.cursor-grab` handle — a *different* draggable, on
 *   `DroppableNodeRow` itself, not `DraggableSoldier` — onto another node)
 *   calls `moveNode` -> `POST /hierarchy/nodes/{id}/move`, a separate,
 *   immediate, no-approval structural edit. This spec never grabs a node's
 *   own handle, only a soldier row's `span.cursor-grab` inside
 *   `tree-soldier-{personal_number}` — a different draggable id/data
 *   (`soldier:{id}` vs `node-drag:{id}`) entirely, so there is no risk of
 *   accidentally exercising `moveNode` here. This remains an uncovered gap,
 *   flagged in the coverage matrix rather than silently implied as tested.
 * - Approver view: `ApprovalsPage`, tab `approvals-tab-transfers`
 *   (URL `?tab=transfers` works directly, confirmed by reading the page's
 *   own `VALID_TABS`/`searchParams` handling) -> per-request
 *   `transfer-approve-{id}` / (`transfer-reject-note-{id}` fill required,
 *   the reject button `transfer-reject-{id}` stays `disabled` until it has
 *   text — confirmed by reading `ApprovalsPage.tsx` directly) ->
 *   `POST /api/hierarchy-transfers/{id}/approve` / `/reject`.
 * - CORRECTION (found by reading `backend/app/routes/hierarchy_transfers.py`
 *   directly): none of create/approve/reject override FastAPI's default
 *   status code — all three return **200**, not 201 as swaps.spec.ts's
 *   create calls do. Asserted as such below.
 * - CORRECTION (found by reading `backend/app/routes/my_requests.py`'s
 *   `my_hierarchy_transfers` end to end, prompted by the brief's own
 *   "confirm the exact selector/behaviour before writing" discipline — this
 *   one is NOT a testid typo but a real behavioural mismatch with the
 *   brief's assumption): `GET /me/hierarchy-transfers` (the query behind
 *   `MyRequestsPage`'s `?tab=existing&type=transfers` "transfers" group)
 *   filters `HierarchyTransferRequest.soldier_id == user.id` — the
 *   *transferred* soldier — not `requested_by == user.id`. Every other
 *   request type on that page (swaps, exemptions, constraints...) is a
 *   soldier acting for themselves, so "the requester" and "the soldier the
 *   request is about" are the same person there; a hierarchy transfer is
 *   submitted *about* a soldier by their commander/duty-manager, and it is
 *   the transferred soldier — never the commander/duty-manager who clicked
 *   submit — who can see it on `/my-requests`. The submitting
 *   commander/duty-manager has no view of their own submitted request
 *   anywhere once it leaves `/approvals` (that tab only lists *pending*
 *   requests). This spec therefore logs in as the actual transferred
 *   soldier (`transferSoldier`, a new journey actor — see fixtures/auth.ts)
 *   to verify the rejection-path assertion, rather than the commander/
 *   duty-manager session that clicked "submit".
 * - Node/soldier identity: `commander` (2000001) directly commands branch
 *   "פוקוס", and `dutyManager` (2500001) holds a `DutyManagerScope` over the
 *   whole "פוקוס" branch subtree (both confirmed directly in seed.py, and
 *   already relied on by ranges.spec.ts for `dutyManager`'s own-node
 *   creation) — `can()`'s scope check (`_node_in_scope`, path_ids
 *   containment) therefore grants BOTH of them `Action.HIERARCHY_TRANSFER`
 *   (create authorized on the source node, approve/reject on the
 *   destination node) and `Action.HIERARCHY_MANAGE`/`can_edit` (drag handle
 *   + "add soldier" button visibility) on every team under that branch,
 *   including the source ("צוות ריי") and destination ("צוות ספארק") teams
 *   used below — both siblings under mador "שבירה", with genuinely distinct
 *   team-leader commanders (per Step 1's "distinct commanders" requirement),
 *   confirmed directly from seed.py's team-node/leader-assignment loop. No
 *   third actor is needed for the create/approve/reject actions themselves.
 */

type JourneyActor = "dutyManager" | "commander" | "transferSoldier";

const actorStorageRole: Record<JourneyActor, Role> = {
  dutyManager: "dutyManager",
  commander: "commander",
  transferSoldier: "soldier",
};

const journeyStorageActor: Partial<Record<JourneyActor, AuthJourneyActor>> = {
  transferSoldier: "transferSoldier",
};

type RoleContext = { context: BrowserContext; page: Page };

const SOURCE_NODE_NAME = "צוות ריי";
const DEST_NODE_NAME = "צוות ספארק";
// Ancestor chain shared by both teams: root -> פסיפס -> פוקוס -> שבירה.
const ANCESTOR_CHAIN = ["כלל המסגרת", "פסיפס", "פוקוס", "שבירה"];

async function openActorContext(browser: Browser, actor: JourneyActor): Promise<RoleContext> {
  const projectUse = test.info().project.use as {
    baseURL?: string;
    viewport?: { width: number; height: number };
  };
  const journeyActor = journeyStorageActor[actor];
  const context = await browser.newContext({
    baseURL: projectUse.baseURL ?? "http://localhost:5173",
    viewport: projectUse.viewport,
    storageState: journeyActor ? journeyActorStorageState(journeyActor) : roleStorageState(actorStorageRole[actor]),
  });
  return { context, page: await context.newPage() };
}

/** Locates a node's own row (toggle + name + edit/add/delete controls) by
 * its exact, tree-unique Hebrew name. The row's containing `<div>` (from
 * `DroppableNodeRow`) holds only that row's own controls — child nodes and
 * soldiers live in sibling `<ul>`s outside it — so a `hasText` filter on
 * this specific class combination cannot accidentally match a descendant
 * row too. */
function nodeRowLocator(page: Page, nodeName: string) {
  return page.locator("div.flex.flex-wrap.items-center").filter({ hasText: nodeName }).first();
}

/** Expands a node (via its own toggle button) only if it is currently
 * collapsed ("▶") — never blindly clicks, since clicking an
 * already-expanded node would collapse it instead. The toggle button is the
 * one `<button>` preceding the name span within the row's inner flex div
 * (drag-handle/level-label siblings before it are `<span>`s, not
 * `<button>`s), confirmed by reading `DroppableNodeRow` directly. */
async function ensureNodeExpanded(page: Page, nodeName: string): Promise<void> {
  const nameSpan = page.getByTestId("node-tree").getByText(nodeName, { exact: true });
  await expect(nameSpan).toBeVisible({ timeout: 30_000 });
  const toggle = nameSpan.locator("xpath=preceding-sibling::button[1]");
  const label = (await toggle.textContent())?.trim();
  if (label === "▶") {
    await toggle.click();
  }
}

async function expandAncestorChain(page: Page): Promise<void> {
  for (const name of ANCESTOR_CHAIN) {
    await ensureNodeExpanded(page, name);
  }
}

/** Click-based creation ("quick add"): opens the destination node's
 * add-soldier search, selects the existing soldier by personal number
 * (routing into the transfer-confirmation flow since the soldier already
 * exists — see seam inventory), fills the reason, and confirms. Returns the
 * created request's id and the source/destination node ids straight from
 * the response body, so later assertions can scope precisely to
 * `tree-soldiers-{nodeId}` rather than guessing at node ids from the DOM. */
async function createTransferViaClick(
  page: Page,
  args: { personalNumber: string; destNodeName: string; reason: string },
): Promise<{ id: string; fromNodeId: string | null; toNodeId: string }> {
  await page.goto("/team");
  await expect(page.getByTestId("team-page")).toBeVisible({ timeout: 30_000 });
  const destRow = nodeRowLocator(page, args.destNodeName);
  await expect(destRow).toBeVisible({ timeout: 30_000 });
  await destRow.locator('[data-testid^="tree-add-soldier-"]').click();

  const searchInput = page.getByTestId("soldier-search-input");
  await expect(searchInput).toBeVisible({ timeout: 30_000 });
  await searchInput.fill(args.personalNumber);
  const result = page.getByTestId(`soldier-search-result-${args.personalNumber}`);
  await expect(result).toBeVisible({ timeout: 30_000 });
  await result.click();

  const reasonField = page.getByTestId("transfer-reason");
  await expect(reasonField).toBeVisible({ timeout: 30_000 });
  await reasonField.fill(args.reason);
  const create = page.waitForResponse(r => r.url().endsWith("/api/hierarchy-transfers") && r.request().method() === "POST");
  await page.getByTestId("confirm-dialog-confirm").click();
  const response = await create;
  expect(response.status()).toBe(200);
  const body = await response.json() as { id: string; from_node_id: string | null; to_node_id: string };
  return { id: body.id, fromNodeId: body.from_node_id, toNodeId: body.to_node_id };
}

/** Drag-and-drop creation: grabs the soldier row's own drag-handle span
 * (never the node row's own handle — that's `moveNode`, explicitly out of
 * scope) and drops it onto the destination node's name span, via a real
 * pointer sequence (hover -> down -> several small incremental moves -> up)
 * so dnd-kit's `PointerSensor` (8px activation distance) actually starts a
 * drag rather than registering a click. Asserts the `ConfirmDialog` opened
 * as proof `handleDragEnd` routed into the same transfer-confirmation flow,
 * then fills the reason and confirms exactly like the click path. */
async function createTransferViaDrag(
  page: Page,
  args: { personalNumber: string; destNodeName: string; reason: string },
): Promise<{ id: string; fromNodeId: string | null; toNodeId: string }> {
  await page.goto("/team");
  await expect(page.getByTestId("team-page")).toBeVisible({ timeout: 30_000 });
  await expandAncestorChain(page);
  await ensureNodeExpanded(page, SOURCE_NODE_NAME);
  await ensureNodeExpanded(page, args.destNodeName);

  const handle = page.getByTestId(`tree-soldier-${args.personalNumber}`).locator("span.cursor-grab");
  await expect(handle).toBeVisible({ timeout: 30_000 });
  const destName = page.getByTestId("node-tree").getByText(args.destNodeName, { exact: true });
  await expect(destName).toBeVisible({ timeout: 30_000 });

  // With the whole branch expanded (see ensureNodeExpanded above), the tree
  // is far taller than one viewport — `boundingBox()` is viewport-relative,
  // so without this, one (or both) of source/destination can sit outside
  // the visible area and every `page.mouse` coordinate lands on nothing,
  // silently no-opping the whole drag (confirmed directly: the drop never
  // opened the confirmation dialog until this fix). The page itself does
  // NOT scroll — `Layout`'s `<main>` (`overflow-y-auto`) is the actual
  // scrolling container, confirmed directly by walking the DOM for the
  // first scrollable ancestor; `window.scrollTo`/`window.scrollY` are
  // no-ops here. Scroll that container to the midpoint between the two
  // rows (in its own scroll-space) so both are simultaneously in view for
  // the coordinate-based mouse sequence below.
  // Each callback below is passed to `page`/`locator.evaluate`, which
  // serializes only the function itself for in-browser execution — no
  // outer-scope helper functions are reachable from inside it, so the
  // scroll-container lookup is duplicated inline in each one rather than
  // factored out (a first attempt that called a shared outer `const`
  // function from inside `evaluate` threw a browser-side ReferenceError).
  const absoluteTop = (el: Element): number => {
    let node: Element | null = el;
    while (node) {
      const style = getComputedStyle(node);
      if ((style.overflowY === "auto" || style.overflowY === "scroll") && node.scrollHeight > node.clientHeight + 5) break;
      node = node.parentElement;
    }
    const scroller = (node ?? document.scrollingElement) as HTMLElement;
    return el.getBoundingClientRect().top + scroller.scrollTop;
  };
  const containerClientHeight = (el: Element): number => {
    let node: Element | null = el;
    while (node) {
      const style = getComputedStyle(node);
      if ((style.overflowY === "auto" || style.overflowY === "scroll") && node.scrollHeight > node.clientHeight + 5) break;
      node = node.parentElement;
    }
    return ((node ?? document.scrollingElement) as HTMLElement).clientHeight;
  };
  const [handleAbsY, destAbsY, containerHeight] = await Promise.all([
    handle.evaluate(absoluteTop),
    destName.evaluate(absoluteTop),
    handle.evaluate(containerClientHeight),
  ]);
  const midpoint = (handleAbsY + destAbsY) / 2;
  await handle.evaluate((el, targetScrollTop) => {
    let node: Element | null = el;
    while (node) {
      const style = getComputedStyle(node);
      if ((style.overflowY === "auto" || style.overflowY === "scroll") && node.scrollHeight > node.clientHeight + 5) break;
      node = node.parentElement;
    }
    const scroller = (node ?? document.scrollingElement) as HTMLElement;
    scroller.scrollTop = Math.max(0, targetScrollTop);
  }, midpoint - containerHeight / 2);

  const startBox = await handle.boundingBox();
  const endBox = await destName.boundingBox();
  if (!startBox || !endBox) throw new Error("drag source/target not measurable");
  const startX = startBox.x + startBox.width / 2;
  const startY = startBox.y + startBox.height / 2;
  const endX = endBox.x + endBox.width / 2;
  const endY = endBox.y + endBox.height / 2;

  await page.mouse.move(startX, startY);
  await page.mouse.down();
  const steps = 12;
  for (let i = 1; i <= steps; i += 1) {
    await page.mouse.move(
      startX + ((endX - startX) * i) / steps,
      startY + ((endY - startY) * i) / steps,
    );
  }
  // A short pause at the final position before releasing — dnd-kit's
  // droppable `isOver` state needs the pointermove event to be processed
  // before pointerup, and an instant down->moves->up sequence with no
  // settle time occasionally raced that in practice.
  await page.waitForTimeout(200);
  await page.mouse.up();

  // Proves handleDragEnd actually fired and routed into
  // openTransferConfirmation, not just that the mouse moved.
  const reasonField = page.getByTestId("transfer-reason");
  await expect(reasonField).toBeVisible({ timeout: 30_000 });
  await reasonField.fill(args.reason);
  const create = page.waitForResponse(r => r.url().endsWith("/api/hierarchy-transfers") && r.request().method() === "POST");
  await page.getByTestId("confirm-dialog-confirm").click();
  const response = await create;
  expect(response.status()).toBe(200);
  const body = await response.json() as { id: string; from_node_id: string | null; to_node_id: string };
  return { id: body.id, fromNodeId: body.from_node_id, toNodeId: body.to_node_id };
}

async function approveTransfer(page: Page, args: { requestId: string }): Promise<void> {
  await page.goto("/approvals?tab=transfers");
  const approveButton = page.getByTestId(`transfer-approve-${args.requestId}`);
  await expect(approveButton).toBeVisible({ timeout: 30_000 });
  const approve = page.waitForResponse(r => r.url().includes(`/hierarchy-transfers/${args.requestId}/approve`) && r.request().method() === "POST");
  await approveButton.click();
  expect((await approve).status()).toBe(200);
}

async function rejectTransfer(page: Page, args: { requestId: string; note: string }): Promise<void> {
  await page.goto("/approvals?tab=transfers");
  const noteInput = page.getByTestId(`transfer-reject-note-${args.requestId}`);
  await expect(noteInput).toBeVisible({ timeout: 30_000 });
  await noteInput.fill(args.note);
  const rejectButton = page.getByTestId(`transfer-reject-${args.requestId}`);
  await expect(rejectButton).toBeEnabled();
  const reject = page.waitForResponse(r => r.url().includes(`/hierarchy-transfers/${args.requestId}/reject`) && r.request().method() === "POST");
  await rejectButton.click();
  expect((await reject).status()).toBe(200);
}

/** After a refresh, asserts the soldier's row is visible specifically
 * inside the given node's own `tree-soldiers-{nodeId}` container — not just
 * "visible somewhere" — proving the transfer actually moved them, not just
 * that the approve call returned 2xx. */
async function assertSoldierInNode(page: Page, args: { nodeId: string; personalNumber: string }): Promise<void> {
  await page.goto("/team");
  await expandAncestorChain(page);
  await ensureNodeExpanded(page, SOURCE_NODE_NAME);
  await ensureNodeExpanded(page, DEST_NODE_NAME);
  const container = page.getByTestId(`tree-soldiers-${args.nodeId}`);
  await expect(container).toBeVisible({ timeout: 30_000 });
  await expect(container.getByTestId(`tree-soldier-${args.personalNumber}`)).toBeVisible({ timeout: 30_000 });
}

async function assertSoldierNotInNode(page: Page, args: { nodeId: string; personalNumber: string }): Promise<void> {
  await page.goto("/team");
  await expandAncestorChain(page);
  await ensureNodeExpanded(page, SOURCE_NODE_NAME);
  await ensureNodeExpanded(page, DEST_NODE_NAME);
  const container = page.getByTestId(`tree-soldiers-${args.nodeId}`);
  // The container may or may not still exist (it always will here, since
  // several other members remain), but either way the soldier's own row
  // must not be inside it.
  await expect(container.getByTestId(`tree-soldier-${args.personalNumber}`)).toHaveCount(0);
}

test.describe.configure({ mode: "serial" });

// Desktop-only per the plan's Global Constraints: the click-based creation
// path targets a control that is `display:none` below the `sm` breakpoint
// (hidden sm:grid in HierarchyTree.tsx), so it cannot pass at mobile-390.
test.beforeEach(async ({}, testInfo) => {
  test.skip(testInfo.project.name !== "desktop", "desktop-only journey per plan's Global Constraints");
});

test("hierarchy transfer via click, approve, and verify placement @smoke", async ({ browser }) => {
  test.setTimeout(600_000);
  const dutyManager = await openActorContext(browser, "dutyManager");
  const commander = await openActorContext(browser, "commander");
  try {
    const reason = `העברת חייל E2E ${Date.now()}`;
    const transfer = await createTransferViaClick(dutyManager.page, {
      personalNumber: "1000033", destNodeName: DEST_NODE_NAME, reason,
    });
    expect(transfer.toNodeId).toBeTruthy();

    await approveTransfer(commander.page, { requestId: transfer.id });

    await assertSoldierInNode(dutyManager.page, { nodeId: transfer.toNodeId, personalNumber: "1000033" });
    if (transfer.fromNodeId) {
      await assertSoldierNotInNode(dutyManager.page, { nodeId: transfer.fromNodeId, personalNumber: "1000033" });
    }
  } finally {
    await Promise.all([dutyManager.context.close(), commander.context.close()]);
  }
});

test("hierarchy transfer via drag-and-drop, approve, and verify placement @smoke", async ({ browser }) => {
  test.setTimeout(600_000);
  const dutyManager = await openActorContext(browser, "dutyManager");
  const commander = await openActorContext(browser, "commander");
  try {
    const reason = `העברת חייל E2E גרירה ${Date.now()}`;
    // A second, still-untouched member of the source team — the first
    // test above already moved 1000033 out, so this avoids colliding with
    // that soldier's now-changed node.
    const transfer = await createTransferViaDrag(commander.page, {
      personalNumber: "1000034", destNodeName: DEST_NODE_NAME, reason,
    });
    expect(transfer.toNodeId).toBeTruthy();

    await approveTransfer(dutyManager.page, { requestId: transfer.id });

    await assertSoldierInNode(commander.page, { nodeId: transfer.toNodeId, personalNumber: "1000034" });
    if (transfer.fromNodeId) {
      await assertSoldierNotInNode(commander.page, { nodeId: transfer.fromNodeId, personalNumber: "1000034" });
    }
  } finally {
    await Promise.all([dutyManager.context.close(), commander.context.close()]);
  }
});

test("hierarchy transfer rejection path shows the reason to the transferred soldier @smoke", async ({ browser }) => {
  test.setTimeout(600_000);
  const dutyManager = await openActorContext(browser, "dutyManager");
  const commander = await openActorContext(browser, "commander");
  // See seam-inventory correction: /my-requests's transfer listing is keyed
  // by the *transferred* soldier, not whoever submitted the request — so
  // this must be a session logged in as that soldier, not dutyManager or
  // commander.
  const transferSoldier = await openActorContext(browser, "transferSoldier");
  try {
    const reason = `העברת חייל E2E דחייה ${Date.now()}`;
    // A third, still-untouched member of the source team. This is the same
    // soldier as the `transferSoldier` journey actor (personal number
    // 1000035) — see fixtures/auth.ts.
    const transfer = await createTransferViaClick(dutyManager.page, {
      personalNumber: "1000035", destNodeName: DEST_NODE_NAME, reason,
    });

    const rejectionNote = `אין מקום בצוות היעד E2E ${Date.now()}`;
    await rejectTransfer(commander.page, { requestId: transfer.id, note: rejectionNote });

    // The rejection reason is visible to the transferred soldier on their
    // own /my-requests page.
    await transferSoldier.page.goto("/my-requests?tab=existing&type=transfers");
    const row = transferSoldier.page.getByTestId(`transfer-row-${transfer.id}`);
    await expect(row).toBeVisible({ timeout: 30_000 });
    await expect(row).toContainText(rejectionNote);

    // A rejected request has no side effect on the hierarchy: the soldier
    // never left their original team.
    if (transfer.fromNodeId) {
      await assertSoldierInNode(dutyManager.page, { nodeId: transfer.fromNodeId, personalNumber: "1000035" });
    }
  } finally {
    await Promise.all([
      dutyManager.context.close(),
      commander.context.close(),
      transferSoldier.context.close(),
    ]);
  }
});
