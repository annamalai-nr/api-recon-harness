# Spec-Driven Development With AI Coding Agents

Spec-driven development (SDD) is a software engineering workflow where the durable source of truth is not the code or a chat transcript, but a written specification. In the AI-agent version of SDD, humans and agents collaborate to turn an idea into explicit requirements, design choices, implementation tasks, validation checks, and then code. The central shift is simple: instead of asking an agent to "build X" from a loose prompt, the team first writes down what X means, why it matters, how success will be judged, and what constraints the implementation must obey.

This is not entirely new. Traditional software teams have long used product requirement documents, design documents, acceptance criteria, and test plans. What is new is that modern coding agents can consume these artifacts directly and use them as operating context. In that setting, a spec is no longer only documentation for humans. It becomes an executable guide for an agent: it shapes planning, file edits, tests, review, and future changes.

## The Core Idea

DeepLearning.AI's short course, *Spec-Driven Development with Coding Agents*, frames SDD as a disciplined alternative to "vibe coding." Vibe coding is fast and useful for exploration, but it often relies on short prompts, implicit assumptions, and the agent's guesses about the product. SDD replaces that with a clear Markdown spec, a project constitution, and a repeatable plan-implement-verify workflow. The course emphasizes that specs preserve context across agent sessions, improve intent fidelity, and reduce cognitive debt.

GitHub's Spec Kit describes the same principle as putting specifications at the center of AI-assisted development. Its default workflow is:

1. **Spec**: describe what to build, including user stories, acceptance criteria, and non-goals.
2. **Plan**: translate the spec into architecture, technology choices, data models, API contracts, and risks.
3. **Tasks**: break the plan into small, trackable implementation steps.
4. **Implement**: let the coding agent execute those tasks while checking against the spec.

Kiro, an agentic AI IDE, expresses the workflow with three core files: `requirements.md`, `design.md`, and `tasks.md`. Requirements capture user stories and acceptance criteria. Design captures architecture, sequence diagrams, data flow, error handling, and test strategy. Tasks convert the design into discrete units of implementation that can be run one by one or in dependency-aware batches.

The practical theme across these tools is that SDD gives the agent structured context. The agent does not need to infer everything from the current prompt or from a partial scan of the repository. It has an explicit map of user intent, engineering decisions, and completion criteria.

## What A Good Spec Contains

A useful AI-era spec is not a long essay. It is a compact engineering artifact that is precise enough to guide code generation and review. Good specs usually include:

- **Problem and goal**: what user or business problem is being solved.
- **Scope and non-scope**: what is included, what is explicitly excluded, and what should not change.
- **User stories or workflows**: concrete examples of how the feature will be used.
- **Acceptance criteria**: observable behavior that proves the feature works.
- **Data and interfaces**: inputs, outputs, API contracts, database changes, events, or CLI behavior.
- **Constraints**: security, performance, accessibility, compatibility, cost, compliance, or team conventions.
- **Validation plan**: tests, manual checks, and edge cases.
- **Implementation tasks**: small, ordered steps that can be reviewed independently.

The best specs also include uncertainty. If a requirement is ambiguous, the spec should mark it as an open question instead of silently choosing an answer. This is especially important with coding agents because they are good at producing plausible code for the wrong interpretation.

## How It Benefits Software Engineering

**1. Better alignment between intent and code**

The main benefit is intent alignment. Coding agents are powerful translators, but they still need a clear source language. A spec makes the desired behavior explicit before implementation begins. This reduces the risk that the agent optimizes for the nearest plausible interpretation rather than the actual product need.

**2. More controlled use of agents**

SDD changes the developer's role from prompt-by-prompt micromanagement to structured supervision. The human sets direction, reviews the spec, approves the plan, and inspects task-level changes. The agent keeps momentum by drafting artifacts, generating code, and running checks. This is a better control model for complex work than asking for a whole feature in one shot.

**3. Persistent context across sessions and tools**

Agent conversations are temporary and can drift. Specs live in the repository. They can be version-controlled, reviewed in pull requests, reused by different agents, and updated as the system changes. This matters when work spans days, when agents are switched, or when a new team member needs to understand why the code exists.

**4. Smaller, reviewable changes**

