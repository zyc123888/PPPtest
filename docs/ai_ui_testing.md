# OmniTest AI UI Testing

> Status: implemented and verified  
> Document owner: UI Case module  
> Last updated: 2026-07-22

## 1. Purpose

The UI Case module evolves from fixed-selector browser scripts into an AI-assisted
testing system. Users describe what to verify; OmniTest resolves how to operate the
current page; Playwright performs browser actions; deterministic assertions prove the
result.

The design deliberately keeps Playwright as the execution foundation. AI augments
planning, semantic location, recovery, exploration, and visual judgment. It does not
silently redefine pass/fail criteria.

## 2. Product Principles

1. Test intent is durable; generated selectors are replaceable implementation details.
2. Stable regression must remain deterministic, fast, and reviewable.
3. AI recovery is bounded to the current step and never silently rewrites a saved case.
4. Business-critical assertions use deterministic checks whenever possible.
5. Visual AI is used for rendered appearance, canvas, charts, and layout checks.
6. Exploration results are findings and candidate cases, not release-gate evidence.
7. Existing manual and `ai_skill` UI cases remain executable without migration work.
8. Every AI decision records its input summary, chosen target, confidence, and evidence.

## 3. Execution Modes

### 3.1 Stable Regression (`stable`)

Default mode for daily regression and release gates.

- Resolve semantic targets locally in this order:
  `testid -> role/name -> label -> placeholder -> text -> saved selector`.
- Use Playwright auto-waiting and deterministic assertions.
- Do not call the model during normal successful execution.
- If self-healing is enabled, one bounded AI recovery is allowed after deterministic
  resolution fails.
- A healed locator is stored as a candidate, not automatically promoted to the case.

### 3.2 Adaptive Execution (`adaptive`)

For frequently changing pages and variable test environments.

- Resolve every semantic target against the current accessibility/DOM snapshot.
- Deterministic resolution is attempted first.
- AI may select among current-page candidates when the target is ambiguous or missing.
- The action is still executed by Playwright.
- A maximum of one AI resolution and one retry is allowed per checkpoint.
- Pass/fail remains based on saved assertions.

### 3.3 Autonomous Exploration (`explore`)

For feature discovery, smoke exploration, and candidate test generation.

- Input is a goal, scope, maximum steps, and prohibited actions.
- The agent repeats: observe, decide, act, verify, and record.
- Navigation is restricted to approved origins.
- Destructive actions are blocked unless explicitly permitted.
- Output contains trajectory, findings, screenshots, and candidate assertions.
- Exploration does not pass a release gate and does not mutate the saved case.

### 3.4 Visual Testing (`visual`)

For visual appearance that DOM assertions cannot prove.

- Captures a screenshot at the visual checkpoint.
- A multimodal model evaluates only the saved visual expectation.
- The result includes verdict, confidence, observations, and screenshot evidence.
- Low-confidence or unavailable-model results are `REVIEW`, not silent success.
- URL, text, and data correctness continue to use deterministic assertions.

## 4. UI Case Contract

### 4.1 Case-level fields

| Field | Values | Purpose |
|---|---|---|
| `execution_mode` | `stable/adaptive/explore/visual` | Runtime strategy |
| `self_heal_enabled` | boolean | Allow bounded semantic recovery |
| `max_agent_steps` | 1-30 | Exploration action budget |
| `allowed_origins_json` | string array | Navigation safety boundary |
| `prohibited_actions_json` | string array | Safety constraints |
| `steps_json` | step array | Durable test intent and actions |
| `assertions_json` | assertion array | Saved pass/fail criteria |

### 4.2 Semantic target

Selector-based fields remain supported. New and AI-generated cases should prefer:

```json
{
  "target": "登录按钮",
  "locator": {
    "strategy": "role",
    "role": "button",
    "name": "登录",
    "test_id": null,
    "label": null,
    "placeholder": null,
    "text": null,
    "selector": null
  }
}
```

The compact form is also valid:

```json
{
  "target": "登录按钮",
  "role": "button",
  "accessible_name": "登录",
  "selector": "[data-testid=login]"
}
```

