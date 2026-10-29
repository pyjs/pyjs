# Agent workflow

- Save work in local commits on task branches; do not use `git stash` when
  switching tasks or branches. WIP commits are welcome and can be squashed
  before pushing a pull request. Keep unrelated user changes out of commits.
- Prefer switching task branches in the main checkout over creating extra
  worktrees for sequential work. Preserve each task's work before switching.
