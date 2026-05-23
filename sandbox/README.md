# Sandbox

A safe place for personal compositions and experimentation.

**Files in here are gitignored** — iterate freely without worrying about
commits. The directory itself is tracked (via this README and a per-directory
`.gitignore`) so it exists in a fresh clone; everything else inside stays
local to your checkout.

## Typical workflow

Copy any file from [`../examples/`](../examples/) as a starting point, then
edit and run as much as you like:

```bash
cp examples/demo.py sandbox/my_idea.py
# edit sandbox/my_idea.py freely
python sandbox/my_idea.py
```

## Sharing a file from here

If you want to publish something from your sandbox, promote it into
`examples/` and commit it there. Or, to track a single file in place, use
`git add -f sandbox/<file>`.
