# Security policy

## Reporting
Please don't open public issues for vulnerabilities. Use GitHub's **Security → Report a vulnerability** (private reporting) with steps to reproduce and impact.

In scope: anything that lets an agent or a web page bypass the permission engine, approvals, workspace confinement, SSRF guards, memory namespace rules or the emergency stop; credential leaks; auth bypass.

## Leaked secrets
If you find a key or personal data in this repository or its history, report it privately. It will be revoked and rotated first, then removed from history.

## Operating safely
- Keep the API bound to 127.0.0.1; put it behind your own authentication if you need remote access.
- Point `STARK_WORKSPACE_ROOTS` at folders you are happy for agents to read.
- Prefer Assist mode; grant Execute-approved scopes narrowly and with expiry.
