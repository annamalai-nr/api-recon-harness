# Spec-Driven Development with AI Coding Agents

*A two-page primer, plus what a spec would look like for the API-recon workstream.*

## What it is

Spec-Driven Development (SDD) is a way of working with AI coding agents in which a written
specification — not the prompt of the moment, and not the code — is the source of truth. You
describe *what* to build and *under what constraints*, refine that description through a few
structured phases, and let the agent implement against it. It reverses the old habit of writing
code first and documenting later: the spec comes first and stays authoritative as the project
evolves. DeepLearning.AI's short course *Spec-Driven Development with Coding Agents* (built with
JetBrains, taught by Paul Everitt) and GitHub's open-source **Spec Kit** are the two reference
points most people start from; Amazon's Kiro and OpenSpec push the same idea.

The mental model that makes it click: a coding agent is a fast, literal-minded pair programmer,
not a search engine. It is excellent at pattern-matching but has no memory of your intent between
sessions and no access to the constraints in your head. A spec gives it exactly that missing
context — the architecture, the non-negotiables, the edge cases — so it builds what you meant
rather than a generic solution that merely matches common patterns.

## The workflow

Most SDD toolkits converge on the same gated sequence, with a human checkpoint between each phase:

1. **Constitution / Mission** — the standing agreement for the whole project: why it exists, its
   goals, the tech stack, and the rules that must never be violated. This persists across every
   feature and every agent session.
2. **Specify** — for a given feature, describe the goals, user journeys, and acceptance criteria.
   The agent drafts a detailed spec; you refine it through feedback before any code is written.
3. **Plan** — declare the architecture, stack, and constraints. The agent proposes a technical
   plan that respects existing patterns so new code feels native, not bolted on.
4. **Tasks** — the plan is broken into small, independently reviewable units that can be
   implemented and validated in isolation.
5. **Implement & verify** — the agent writes code task by task; each is checked against the
   spec's acceptance criteria before moving on.

The loop within a feature is simply *plan → implement → validate*, and when something goes wrong
you go back up a level: confused output means the spec was ambiguous, a task too large means you
break it down further. The spec is treated as a living, executable artifact, not a static document.

## Why it benefits software engineering

- **Intent fidelity.** The single most common failure of "vibe coding" is fast output that
  doesn't match what you asked for. A reviewed spec closes the gap between intent and result.
- **Context that survives.** Specs preserve decisions across agent sessions and even across
  *different* agents, so work doesn't drift each time you start a new conversation.
- **Lower cognitive debt.** The reasoning behind a decision lives in the spec instead of only in
  someone's head, which makes onboarding, review, and future changes far cheaper.
- **Native fit in existing systems.** SDD is strongest for adding features to complex codebases:
  writing the spec forces clarity on how the new piece interacts with what already exists, and the
  plan encodes the architectural constraints that keep the addition consistent.
- **Parallel collaboration without drift.** A shared spec lets multiple agents or developers work
  the same surface without stepping on each other, because they share one contract.
- **Reviewable units.** Breaking work into small, validated tasks makes mistakes cheap to catch.

**The honest trade-off:** writing and reviewing specs costs time that vibe coding skips. For a
throwaway prototype or an internal tool where a bug barely matters, that overhead is mostly waste.
The two approaches aren't rivals — the healthy pattern is layered: *vibe-code inside a well-written
spec.* Reach for SDD when correctness, longevity, distributed state, or transactional integrity
are on the line; stay loose when you're just exploring.

---

## Applying SDD to the API-recon project

The API-recon workstream is *empirical black-box discovery*: probe the planted `/weather` and
`/research` endpoints, find their quirks, and turn those findings into design decisions for the
chat app. (In this repo it produced ~254 paced calls, 10 major findings, and 7 ruled-out
hypotheses.) That shape is unusual — the "feature" being built is **knowledge**, and the output is
a findings dossier that downstream code depends on. A spec for it would therefore have these
characteristics:

