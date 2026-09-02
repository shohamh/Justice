# Multi-user duty problem journey

## Goal

Add a real-browser, multi-role journey proving that a duty manager can use both algorithmic and manual assignment, and that post-assignment availability problems are surfaced and resolved through the UI.

## Actors

- Duty manager: creates/configures the duty, runs and publishes the algorithm, makes a manual assignment, and resolves replacements.
- Commander: observes the duty and its problems and confirms that an exemption conflict is visible in their operational view.
- Assigned soldiers: one receives a duty exemption, one receives גימלים, one reports inability to attend, and one receives Hakpaza Pikudit.
- Reserves: the first reserve is called up after an assignee becomes unavailable, then receives גימלים during the duty; a second reserve is called up.

## Browser-only constraint

All state transitions must use visible application UI. The test may use browser contexts and navigation, but must not create or mutate duties, assignments, requests, exemptions, absences, or reserve records through API calls or direct database access. Setup must use existing visible configuration screens and seeded users only.

## Journey

1. Duty manager creates a uniquely named future duty and runs the algorithm.
2. Duty manager reviews and publishes algorithm results, then manually assigns the additional soldier.
3. The assigned soldier submits an exemption through the UI; after approval, the duty manager and commander both see a problem on the affected shift.
4. A second assigned soldier submits גימלים through the UI; the assignment becomes unavailable.
5. A third assigned soldier reports inability to attend; the duty manager calls up the first reserve through the UI.
6. A fourth assigned soldier receives Hakpaza Pikudit through the UI; the shift and commander-facing problem distinguish this from an ordinary exemption.
7. The called-up reserve submits גימלים during the duty; the duty manager calls up a second reserve.
8. Refresh each role’s context and assert the final assignment, reserve, problem, reason, and history states.

## Assertions

The test must assert visible state after every mutation, including algorithm publication, manual assignment, problem creation, reserve activation, and second replacement. It must verify that the commander can see the exemption conflict and that no unavailable soldier remains the active assignee after replacement.

## Implementation boundary

First inspect the existing UI routes and selectors for algorithm jobs, shift management, exemptions, Hakpaza, sick leave, absence reporting, reserve activation, and commander dashboards. Add only the missing UI behavior and stable selectors required to make the complete journey possible. If a transition is not currently represented in the product UI, implement that UI flow and its focused component/API tests before adding the browser assertion.

The journey remains serial and runs in Chrome at desktop and 390px mobile viewports. It uses a dedicated scenario and must not alter the existing seeded accounts or unrelated development data.
