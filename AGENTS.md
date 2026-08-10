# EHF Applications repository instructions

- Work directly on the GitHub default branch, `main`; do not create or switch branches or worktrees.
- Treat the approved design specification and plans under `docs/superpowers/` as preserved source documents. Change them only when a task explicitly requests it.
- Before editing, inspect the worktree and confirm that local `main` matches `origin/main`. Stop if either has unrelated changes or the branches differ.
- Use test-driven development for every implementation change: write the smallest behavior test, run it RED, implement the minimum, then run the focused and full suites.
- Use the explicit repository Python runtime when Python is needed: `C:\Users\aag\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe`.
- Keep runtime and development dependencies exactly pinned in the requirements files. Do not commit credentials, applicant documents, import output, or test artifacts.
- Stage only files belonging to the current task. Use the commit subject specified by that task, and do not push unless the task explicitly authorizes it.
- Production applicant invitations remain disabled until the documented approval gate is completed by Adriano Aguzzi.
