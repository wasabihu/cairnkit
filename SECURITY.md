# Security

## Reporting a vulnerability

Please do not open a public issue. Use GitHub's
[private vulnerability reporting](https://github.com/wasabihu/cairnkit/security/advisories/new)
or email wasabi.net@gmail.com with a description, the affected version and steps to
reproduce. You should get a first answer within a week.

## Supported versions

Fixes go into the latest minor release (currently 0.3.x).

## Scope

In scope: ways to make cairnkit act for the wrong person, bypass a tool's access level or
roles, slip instructions past the injection scanner into memory or skills, leak secrets
through summaries or logs, or exhaust resources through the document readers.

Out of scope: what a model says (cairnkit cannot make a model truthful), and vulnerabilities
in applications built on cairnkit that come from their own code.
