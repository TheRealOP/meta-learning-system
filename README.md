# Meta-Learning System

A dead-simple AI learning assistant. Two knowledge layers in one folder:

```
knowledge/                    ← AKMS knowledge graph (agents read + write)
  ├── graph/                  ← Structured, agent-curated knowledge nodes
  ├── vault/                  ← Your Obsidian vault (you write, agents read)
  ├── archives/               ← Retired knowledge
  └── logs/                   ← Conversation logs
```

**Your vault lives inside the knowledge graph.** Agents can read your notes for context. You write in Obsidian as usual. AKMS manages the structured graph around it.

---

## Setup

### 1. Install AKMS

```bash
cd akms && pip install -e . && cd ..
```

### 2. Configure

```bash
cp akms_config.yaml.example akms_config.yaml
# Edit akms_config.yaml — add your API key(s)
```

You only need **one** API key (or Ollama running locally with no key at all):

```yaml
providers:
  ollama:
    base_url: "http://localhost:11434"
    models: [llama3.3]

agent_assignments:
  expert:    { provider: ollama, model: llama3.3 }
  librarian: { provider: ollama, model: llama3.3 }
```

### 3. Initialize

```bash
akms init
```

### 4. Point Obsidian at the vault

Open Obsidian → "Open folder as vault" → select `knowledge/vault/`.

Or if you have an existing vault, symlink it:

```bash
ln -s ~/path/to/your/existing/vault knowledge/vault
```

---

## How It Works

```
You ──── Obsidian ──── knowledge/vault/     (your notes, your ideas)
  ↓                           ↑ agents read 
Agent ── akms CLI ──── knowledge/graph/     (structured knowledge nodes)
                              ↑ agents read + write
```

1. **You** take notes in `knowledge/vault/` using Obsidian
2. **Agents** read your vault notes for context when answering questions
3. **Agents** use `akms` commands to search, query, and grow the structured graph
4. **The Librarian** can ingest your vault notes into the graph: `akms ingest knowledge/vault/my-note.md`
5. Over time, the graph gets richer — connecting your personal notes to structured knowledge

---

## Usage

### Ingest a vault note into the graph

```bash
akms ingest knowledge/vault/distributed-systems.md
```

### Search across the graph

```bash
akms search "consensus algorithms"
```

### Ask an expert

```bash
akms ask "distributed-systems" "How does Raft handle leader election?"
```

### Read your vault notes (for agents)

Agents read vault files directly — they're just markdown:

```bash
cat knowledge/vault/my-note.md
ls knowledge/vault/
```

### See what the graph knows

```bash
akms sections
akms get distributed-systems/raft
```

---

## For AI Agents

**Read `agents.md`** — it has full instructions on how to use both the vault and the knowledge graph.

Key rules:
- **Read the vault** before answering domain questions — the user's notes have context
- **Use `akms` commands** to search and query the structured graph
- **Only write to the vault when explicitly asked** — otherwise, it is the user's space
- **Ingest vault notes** into the graph when they contain learnable knowledge
