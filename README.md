# aider-factory 🏭

⚠️ **Active Development:** This repository is currently being prepared for its official open-source release. Feel free to explore, star, and watch the repo as we finalize the initial stable version!



An industrial-grade, high-precision software engineering agent fabric and validation engine.

The AI Factory coordinates multi-model workflows, pre-edit debates, and test-driven self-healing loops to deliver provably correct, high-quality software changes.

## Prerequisites (One-Time System Setup)

To support vendor-free web research (`aider-research`), install Podman for 100% rootless, zero-sudo container execution:

```bash
# Ubuntu / Debian:
sudo apt install -y podman

# RHEL / Fedora / CentOS:
sudo dnf install -y podman
```

*(Note: Docker is also supported as a fallback if your user account belongs to the `docker` group: `sudo usermod -aG docker $USER`).*

## Quick Start (The 3-Step Basic Workflow)

To get to work instantly in any codebase, simply follow these three steps:

### Step 1: Install the AI Factory Globally

Choose one of the two installation methods below:

#### Method A: Standard Installation (Recommended for regular use)

This builds an isolated global sandbox directly from GitLab and registers the CLI commands:

```bash
uv tool install --force git+ssh://git@gitlab.com/bryanrod182/aider-factory.git
```

#### Method B: Editable Installation (Recommended for developers/contributors)

This clones the repository locally and symlinks it, allowing any code changes you make to be live instantly:

```bash
# Clone the repository
git clone git+ssh://git@gitlab.com/bryanrod182/aider-factory.git
cd aider-factory

# Install globally in Editable Mode
uv tool install --force --editable .
```

This registers four global commands on your system path:

- `aider-factory` — Standard workflow runner
- `aider-oracle` — Standalone RAG/Oracle CLI
- `aider-validate` — Deterministic quote/grounding validator
- `aider-research` — SearXNG web research agent CLI

---

### Step 2: Configure Your Cloud API Keys

The AI Factory uses environment variables to authenticate with cloud model providers. You can set them in one of two places:

#### Option A: Globally in your shell profile (Recommended)

Add these lines to the end of your `~/.bashrc` or `~/.zshrc` file so they are always active:

```bash
export GEMINI_API_KEY="AIzaSy..."
export OPENAI_API_KEY="sk-proj-..."
```

Then run `source ~/.zshrc` to reload.

#### Option B: Locally in a `.env` file

Create a local, git-ignored `.env` file at the root of your project:

```env
GEMINI_API_KEY=AIzaSy...
OPENAI_API_KEY=sk-proj-...
```

---

### Step 3: Initialize Your Project & Get to Work

Navigate to your target codebase and run `aider-factory` without arguments:

```bash
cd /path/to/your-project
aider-factory
```

On the first run, the tool will automatically bootstrap a 100% zero-clutter agent workspace:

- **At the project root:** A default `.aiderignore` file to protect your context window.
- **Inside `.aider_factory/`:** A default `.aider_factory/.env.yml` configuration template, alongside `.aider.conf.yml`, `.aider.model.settings.yml`, and `CONVENTIONS.md`.

Now, simply open `.aider_factory/.env.yml`, configure your target files and phases, and run:

```bash
aider-factory
```

The pipeline runs immediately!

---

## Global CLI Commands

### 1. `aider-factory [config_path]`

Runs the Directed Acyclic Graph (DAG) pipeline configured in the specified YAML file. Defaults to `.aider_factory/.env.yml` (and falls back to `.env.yml` at the project root).

### 2. `aider-oracle [options] "<question>"`

Queries your local LanceDB knowledge base using the Oracle side-agent.

- Ask a question: `aider-oracle "How does the caching system work?"`
- Start a debate: `aider-oracle --debate code "Should we refactor the DB layer?"`
- Maintain database: `aider-oracle --list-files` or `aider-oracle --rm-file document.pdf`

### 3. `aider-validate [options]`

Determines if quotes inside generated documents are verbatim substrings of the source material.

### 4. `aider-research search "<query>"`

Performs online metasearch via local SearXNG and renders Markdown research reports:
- Standard search: `aider-research search "Manitoba Basic Income experiment"`
- Academic search: `aider-research search "labor supply elasticity" --academic --top 10`
- File input: `aider-research search --file query.txt --academic --top 10`


---

## Legal Disclaimer

**aider-factory** is an independent, community-driven open-source project. This project is not affiliated with, sponsored by, endorsed by, or associated with:
* **Aider** (created by Paul Gauthier or the official Aider project).
* **Oracle Corporation** (or any of its subsidiaries, database products, or trademarks).

All product names, logos, and brands are property of their respective owners. All company, product, and service names used in this software and documentation are for identification purposes only. Use of these names, logos, and brands does not imply endorsement.
