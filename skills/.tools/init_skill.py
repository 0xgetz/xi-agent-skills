#!/usr/bin/env python3
"""
Skill Initializer - Creates a new skill from template

Usage:
    init_skill.py <skill-name> [--scripts] [--references] [--assets]

Examples:
    init_skill.py my-new-skill
    init_skill.py my-api-helper --scripts --references

Skills are created at /home/user/skills/<skill-name>/
"""

import re
import sys
from pathlib import Path


SKILL_TEMPLATE = """---
name: {skill_name}
description: "TODO: What this skill does and when to use it. Max 1024 chars. No angle brackets."
# icon: "TODO: Optional Lucide icon name, e.g. code, file-text, search. Remove if not needed."
# color: "TODO: Optional color: Grey, Blue, Green, Orange, Red, Yellow, Teal, Pink, Purple, Bronze, Black. Remove if not needed."
---

# {skill_title}

## Overview

[TODO: 1-2 sentences explaining what this skill enables]

## Structuring This Skill

[TODO: Choose the structure that best fits this skill's purpose. Common patterns:

**1. Workflow-Based** (best for sequential processes)
- Works well when there are clear step-by-step procedures
- Structure: ## Overview -> ## Workflow Decision Tree -> ## Step 1 -> ## Step 2...

**2. Task-Based** (best for tool collections)
- Works well when the skill offers different operations/capabilities
- Structure: ## Overview -> ## Quick Start -> ## Task Category 1 -> ## Task Category 2...

**3. Reference/Guidelines** (best for standards or specifications)
- Works well for brand guidelines, coding standards, or requirements
- Structure: ## Overview -> ## Guidelines -> ## Specifications -> ## Usage...

**4. Capabilities-Based** (best for integrated systems)
- Works well when the skill provides multiple interrelated features
- Structure: ## Overview -> ## Core Capabilities -> ### 1. Feature -> ### 2. Feature...

Patterns can be mixed and matched as needed.

Delete this entire "Structuring This Skill" section when done - it's just guidance.]

## [TODO: Replace with the first main section based on chosen structure]

[TODO: Add content here. Examples:
- Code samples for technical skills
- Decision trees for complex workflows
- Concrete examples with realistic user requests
- References to scripts/assets/references as needed]
"""

EXAMPLE_SCRIPT = '''#!/usr/bin/env python3
"""
Example helper script for {skill_name}

This is a placeholder script. Replace with actual implementation or delete if not needed.
"""

def main():
    print("This is an example script for {skill_name}")
    # TODO: Add actual script logic here

if __name__ == "__main__":
    main()
'''

EXAMPLE_REFERENCE = """# Reference Documentation for {skill_title}

This is a placeholder for detailed reference documentation.
Replace with actual reference content or delete if not needed.

## Structure Suggestions

### API Reference Example
- Overview
- Authentication
- Endpoints with examples
- Error codes

### Workflow Guide Example
- Prerequisites
- Step-by-step instructions
- Common patterns
- Troubleshooting
"""

EXAMPLE_ASSET = """# Example Asset File

This placeholder represents where asset files would be stored.
Replace with actual asset files (templates, images, data files, etc.) or delete if not needed.

Assets are NOT loaded into context, but rather used within
the output the agent produces.
"""

DIR_FLAGS = {"--scripts": "scripts", "--references": "references", "--assets": "assets"}


def title_case_skill_name(skill_name):
    """Convert hyphenated skill name to Title Case for display."""
    return ' '.join(word.capitalize() for word in skill_name.split('-'))


SKILLS_BASE_PATH = "/home/user/skills"