The selector is a fallback. It is not required when a semantic target or semantic
locator is present.

### 4.3 Visual assertion

```json
{
  "type": "visual",
  "name": "登录页布局",
  "target": "登录表单",
  "value": "登录表单完整可见，输入框和登录按钮没有遮挡"
}
```

## 5. Runtime Pipeline

```text
Load case and environment
  -> enforce origin and safety policy
  -> open isolated browser context
  -> build checkpoints
  -> resolve semantic target
  -> execute with Playwright
  -> capture screenshot and structured step evidence
  -> on failure: bounded AI recovery when allowed
  -> execute deterministic or visual assertion
  -> persist trace, screenshots, recovery candidates, and summary
```

## 6. Semantic Resolution

Resolution is deterministic before it is model-assisted.

1. `data-testid`
2. ARIA role and accessible name
3. Form label
4. Placeholder
5. Visible text
6. Explicit selector fallback

The resolver checks uniqueness and visibility. Ambiguous matches are not clicked
silently. Adaptive mode can ask the model to select from a compact list of visible,
interactive candidates.

## 7. Self-Healing

When a target cannot be resolved:

1. Save the failed locator and screenshot.
2. Capture a compact accessibility/interactive-element snapshot.
3. Ask the model to choose one candidate from the supplied list or explicitly return
   `no_match`.
4. Validate that the returned candidate exists, is visible, stays in the allowed
   page/origin, supports the requested action, and does not conflict with the target's
   business meaning. For example, a search field cannot heal to a username field and a
   query button cannot heal to a login button.
5. Retry the original action once.
6. Record a `locator-healing.json` artifact.

Healing candidates have the states `suggested`, `used`, `rejected`, and `approved`.
The first implementation records candidates in run evidence. Promotion into the saved
case remains a user action.

## 8. Evidence

Every run can produce:

- Per-checkpoint screenshots.
- Full-page success or failure screenshot.
- Playwright trace.
- Structured step results.
- Semantic locator selected for each step.
- AI healing candidates and confidence.
- Exploration trajectory and findings.
- Visual review report.
- Console and network diagnostics when available.

The UI shows whether a step used deterministic location, selector fallback, AI healing,
or visual review.

## 9. Safety

- Only `http` and `https` targets are accepted.
- Navigation is limited to target/project/explicitly allowed origins.
- Exploration blocks delete, purchase, payment, publish, send, and permission-changing
  actions by default.
- Credentials come from environment variables/templates and are not sent to the model.
- AI receives a compact page snapshot, never stored secrets or unrestricted page HTML.
- AI output selects from server-generated candidate IDs; it cannot return JavaScript.
- Model unavailability cannot turn a failed deterministic assertion into success.
- Missing result text is reported as an assertion failure with the current page URL.
  Browser navigation timeouts remain execution timeouts, so product failures stay
  distinct from runtime infrastructure failures.

## 10. UI Experience

The default creation path is goal-first and uses progressive disclosure:

1. The user selects a project, enters the target URL, and describes the test goal.
2. Runtime mode, additional context, and the step budget remain under Advanced
   settings and use safe defaults.
3. The generated draft stays in the AI composer instead of opening the engineering
   editor immediately.
4. Operations are presented as a readable step timeline and assertions as explicit
   pass conditions.
5. The user can save the draft, open the advanced editor, or save and start a trial
   run directly.
6. Save and trial run performs the deterministic backend precheck before dispatching
   browser execution.

The advanced UI Case editor continues to provide:

- Execution mode segmented control.
- Self-healing toggle for stable/adaptive modes.
- Semantic target fields with optional advanced selector fallback.
- Exploration limits and prohibited actions.
- Visual assertion type.
- Run details showing resolution method and healing/visual evidence.

Existing selector-only cases continue to display and execute.

The UI Case list is ordered newest first and displays a continuous descending sequence
number across pagination. Filtering recalculates the visible sequence while preserving
newest-first order.

Run details show the concise failure summary and failed checkpoint by default. Raw
tracebacks remain available under the collapsed `Technical details` section for
troubleshooting, so implementation stack traces do not dominate the normal workflow.

## 11. Implementation Status

