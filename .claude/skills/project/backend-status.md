---
name: backend-status
trigger: /backend-status
description: Quick status check of the mingai backend — shows module coverage, test count, and key pending items.
---

Run the following to get the current backend status:

```bash
cd /Users/cheongwailuen/Development/mingai/.claude/worktrees/agent-a890eedb/src/backend

# Test count
python -m pytest tests/unit/ -q --tb=no 2>&1 | tail -3

# Module coverage
ls app/modules/

# Recent commits
git log --oneline -5
```

Then report:
1. Test pass count
2. Which modules exist vs are missing
3. Last 5 commits
4. Any obvious stubs (grep for TODO/NotImplementedError in non-test files)

```bash
grep -r "TODO\|NotImplementedError\|STUB" app/ --include="*.py" | grep -v test | grep -v __pycache__
```
