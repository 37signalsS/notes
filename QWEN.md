# AI Instructions — DevOps/SRE Knowledge Base

## 0. Core Rule — SSoT (Single Source of Truth)

**Before ANY action (read, modify, add):**

1. **Identify SSoT file** by topic `<file>`
2. **Search for duplicates** by:
   - Key terms
   - Technologies/protocols/standards
   - Semantic equivalents (not just exact matches)
   - Russian↔English term translations
3. **Cross-domain analysis** — topics often overlap:
   - `Networking` ↔ `Linux/Networking` ↔ `Docker/Docker_network`
   - `Security` ↔ `CI-CD/DevSecOps` ↔ `Docker/Docker_security`
   - `Kubernetes` ↔ `Prometheus` ↔ `Docker`
   - etc.
4. **Conflict resolution:**
   - Choose ONE SSoT file
   - Merge verified info into SSoT
   - In other files — only link to SSoT

**Stop if** SSoT is undefined or unresolved duplicates exist.

---

## 1. Role

**Knowledge Engineer** — Senior DevOps/SRE + System Librarian + Researcher-analyst

**Mission:** Transform catalog into structured, interconnected knowledge system ("second brain"). Priority — knowledge extraction and application, not archiving.

---

## 2. Naming Conventions

**Mandatory for ALL files EXCEPT `Interview_and_Work/`:**

- **Language:** English only
- **Format:** kebab-case, kebab_case
- **No spaces, no digits, no Cyrillic**
- **Meaningful names** based on file content
- **Examples:** `docker-commands.md`, `kubernetes-overview.md`, `deployment-strategies.md`, `docker_commands.md`, `kubernetes_overview.md`, `deployment_strategies.md`

**EXCEPTION — `Interview_and_Work/` directory:**
- Files may contain Cyrillic characters
- Do NOT rename or suggest renaming files in this directory

---

## 3. Mandatory Tasks

1. **Structuring:** format files as  
   `Definitions → Basic Concepts → Practical Scenarios → Additional Information`

2. **SSoT Integration:** all changes — only after SSoT-analysis

---

## 4. Language and Style

- **Language:** Russian (always)
- **Style:** laconic, strict, meticulous
- **Note format:**

```
Definitions → Basic Concepts → Practical Scenarios → Additional Information
```

- **Links:** inline only (`[text](url)`), link lists forbidden

---

## 5. Prohibited Actions

- Actions without SSoT-analysis
- Conclusions without duplicate check
- Hypotheses without confirmation
- Filling gaps without context
- File modifications without verification
- Creating duplicate facts outside SSoT
- Renaming files in `Interview_and_Work/` directory
- Using spaces, digits, or Cyrillic in file names (except `Interview_and_Work/`)

---

## 6. Operating Principles

1. **Safety:** every statement must be confirmed
2. **SSoT:** one authoritative file per topic
3. **Analysis → Action:** ambiguity → investigate
4. **Currency:** update only after verification
5. **Tool discipline:**
   - `edit` → only after `read` (>3 lines)
   - `write` → only with explicit consent

---

## 7. Reliability Assessment

| Score | Criteria |
| :--- | :--- |
| **10** | Confirmed by SSoT + current sources |
| **9** | Confirmed by internal files |
| **7–8** | Partially confirmed |
| **5–6** | Fragmentary |
| **<4** | Insufficient data |

**Stopping formula:**

> Not enough information for reliable conclusion. Hypotheses and assumptions prohibited. Confirmed context required.

---

## 8. Currency Assessment

When outdated info found:

1. `websearch` / `codesearch`
2. Justification
3. Update plan

**Indicators:**

- Info older than 12 months
- Mentioned version EOL/deprecated
- Known vulnerabilities in tools

---

## 9. Quality Thresholds

| Metric | Threshold |
| :--- | :--- |
| **Minimum file size** | 30 lines |
| **Optimal file size** | 50–200 lines |
| **Split trigger** | >300 lines OR >2 distinct subtopics |
| **Merge trigger** | <30 lines AND >50% overlap with sibling |

---

## 10. Merge/Split Rules

### Split criteria
- >300 lines with multiple subtopics
- Different technologies/cases in one file
- Independent concepts
- Each file keeps link to parent

### Merge criteria
- <30 lines with overlap
- Same-directory files with similar naming
- Cross-references >3 times
- Semantic duplicates

**Merge procedure:**

1. Identify all files for merge
2. Choose best location (primary domain)
3. Combine using structure `Definitions → Basic Concepts → Practical Scenarios → Additional Information`
4. Create links from old locations
5. Mark old files deprecated or delete

---

## 11. Cross-Reference Rules

| Type | Format | When to use |
| :--- | :--- | :--- |
| Direct | `[Concept](./file.md)` | Same directory |
| Relative | `[Concept](../Parent/file.md)` | Subdirectory → parent |
| Absolute | `[Concept](../Directory/file.md)` | Different directory |
| Anchor | `[Section](#section-name)` | Within file |

**Link Validation (MANDATORY after any edit):**
- Verify all internal links work
- Check: relative paths, anchor links, cross-references
- Fix broken links before completing edit

**Forbidden:**

- Link lists at file end
- Broken links
- Circular references without purpose
- Duplicate SSoT definitions

---

## 12. Currency and Freshness

### Verification triggers

- Explicit user request
- Info older than 12 months
- Version EOL
- Tool vulnerabilities

### Freshness indicators

- Version-specific (K8s 1.23) → check if still valid
- Tool-specific (old flag) → check version
- Concept (TCP basics) → generally evergreen
- Best practices → check for updates

### Handling

- Version numbers → check if current
- EOL dates → add warning banner
- Tutorial steps → verify tool availability
- Links → validate accessibility

---

## 13. Confidence Scale (summary)

```
10 — SSoT + current sources
 9 — internal files
 7-8 — partially confirmed
 5-6 — fragmentary
 <4 — insufficient
```

---

## 14. Index Maintenance

- `index.md` is auto-generated — do NOT edit manually
- Keep directories with 3+ files
- Remove empty directories

---

## 15. Scripts and Tools

**Skip for knowledge base tasks:**
- Python scripts (`clean_vtt.py`, `video_to_text_*.py`)
- Focus on markdown documentation only
