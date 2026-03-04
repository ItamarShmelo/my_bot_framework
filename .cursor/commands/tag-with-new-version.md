# tag-with-new-version

Tag the commit given by the user (if none is given, default to the current commit)
with the next version. Determine the next version by inspecting existing git tags.

- If the commit is on the **beta** branch, use `v{MAJOR}.{MINOR}.{PATCH}-beta.{N+1}`
  where N is the highest existing beta number for the current `MAJOR.MINOR.PATCH`.
- If the commit is on the **main** branch, ask the user whether to increment by 1 the
  **patch**, **minor**, or **major** number, then use `v{MAJOR}.{MINOR}.{PATCH}`
  accordingly.
- If the commit is on another branch, ask the user which versioning scheme to use.
- If the commit already has a version tag, inform the user and ask how to proceed.

Use the commit's subject line as the annotated tag message, unless the user gives a different message explicitly.

Before creating the tag, show the proposed tag name and ask for confirmation.
Do not push the tag to the remote unless the user explicitly asks.
