# Sandai AI Bot for openSUSE/osc

Welcome to the automated agent workflow for `openSUSE/osc` powered by **Sandai**.

This guide explains how contributors can trigger the bot, review and iterate on pull requests, forward changes upstream to `openSUSE/osc`, and tweak the agent's configuration.

---

## 1. Why a Dedicated `sandai` Branch?

The `sandai` branch is an isolated branch storing Sandai automation files (`sandai.yaml`, prompt templates, helper scripts, and documentation).

Because Sandai reads its configuration directly from this branch via Git plumbing (`git cat-file`), **no Sandai files or configurations are present on `master` or feature branches**. When the bot solves an issue, the generated Pull Request is 100% clean and contains only the code fixes and tests ready for upstream review.

---

## 2. How to Use the Bot

### A. Requesting a Fix or Feature via Issues

Open an issue in the [`sandai-osc/osc`](https://github.com/sandai-osc/osc) fork repository and choose **either Option 1 or Option 2**:

#### Option 1: Reference an Existing / Upstream Issue (Recommended for upstream bugs)
If the bug or feature is already documented in an issue (such as upstream `openSUSE/osc`), there is no need to copy-paste details. Simply reference the issue and mention the bot:

```markdown
Title: Address openSUSE/osc#1425

Body:
@sandai-bot please investigate and fix openSUSE/osc#1425
```

The bot's issue discovery feature automatically fetches the referenced issue's title, description, and author context directly from GitHub to formulate the task requirements!

*(You can use `openSUSE/osc#<num>`, `#<num>`, or a full GitHub issue URL like `https://github.com/openSUSE/osc/issues/<num>`).*

---

#### Option 2: Describe the Problem Directly (For new issues or custom tasks)
If you are reporting a new problem or custom task directly, describe the issue, error output, and requirements in the issue body, and include `@sandai-bot`:

```markdown
Title: Fix KeyError when reading package metadata in osc/core.py

Body:
Running `osc info` raises a KeyError when package metadata is missing.
Expected behavior: Return default empty metadata without crashing.

@sandai-bot please fix this issue and add a regression test.
```

> **Trigger**: The bot triggers whenever a collaborator mentions `@sandai-bot`—either directly in the **issue description/title** when opening the issue, or in any subsequent **issue comment**.

### B. What the Bot Does

1. **Acknowledgment**: The bot posts an initial comment with a real-time progress checklist:
   - [x] Workspace preparation & repository clone
   - [ ] ⏳ **Executing Sandai agent inside isolated sandbox**
   - [ ] Discover generated branch & push to fork
   - [ ] Open Pull Request
2. **Sandbox Execution**: The agent runs inside an isolated rootless container (Podman with dropped capabilities and egress allowlists). It inspects the `osc` codebase, edits files, and runs verification guardrails (e.g. `pytest`).
3. **Pull Request**: Once guardrails pass, the bot pushes a branch (`sandai/sandai-run-<timestamp>`) and opens a Pull Request on `sandai-osc/osc` referencing the issue.

### C. Reviewing & Iterating on the Pull Request

If the bot's proposed implementation needs adjustments:
1. Comment directly on the Pull Request on GitHub and tag the bot:
   ```markdown
   @sandai-bot the fix looks good, but please also handle the case when --verbose is omitted.
   ```
2. The bot will:
   - Fetch your review comment and any referenced issues.
   - Check out the existing PR branch.
   - Perform another iteration inside the sandbox.
   - Commit and push changes directly to the existing PR branch.

### D. Forwarding to Upstream `openSUSE/osc`

Once you and fellow team members approve the Pull Request in the fork:
1. Click **Contribute** → **Open pull request** on GitHub.
2. Set the base repository to `openSUSE/osc` and base branch to `master`.
3. Submit the clean Pull Request upstream.

---

## 3. Customizing the Configuration (`sandai.yaml`)

Contributors with write access to the `sandai` branch can modify `sandai.yaml` to adjust models, timeouts, security policies, and test suites.

### Example `sandai.yaml` for `osc`

```yaml
version: "1"

orchestrator:
  # Maximum refinement loops the agent gets to make guardrails pass
  max_iterations: 3
  # Maximum time allowed per iteration
  timeout: "30m"
  # Set to true for non-interactive autonomous mode
  afk: true

agent:
  name: "gemini"
  model: "gemini-2.5-pro" # or gemini-2.5-flash for faster triage
  command: "gemini"

sandbox:
  provider: "podman"
  image: "localhost/ai-agents-sandbox-gemini:latest"

  security:
    cap_drop:
      - ALL
    no_new_privileges: true
    userns: "keep-id" # Maps host user to container user

  network:
    # strict drops container internet access except via local CONNECT proxy
    enforcement: "strict"
    allow_domains:
      - "github.com"
      - "api.github.com"
      - "pypi.org"
      - "files.pythonhosted.org"
      - "build.opensuse.org"
    allow_web_search: true

hooks:
  # Evaluated after each agent step. If this fails, the error output is fed
  # back to the agent for the next iteration until it passes.
  after_run:
    steps:
      - name: "ruff-check"
        command: "ruff check osc/"
        allow_failure: true # Don't block iteration on linter alone
      - name: "pytest"
        command: "pytest tests/"
        timeout: "10m"
```

### Key Configuration Fields:

- **`orchestrator.max_iterations`**: If tests fail on the first attempt, the agent inspects the test failure and tries again up to `max_iterations` times.
- **`agent.model`**: You can switch between `gemini-2.5-pro` (thorough code analysis) and `gemini-2.5-flash` (faster, lower latency).
- **`network.allow_domains`**: Egress whitelist. If tests or tools need to reach external hosts (such as OBS APIs or package mirrors), add their hostnames here.
- **`hooks.after_run`**: Defines the acceptance criteria. Any standard command (`pytest`, `make test`, `ruff check`) can be used.

---

## 4. Security Notice: GitHub Actions Workflow Restrictions

For security reasons, the bot's GitHub App authentication token **does not have permissions to modify workflow files** (`.github/workflows/*`).

- **Why this restriction exists**: Restricting workflow write permissions is a critical security safeguard. It ensures that automated AI agents cannot modify CI/CD pipelines, alter security checks, or access/exfiltrate repository secrets through modified Actions definitions.
- **Current Behavior**: If a requested task involves editing or creating files in `.github/workflows/`, GitHub will reject the bot's `git push` with a permission error (`refusing to allow an App to create or update workflow without workflows permission`).
- **Future Improvements**: This restriction is enforced intentionally at the moment. More granular or human-approved workflows for CI modifications might be introduced in future releases.
