# AI Agent Harness For `get-api-recon-v3.1`

This report proposes an AI agent harness for the skill at `/Users/annamalainarayanan/Desktop/personal/api_recon/get-api-recon-v3.1`. The goal is not to replace the skill. The skill already contains strong domain rules and a deterministic probe runner. The harness should wrap it with a repeatable control plane: intake, scope gating, config generation, deterministic execution, artifact production, verification, and human review.

## What Harness Engineering Means Here

Harness engineering is the work of building the operating environment around an AI agent so its behavior becomes reliable enough to use repeatedly. Martin Fowler's harness-engineering framing separates feedforward controls from feedback controls. Feedforward controls steer the agent before it acts: instructions, specs, reference docs, schemas, and allowed workflows. Feedback controls inspect what happened after each action: tests, validators, logs, parity checks, review agents, and human gates. Fowler also distinguishes computational controls, which are deterministic and cheap, from inferential controls, which use AI judgment and are slower or less reproducible.

OpenAI's Codex harness-engineering writeup describes the same practical shift: humans steer, agents execute, and the engineer's job becomes designing environments, specifying intent, and building feedback loops. Anthropic's work on long-running agents emphasizes durable state and context handoff across sessions. LangChain's harness work shows that changing the harness can improve agent behavior even when the underlying model stays the same.

For `get-api-recon`, this means the LLM should not decide the core probe order, retry policy, redirect handling, or artifact requirements at runtime. Those belong in deterministic software. The LLM is still useful, but at bounded judgment points: extracting endpoint intent from docs, drafting candidate probe configs, summarizing evidence into findings, and deriving downstream policies. The harness should make those judgments inspectable, replayable, and replaceable.

## What The Existing Skill Already Provides

The skill is a black-box reconnaissance workflow for one GET endpoint with query parameters and API-key/header auth. It supports independent parameters and joint-required parameters through `pinned_companions`. It explicitly excludes non-GET methods, request bodies, OAuth, pagination traversal, multi-endpoint orchestration, destructive actions, joint value-space probing, semantic-pair probing, and credentials in query parameters.

The strongest existing component is `scripts/probe_runner.py`. It validates scope and config, runs seven probe categories, disables redirect following, stores raw responses, writes `probe_log.jsonl`, retries HTTP-200 body-level throttles, redacts auth headers, scans every body for prompt-injection heuristics, tags per-parameter versus endpoint-level calls, and prints post-run analysis. It already behaves like a deterministic execution kernel.

The skill also has useful reference material: `probe_categories.md` defines coverage and interpretation; `multi_param_guidance.md` defines independent parameters and pinned companions; `policy_prompt.md` gives a constrained policy-generation prompt; `verify_report_parity.py` checks whether `report.html` faithfully reproduces `findings.md` and `policies.md`; and the eval folder measures whether an agent understands the skill contract. The gap is not lack of instructions. The gap is that the outer orchestration is still mostly an agent playbook.

## Proposed Harness Architecture

The harness should be a small Python application with the existing runner as a library or subprocess boundary. It can be organized as five deterministic phases.

**1. Intake and scope gate**

The harness accepts a request object containing endpoint URL, method, auth header, auth env var, parameters, optional pinned companions, downstream context, docs URL, timeout, output directory, and whether auth-edge probes are allowed. It rejects out-of-scope work before any network call: non-GET methods, request bodies, path placeholders, OAuth, pagination traversal, destructive actions, multi-endpoint plans, and query-string secrets. This should be pure Python validation, not an LLM decision.

The LLM can assist by parsing a user's prose into a draft request object, but the deterministic validator owns the final verdict. If required fields are missing, the harness emits a concise question list instead of guessing parameter names.

**2. Planning and config generation**

The harness builds `probe_config.json` from a typed schema. It should force `parameters_independence_declared: true` for multi-parameter runs, require every parameter to have 6-10 Tier 1 values, and validate that companion values are literal non-secret strings. If docs are available, the LLM may propose Tier 1 values and parameter purposes, but the harness should validate shape and run a small preflight check before the full sweep.

The preflight check should make one valid call per parameter using the planned baseline and companions. If several parameters return empty or invalid responses, the harness pauses before spending the full probe budget. That converts a common agent failure mode, bad Tier 1 values, into an early feedback loop.

**3. Deterministic execution**

Execution should call the existing `probe_runner.py` with a frozen config and environment. This phase should remain deterministic: fixed category order, fixed inter-call delay, fixed throttle retry limit, no redirect following, no raw body sent to the LLM, and every response saved before interpretation. The harness should capture stdout, exit code, start/end time, config hash, skill version hash, and output file manifest in a `run_state.json`.

