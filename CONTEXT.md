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
