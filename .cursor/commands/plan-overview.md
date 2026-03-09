# plan-overview

Review a plan created in another chat.
Check for clarity, correctness, and truthfulness.
Suggest improvements that make the plan and resulting code clearer, simpler, more maintainable, and more robust.
List suggestions in order of importance.

Things to prioritize:
- The plan will solve the stated problem or refactor.
- The plan leads to a maintainable solution.
- The plan is easy to follow.
- The plan is sufficiently comprehensive.

How to review:
- Read the plan end-to-end once without comments.
- Restate the goal in one sentence and check that every step supports it.
- Validate assumptions and prerequisites (data, configs, dependencies, access).
- Spot gaps: missing steps, edge cases, rollback, tests, docs, monitoring.
- Flag risky steps, vague language, or steps that hide complexity.
- Prefer fewer steps, clearer names, and stronger ordering.
- Note any contradictions or claims that cannot be verified.

Checklist:
- Goal is stated clearly and matches the request.
- Scope is explicit (what is in/out).
- Dependencies and prerequisites are listed.
- Step order is logical and feasible.
- Each step is actionable and unambiguous.
- APIs, files, and areas to touch are identified.
- Risks and edge cases are addressed.
- Testing plan is included.
- Documentation updates are called out.
- Validation/rollback steps are included when needed.
    