def init_skill(skill_name, resource_dirs=None):
    """
    Initialize a new skill directory with template SKILL.md.

    Args:
        skill_name: Name of the skill
        resource_dirs: Optional set of directory names to create (from VALID_RESOURCE_DIRS).
                       None means no resource directories are created.

    Returns:
        Path to created skill directory, or None if error
    """
    # Validate skill name before creating anything
    if not re.match(r'^[a-z0-9-]+$', skill_name):
        print(f"Error: Name '{skill_name}' must be hyphen-case (lowercase letters, digits, and hyphens only)")
        return None
    if skill_name.startswith('-') or skill_name.endswith('-') or '--' in skill_name:
        print(f"Error: Name '{skill_name}' cannot start/end with hyphen or contain consecutive hyphens")
        return None
    if len(skill_name) > 64:
        print(f"Error: Name is too long ({len(skill_name)} characters). Maximum is 64 characters.")
        return None

    skill_dir = Path(SKILLS_BASE_PATH) / skill_name

    if skill_dir.exists():
        print(f"Error: Skill directory already exists: {skill_dir}")
        return None

    try:
        skill_dir.mkdir(parents=True, exist_ok=False)
        print(f"Created skill directory: {skill_dir}")
    except Exception as e:
        print(f"Error creating directory: {e}")
        return None

    # Create SKILL.md from template
    skill_title = title_case_skill_name(skill_name)
    skill_content = SKILL_TEMPLATE.format(
        skill_name=skill_name,
        skill_title=skill_title
    )

    skill_md_path = skill_dir / 'SKILL.md'
    try:
        skill_md_path.write_text(skill_content)
        print("Created SKILL.md")
    except Exception as e:
        print(f"Error creating SKILL.md: {e}")
        return None

    # Create only the requested resource directories with starter files
    if resource_dirs:
        try:
            if "scripts" in resource_dirs:
                scripts_dir = skill_dir / 'scripts'
                scripts_dir.mkdir(exist_ok=True)
                example_script = scripts_dir / 'example.py'
                example_script.write_text(EXAMPLE_SCRIPT.format(skill_name=skill_name))
                example_script.chmod(0o755)
                print("Created scripts/example.py")

            if "references" in resource_dirs:
                references_dir = skill_dir / 'references'
                references_dir.mkdir(exist_ok=True)
                example_reference = references_dir / 'api_reference.md'
                example_reference.write_text(EXAMPLE_REFERENCE.format(skill_title=skill_title))
                print("Created references/api_reference.md")

            if "assets" in resource_dirs:
                assets_dir = skill_dir / 'assets'
                assets_dir.mkdir(exist_ok=True)
                example_asset = assets_dir / 'example_asset.txt'
                example_asset.write_text(EXAMPLE_ASSET)
                print("Created assets/example_asset.txt")
        except Exception as e:
            print(f"Error creating resource directories: {e}")
            return None

    print(f"\nSkill '{skill_name}' initialized successfully at {skill_dir}")
    print("\nNext steps:")
    print("1. Edit SKILL.md to replace the TODO placeholders")
    print("2. Run the validator when ready: python3 /home/user/skills/.tools/quick_validate.py " + skill_name)

    return skill_dir


def parse_args(args):
    """Parse CLI args, returning (skill_name, resource_dirs)."""
    skill_name = None
    resource_dirs = set()

    for arg in args:
        if arg in DIR_FLAGS:
            resource_dirs.add(DIR_FLAGS[arg])
        elif arg.startswith("--"):
            print(f"Error: unknown flag: {arg}")
            print(f"Valid flags: {', '.join(sorted(DIR_FLAGS.keys()))}")
            sys.exit(1)
        elif skill_name is None:
            skill_name = arg
        else:
            print(f"Error: unexpected argument: {arg}")
            sys.exit(1)

    return skill_name, resource_dirs or None


def main():
    if len(sys.argv) < 2:
        print("Usage: init_skill.py <skill-name> [--scripts] [--references] [--assets]")
        print("\nSkill name requirements:")
        print("  - Hyphen-case identifier (e.g., 'data-analyzer')")
        print("  - Lowercase letters, digits, and hyphens only")
        print("  - Max 64 characters")
        print("  - Must match directory name exactly")
        print("\nOptions:")
        print("  --scripts     Create scripts/ with an example helper script")
        print("  --references  Create references/ with an example reference doc")
        print("  --assets      Create assets/ with an example asset file")
        print("               Only use these when the skill clearly needs them.")
        print("\nExamples:")
        print("  init_skill.py my-new-skill")
        print("  init_skill.py my-api-helper --scripts --references")
        print(f"\nSkills are created at {SKILLS_BASE_PATH}/<skill-name>/")
        sys.exit(1)

    skill_name, resource_dirs = parse_args(sys.argv[1:])

    if not skill_name:
        print("Error: skill name is required")
        sys.exit(1)

    print(f"Initializing skill: {skill_name}")
    print(f"Location: {SKILLS_BASE_PATH}/{skill_name}")
    print()

    result = init_skill(skill_name, resource_dirs=resource_dirs)

    if result:
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