Breaking a plan into tasks naturally encourages smaller patches. Each task can point back to a requirement and a design decision. That traceability makes code review sharper: reviewers can ask, "Does this change satisfy the acceptance criterion?" instead of reverse-engineering intent from the diff.

**5. Better testing and validation**

Acceptance criteria and edge cases can become tests or manual validation steps. In mature SDD workflows, test scenarios are not an afterthought; they are derived from the same spec that drives implementation. This is useful for both feature work and bug fixes. Kiro's bugfix specs, for example, capture current behavior, expected behavior, and unchanged behavior so fixes do not create regressions.

**6. Lower cognitive debt**

Cognitive debt is the hidden cost of decisions that only exist in someone's memory or in a long agent chat. SDD writes those decisions down: why a design was chosen, what constraints mattered, what was deferred, and how success was defined. This makes future changes cheaper because the next engineer or agent starts from a maintained record rather than a guessing exercise.

**7. Safer handling of security and compliance**

Security requirements can be placed in the spec or in a project constitution before code is generated. Recent research on "constitutional" SDD argues that embedding non-negotiable security rules into the specification layer can reduce security defects compared with unconstrained AI generation. Even if a team does not adopt a formal constitution, writing constraints such as "never log secrets," "validate all external input," or "preserve tenant isolation" gives agents and reviewers concrete rules to enforce.

## Where SDD Helps Most

SDD is most valuable when the work has meaningful complexity: new product features, cross-file refactors, public APIs, data model changes, compliance-sensitive systems, or bug fixes where regressions would be expensive. It also helps in existing codebases because specs can force the agent to inspect current behavior and align with local architecture before editing.

It is less useful for trivial changes, one-line fixes, throwaway experiments, or early ideation where the goal is deliberately unclear. In those cases, lightweight prompting or "vibe" exploration may be faster. A pragmatic team should choose the amount of specification based on risk. The point is not ceremony; the point is enough structure to make agentic development predictable.

## Risks And Failure Modes

SDD can fail if specs become stale, too verbose, or detached from the actual code. A large spec that nobody maintains is just another documentation burden. It can also over-constrain the agent: if the design is wrong but the agent is told to follow it blindly, the output may be consistently wrong. The workflow needs feedback loops. When implementation reveals a missing edge case, the right move is often to update the spec, plan, or task list before continuing.

Another risk is context blindness. A spec may describe the desired feature, but the agent still needs repository evidence: existing APIs, architectural patterns, dependencies, and tests. Emerging work on context-grounded SDD adds read-only probing and validation hooks at each phase so agents do not hallucinate unavailable APIs or violate local conventions.

## Bottom Line

Spec-driven development is a way to make AI-assisted software engineering more deliberate. It turns the spec into the shared contract between humans, agents, code, and tests. For developers, the benefit is not that the agent writes more code; it is that the agent writes code against a clearer target. Done well, SDD improves alignment, reviewability, continuity, testability, and institutional memory. Done poorly, it becomes stale documentation. The practical standard is therefore lightweight but rigorous: write just enough spec to make the next implementation step unambiguous, validate against it, and update it when reality teaches you something new.

## Sources

- DeepLearning.AI: [Spec-Driven Development with Coding Agents](https://www.deeplearning.ai/courses/spec-driven-development-with-coding-agents)
- GitHub Spec Kit docs: [GitHub Spec Kit](https://github.github.io/spec-kit/)
- GitHub Spec Kit repository: [What is Spec-Driven Development?](https://github.com/github/spec-kit)
- GitHub Spec Kit philosophy: [Specification-Driven Development](https://github.com/github/spec-kit/blob/main/spec-driven.md)
- Kiro docs: [Specs](https://kiro.dev/docs/specs/)
- Kiro docs: [Specs Best Practices](https://kiro.dev/docs/specs/best-practices/)
- JetBrains Junie Blog: [How to Use a Spec-Driven Approach for Coding with AI](https://blog.jetbrains.com/junie/2025/10/how-to-use-a-spec-driven-approach-for-coding-with-ai/)
- arXiv: [Spec-Driven Development: From Code to Contract in the Age of AI Coding Assistants](https://arxiv.org/abs/2602.00180)
- arXiv: [Constitutional Spec-Driven Development](https://arxiv.org/abs/2602.02584)
- arXiv: [Spec Kit Agents: Context-Grounded Agentic Workflows](https://arxiv.org/abs/2604.05278)
