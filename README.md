
# TPM Enterprise Command Center 🚀

[![Automated Tests](https://github.com/mrzeznic/pm_notes/actions/workflows/tests.yml/badge.svg)](https://github.com/mrzeznic/pm_notes/actions)

A high-velocity, markdown-driven Technical Project Management mission control dashboard built with **Python**, **NiceGUI**, and a **Hybrid AI Engine** (supporting **GitHub Copilot / Models API** and **Local Ollama LLMs**).

---

## ⚡ Quick Start

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Run the Dashboard
```bash
python main.py
```
Open your browser at **`http://127.0.0.1:8080`**.

---

## 🤖 Configuring AI Engines

### A. Using GitHub Copilot / Cloud AI
You can connect Copilot in two ways:
1. **GitHub Models API (Recommended)**:
   - Provide your `GITHUB_TOKEN` in the dashboard **Settings (⚙️)** or set it in your environment:
     ```bash
     export GITHUB_TOKEN="ghp_your_token_here"
     ```
   - Select your preferred cloud model (e.g. `gpt-4o`, `claude-3.5-sonnet`, `o1-mini`).
2. **GitHub CLI (`gh`) Fallback**:
   - If no token is provided, the app will automatically use the authenticated `gh copilot` extension CLI.

### B. Using Local Ollama
1. Start Ollama:
   ```bash
   ollama serve
   ```
2. Pull your desired model (default: `qwen2.5:7b`):
   ```bash
   ollama pull qwen2.5:7b
   ```
3. Set tool preferences in **Settings (⚙️)** to `local`.

---

## 📂 Architecture

```
tpm-command-center/
├── main.py                     # Entry point & NiceGUI server startup
├── requirements.txt            # Dependencies
├── tpm_defaults.json           # Default settings
├── core/
│   ├── config.py               # Config persistence & validation
│   ├── logger.py               # Live logging system
│   └── security.py             # Path validation & sanitization
├── models/
│   └── task.py                 # Structured Task & Project dataclasses
├── services/
│   ├── ai_engine.py            # Copilot API, Ollama HTTP, CLI fallback
│   ├── markdown_parser.py      # Resilient Markdown parser & serializer
│   └── project_service.py      # Atomic writes, backup creator, archiver
├── ui/
│   ├── styles.py               # Dark mode theme & diff styling
│   └── dashboard.py            # NiceGUI UI & interactive dialogs
├── projects/                   # Markdown project files
│   ├── Auth_Service/notes.md
│   └── Payment_Gateway/notes.md
└── tests/
    └── test_core.py            # Unit test suite
```

---

## 📝 Markdown Task Syntax

In each `notes.md` file:
* **Tasks**: `- [ ] Task title` or `- [x] Completed task`
* **Priority**: `#p1` (High, Red), `#p2` (Medium, Yellow), `#p3` (Low, Green)
* **Due Dates**: `@YYYY-MM-DD` (Overdue tasks flagged automatically)
* **Blockers & Dependencies**: `#blocked: Reason` / `#dep: Dependency`
* **Description**: Trailing text in parentheses `(Description...)`
* **Sections**: `## Tasks`, `## PROJECT SUMMARY`, `## ARCHIVE`