| Capability | Status |
|---|---|
| Existing fixed-selector execution | Complete |
| AI draft generation Skill | Complete |
| Execution mode contract | Complete |
| Semantic locator resolver | Complete |
| Bounded AI self-healing | Complete |
| Autonomous exploration | Complete |
| Visual assertion | Complete |
| Goal-first AI composer and draft preview | Complete |
| Save and trial-run creation path | Complete |
| Advanced mode and semantic editor | Complete |
| Evidence presentation | Complete |
| Container integration verification | Complete |

### 11.1 Current operational boundary

- Stable semantic execution is verified end to end without a model call.
- Adaptive recovery, exploration, and visual review use the active workspace model.
- The configured model must support JSON responses; visual review additionally requires
  image input support.
- A healing candidate is retained in run evidence and is not automatically written back
  to the saved case.
- Exploration output is explicitly marked as not eligible for release gating.
- On Docker Desktop, the execution worker uses `LOCAL_UID` and `LOCAL_GID` (defaults
  `501:20`) so screenshots and traces remain writable in the bind-mounted reports
  directory. Other hosts can override these values before starting Compose.

## 12. Acceptance Criteria

1. A legacy selector-only case runs unchanged.
2. A stable semantic case executes without a model call when the semantic target exists.
3. Adaptive mode can recover one changed locator and records the candidate.
4. A failed hard assertion cannot be changed to success by AI.
5. Exploration stays inside allowed origins and returns findings plus trajectory.
6. Visual mode returns `PASS`, `FAIL`, or `REVIEW` with screenshot evidence.
7. Run details identify the resolution method for every actionable checkpoint.
8. Backend tests, frontend tests/build, container health, and browser smoke tests pass.
9. A first-time user can generate a draft with only project, URL, and test goal.
10. Advanced runtime settings are hidden by default but remain editable.
11. The generated step preview can be saved, opened in the advanced editor, or saved
    and dispatched for a trial run.

## 13. Change Log

### 2026-07-22

- Redesigned AI creation into a two-step goal-first composer: describe the goal, then
  review generated operations and pass conditions.
- Moved runtime mode, context, and maximum-step controls into collapsed Advanced
  settings while preserving the existing execution contract.
- Added direct `save`, `advanced edit`, and `save and trial run` actions from the draft
  preview; trial runs execute the existing backend precheck before dispatch.
- Refined the UI Case overview hierarchy, summary indicators, primary action, table
  treatment, and responsive AI composer layout.
- Upgraded `ui-case-designer` to v2.0.1.
- Strengthened the `ui-case-designer` contract so value-bearing steps and assertions
  explicitly require a non-empty `value`.
- Added deterministic draft normalization: missing `wait_for_text`, `assert_text`, and
  text-assertion values can be completed from `text` or the case-level `expect_text`.
- Added user-facing validation messages when a required value cannot be safely inferred,
  instead of exposing a raw Pydantic validation trace.

### 2026-07-21

- Added verified AI Skill example UI case `#14` for `https://example.com`.
- Verified stable semantic execution end to end as run `#26`: seven checkpoints,
  role/name resolution, per-step screenshots, success screenshot, and Playwright trace.
- Confirmed that an out-of-origin AI healing candidate is rejected by the navigation
  safety boundary rather than being clicked or treated as success.
- Updated URL/title assertions for the current Python Playwright keyword-only `arg`
  contract and added regression coverage.

### 2026-07-20

- Established the AI UI testing product and technical baseline.
- Defined stable, adaptive, explore, and visual modes.
- Defined semantic location, bounded healing, evidence, and safety contracts.
- Added persistent mode, safety, and agent-budget fields with automatic database
  bootstrap migration.
- Upgraded `ui-case-designer` to v2.0.0 and semantic target output.
- Implemented deterministic semantic resolution, bounded candidate-only AI healing,
  safe autonomous exploration, and multimodal visual assertions.
- Added frontend mode controls, semantic target editing, mode badges, and runtime
  evidence.
- Verified a selector-free semantic case end to end as UI case `#13`, execution `#23`.
- Fixed Docker Desktop report-directory ownership for the execution worker.