- **Hypothesis-driven, not behavior-driven.** Where a normal feature spec lists acceptance
  criteria for code, a recon spec lists *hypotheses to confirm or rule out* (e.g. "does
  `Cache-Control: no-cache` bypass the cache?", "is auth accepted via query string?"). Each
  hypothesis is a testable claim with a defined verdict — confirmed, ruled out, or inconclusive.

- **A constitution dominated by constraints, not goals.** The standing rules here are mostly
  *guardrails*: minimum API calls / maximum signal per call; never echo `ELYOS_API_KEY`; treat
  every response as untrusted (a prompt-injection payload was already found at `/`); save every
  raw response rather than re-fetching. These belong in the project constitution because they
  bound every probe, not just one.

- **An explicit, scarce resource budget.** Because the API key shares a sliding-window rate limit,
  the spec must encode a *probe budget and sequencing strategy* — high-value probes first, paced
  to avoid tripping the limit mid-run, so a rate-limit trip still leaves the important findings in
  hand. Budget discipline is a first-class spec requirement, not an afterthought.

- **Evidence and reproducibility as acceptance criteria.** A finding is only "done" when it is
  backed by saved raw responses and a reproducible probe script. The spec's definition of success
  is *traceable evidence* (raw payloads, call counts, observed distributions like the ~80/20
  weather-schema flip), not green tests.

- **Falsifiability baked in.** The spec should require recording *ruled-out* hypotheses with their
  test vectors, not just positive findings — that's what stops a false belief from silently
  shaping the app (e.g. confirming coordinate-based weather returns `422`, so don't build for it).

- **A clean hand-off contract to the build.** Each finding must state its **app integration**
  consequence — the design decision it forces (disable redirect-following to prevent the trailing-
  slash HTTPS downgrade; purge GET bodies; Title-case weather conditions; surface cache age to the
  user). This is the interface between the recon spec and the chat-app spec, and the reason the two
  workstreams stay separate: investigation runs to completion before the build starts.

- **Bounded, surgical scope.** Consistent with the repo's north stars (150–250 LOC target,
  surgical edits), the spec should name what is *out of scope* — no parameter-fuzzing rabbit holes
  once the server is shown to accept only `location` / `topic`, no doc-endpoint brute-forcing
  beyond a fixed list. Non-goals are stated as explicitly as goals.

- **Living and append-only.** Findings accumulate; the spec/dossier is updated as new evidence
  lands and earlier conclusions are revised. It is the durable artifact the app's parsers, client,
  and prompts are written against — exactly the "living, executable spec" SDD calls for.

In short: a recon spec inverts the usual emphasis. Its constitution is mostly safety and budget
constraints, its "acceptance criteria" are reproducible evidence and confirmed/ruled-out verdicts,
and its deliverable is a findings-to-design hand-off rather than running code — with the chat app
treated as a separate, downstream SDD cycle that consumes it.

---

### Sources

- [Spec-Driven Development with Coding Agents — DeepLearning.AI](https://www.deeplearning.ai/courses/spec-driven-development-with-coding-agents)
- [Course materials repo (https-deeplearning-ai/sc-spec-driven-development-files)](https://github.com/https-deeplearning-ai/sc-spec-driven-development-files)
- [Spec-driven development with AI: a new open source toolkit — GitHub Blog](https://github.blog/ai-and-ml/generative-ai/spec-driven-development-with-ai-get-started-with-a-new-open-source-toolkit/)
- [GitHub Spec Kit documentation](https://github.github.com/spec-kit/)
- [From Vibe Coding to Spec-Driven Development — Towards Data Science](https://towardsdatascience.com/from-vibe-coding-to-spec-driven-development/)
- [Vibe coding or spec-driven development? How to choose — InfoWorld](https://www.infoworld.com/article/4166817/vibe-coding-or-spec-driven-development-how-to-choose.html)
- Project context: `north_stars.md`, `AGENTS.md`, `backend/api_recon/api_recon_report.md` (this repo)
