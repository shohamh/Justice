# Justice Domain Glossary

This glossary defines the shared language for operational feedback and bug triage in Justice.

## Bug reporting

**Bug report**:
A user-submitted description of unexpected or incorrect system behavior, together with the technical context captured when it was submitted.
_Avoid_: issue, ticket, complaint

**Active bug report**:
A bug report whose status is `open` or `in_progress`; these are the reports eligible for agentic triage export.
_Avoid_: current report, unresolved report

**Agentic triage export**:
A read-only ZIP archive containing active bug reports as linked Markdown and image files for human triage and agent-assisted investigation.
_Avoid_: bug dump, report backup

**Filtered export**:
An agentic triage export constrained by the admin table's severity and active-status filters, without applying table pagination.
_Avoid_: page export, visible export

**Original screenshot**:
The image captured with the user's initial bug report.
_Avoid_: report image, first attachment

**Comment attachment**:
An image uploaded as part of a follow-up comment on a bug report.
_Avoid_: comment image, feedback file

## Requests and approvals

**Personal constraint (אילוץ אישי)**:
A recurring personal limitation a soldier submits that restricts which duties can be assigned to them.
_Avoid_: constraint request, restriction

**Exemption request (בקשת פטור)**:
A soldier-submitted request to be relieved from duties, optionally permanent and supported by attached files; distinct from the exemption it may produce.
_Avoid_: exemption application, absence request

**Duty manager (אחראי תורנויות)**:
The staff role whose approval is the final step of a request's approval chain.
_Avoid_: רס"פ, מנהל תורניות, DM


**Approval chain (שרשרת אישור)**:
The ordered steps a request passes through — typically commander first, duty manager last — before it is approved or rejected.
_Avoid_: approval flow, workflow

**Waiting approver (המאשר הנוכחי)**:
The single role currently holding the request in the chain; shown to the soldier as "who needs to approve".
_Avoid_: pending approver, next approver

**Enrollment (קליטה)**:
A soldier's registration request to join the system, including attached exemption requests, resolved by a commander's approval.
_Avoid_: registration request, onboarding

**Hierarchy transfer (מעבר היררכיה)**:
A request to move a soldier between units in the command hierarchy, approved by the destination-side commander or duty manager.
_Avoid_: transfer request, unit move

**Range excusal (פטור ממטווח)**:
A soldier's request to be excused from an assigned shooting-range day; primary requests require duty-manager approval, reserve requests are auto-approved.
_Avoid_: range deferral, דחיית מילואים
