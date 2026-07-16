---
name: ui-case-designer
description: Design a reviewable, deterministic browser UI test case draft from a target URL and a natural-language test goal. Use when OmniTest needs AI-assisted UI steps and assertions that must stay inside the platform's supported Playwright DSL.
---

# UI Case Designer

Produce one executable UI case draft. Return only the JSON object defined in
`references/output-schema.json`.

## Design Workflow

1. Treat `target_url` as the fixed entry point and `goal` as the behavior to verify.
2. Convert the goal into the smallest complete user journey that proves the outcome.
3. Prefer stable CSS selectors in this order: `data-testid`, stable `id` or `name`,
   accessible attributes such as `aria-label`, then stable semantic attributes.
4. Avoid dynamic class names, generated ids, positional selectors, and `nth-child` unless
   the supplied context leaves no stable alternative.
5. Use only the action and assertion enums from the output schema.
6. Keep the total number of steps at or below `max_steps`.
7. End with an observable assertion. Make `expect_text` a concise text that should be
   visible after the journey succeeds.
8. Put uncertainties in `warnings`; do not invent credentials, test data, selectors, or
   product behavior.

## Safety Rules

- Keep `target_url` unchanged.
- Do not navigate outside the allowed origins supplied in the request.
- Do not emit JavaScript, `eval`, browser extensions, shell commands, or unsupported
  actions.
- Do not include secrets or real credentials. Preserve template variables such as
  `{{username}}` when the request supplies them.
- Do not claim that the case has executed. This skill only designs a draft for review.
- Return valid JSON without Markdown fences or explanatory text.