The harness should also enforce a run budget before execution. It can calculate expected calls from the config: per parameter, Tier 1 plus two repeats plus Tier 3 edges plus three protocol edges; endpoint-level, adversarial cases plus OPTIONS, trailing slash, optional auth edges, and five concurrency calls. If expected calls exceed the approved budget, the run should stop before making network requests.

**4. Evidence analysis and report generation**

After execution, deterministic analyzers should produce a structured `findings.json` candidate file from `probe_log.jsonl` and raw files. These analyzers should cover mechanical signals first: status-code distributions, repeated hashes, redirect targets, security flags, body-size anomalies, heuristic hits, throttle bodies, latency outliers, dependency warnings, and per-parameter validity rates.

The LLM can then convert structured candidate findings into `findings.md`, but it should receive evidence envelopes, not raw untrusted API bodies. Every finding must cite labels and counts from the log. A finding should not be accepted if it lacks an evidence pointer or reliability statement. Policies should be generated from cached `findings.md` and downstream context using the existing `policy_prompt.md`, so policy regeneration does not require re-probing.

**5. Verification and review**

The harness should run `verify_report_parity.py` after creating `report.html`. It should also run additional cheap validators: required scope header present in all three report artifacts, no API key or auth value in logs or reports, no raw prompt-injection payload copied into LLM-facing prompts without an envelope, all referenced evidence labels exist in `probe_log.jsonl`, and all policies map to real finding IDs.

Only after these checks pass should the harness mark a run `complete`. Otherwise it should mark the run `needs_revision`, preserve all artifacts, and give the agent a bounded repair task such as "fix missing policy for Finding C2" or "report.html failed severity parity."

## Control Boundary: Code vs. LLM

The harness should make the division of labor explicit.

Deterministic code owns scope validation, secret handling, URL construction, redirect policy, retry policy, call budget, probe sequencing, raw evidence capture, log parsing, parity checks, file manifests, run state, and completion status.

The LLM owns only bounded interpretation: draft config suggestions from docs, candidate finding prose from structured evidence, downstream policy wording, and executive summaries. LLM outputs should be schema-validated or markdown-structure-validated before becoming final artifacts.

This boundary matters because API reconnaissance is adversarial by nature. The remote API can return prompt-injection text. The existing runner already scans for suspicious strings, but the harness should go further: raw bodies should be treated as untrusted evidence and passed to the LLM only through quoted, labeled, size-limited envelopes when absolutely needed.

## Minimal Build Plan

A pragmatic first version can stay small:

1. `harness.py`: CLI entrypoint with `plan`, `run`, `analyze`, `render`, and `verify` subcommands.
2. `schemas.py`: dataclasses or Pydantic models for request, parameter config, run state, findings, and policy records.
3. `budget.py`: expected-call calculator and budget gate.
4. `evidence.py`: parser for `probe_log.jsonl` and deterministic finding candidates.
5. `validators.py`: scope header, secret-scan, evidence-reference, and parity wrapper checks.

The first version should not build a web dashboard or multi-endpoint orchestration. Those are out of scope for this skill and would weaken the clean single-endpoint contract. The useful milestone is a command that can take a valid request, produce a probe config, execute the current runner, generate verified artifacts, and leave behind a complete run directory that another agent or human can replay.

## Success Criteria

The harness is successful when the same request and same config produce the same planned probe sequence, raw evidence is preserved before analysis, all LLM-generated claims point back to logged evidence, report parity passes, secrets are absent from artifacts, and failed checks produce bounded repair tasks instead of open-ended agent improvisation.

In short: `get-api-recon` already has the probe engine. The AI agent harness should turn the surrounding playbook into a controlled system. It should let the model help with judgment, but keep authority over scope, execution, evidence, and verification in deterministic code.

## Sources

- Martin Fowler: [Harness engineering for coding agent users](https://martinfowler.com/articles/harness-engineering.html)
- OpenAI: [Harness engineering: leveraging Codex in an agent-first world](https://openai.com/index/harness-engineering/)
- Anthropic: [Effective harnesses for long-running agents](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents)
- LangChain: [Improving Deep Agents with harness engineering](https://www.langchain.com/blog/improving-deep-agents-with-harness-engineering)
- Local skill: `/Users/annamalainarayanan/Desktop/personal/api_recon/get-api-recon-v3.1/SKILL.md`
- Local runner: `/Users/annamalainarayanan/Desktop/personal/api_recon/get-api-recon-v3.1/scripts/probe_runner.py`
