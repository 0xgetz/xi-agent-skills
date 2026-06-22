---
name: skill-creator
description: Creates and improves agent skills using Gumloop's sandbox helpers and SKILL.md conventions. Use when the user asks to create, refactor, validate, or document skills.
icon: sparkles
color: Purple
---

# Skill Creator

## When to Use

Use this skill when the task is about authoring or improving another skill, including:

- Creating a new skill from scratch
- Updating an existing `SKILL.md`
- Restructuring long skill docs into references
- Validating naming/frontmatter rules
- Tightening quality with concise instructions and examples

If the task is not skill-authoring related, do not activate this skill.

## Workflow

Use this checklist for skill creation and major edits:

```
Skill Authoring Progress:
- [ ] Step 1: Confirm scope and skill name
- [ ] Step 2: Scaffold or inspect existing files
- [ ] Step 3: Draft concise SKILL.md
- [ ] Step 4: Add resource directories only if needed
- [ ] Step 5: Validate and fix issues
```

### Step 1: Confirm scope and skill name

- Use lowercase hyphen-case names only (`a-z`, `0-9`, `-`).
- Keep name <= 64 chars.
- Ensure the directory name and frontmatter `name` are identical.
- Prefer clear capability names over vague names.

### Step 2: Scaffold or inspect files

Skills always live under the absolute path `/home/user/skills/<skill-name>/` — NEVER relative to your current working directory. Your cwd is typically the per-interaction dir, NOT `/home/user/`, so a `path="skills/foo"` argument would write to the wrong place. Always pass the absolute `/home/user/skills/<skill-name>/...` path to `sandbox_file`, `sandbox_python`, and any shell command.

For new skills, scaffold first:

```bash
python3 /home/user/skills/.tools/init_skill.py my-skill-name
```

Add `--scripts`, `--references`, or `--assets` only when the skill needs them.

For existing skills, read:

```bash
sandbox_file(action="read", path="/home/user/skills/my-skill-name/SKILL.md")
```

### Step 3: Draft concise SKILL.md

Write only what changes behavior. Assume the model already understands basics.

Frontmatter requirements:

- `name`: required, hyphen-case, <=64 chars
- `description`: required, non-empty, <=1024 chars, no angle brackets
- Optional: `icon`, `color`, `related_server_ids`
- `related_server_ids`: array of actual server IDs from server discovery (e.g. `[apollo, gbigquery]`) when the skill is specific to one or more integrations. Enables server-scoped skill discovery. Omit this field if you are not sure which exact server IDs apply.

Description should state both:

1. What the skill does
2. When it should be used (triggering context)

### Step 4: Add resource directories only if needed

Most skills only need a `SKILL.md`. Only create resource directories when there's a concrete reason:

- `scripts/`: deterministic code that would otherwise be rewritten each time
- `references/`: large docs that would bloat SKILL.md past ~500 lines
- `assets/`: static files used in skill output (templates, images)

If you do add references, keep them one level deep from SKILL.md.

### Step 5: Validate and iterate

Run validation:

```bash
python3 /home/user/skills/.tools/quick_validate.py my-skill-name
```

If validation fails:

1. Fix reported issues
2. Re-run validation
3. Repeat until valid

## Authoring Patterns

Choose the right degree of specificity:

- High freedom: heuristics and principles for variable tasks
- Medium freedom: templates/pseudocode with parameters
- Low freedom: exact commands for fragile workflows

Default to one recommended method, then document exceptions only when needed.

## Quality Guardrails

- Do not create resource directories or files unless the skill clearly benefits from them.
- Use consistent terminology across the skill.
- Avoid time-sensitive instructions unless clearly marked as legacy.
- Prefer short, concrete examples over long explanations.
- Include verification loops for critical workflows.
- For longer reference files, add a table of contents at the top.

## Output Expectations

When asked to create/update a skill, produce:

1. Updated `SKILL.md` with valid frontmatter
2. Any needed files in `scripts/`, `references/`, or `assets/`
3. Validation result from `quick_validate.py`

If the user asks for multiple changes, apply them directly and re-validate.
