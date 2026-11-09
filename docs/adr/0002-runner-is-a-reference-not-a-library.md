# The runner ships as a reference for agents, not as a library

`build-runner` gives the agent a minimal reference implementation of the hardest parts of a runner (run identity, per-item atomic commits under one writer, resume, failure handling, progress and summary), and a skill that spells out the core logic and its pitfalls. The agent then writes the repo's own runner in its library area, shaped to the work the repo actually runs. dkitchen does not ship a runner library: every research repo calls different services and needs different spec fields, and a shared library would either grow every repo's special case or be bypassed. The cost is that each repo owns and tests its runner, and a fix in the reference does not reach runners already written.

## Considered options

- **`dkitchen.runner` library**: one tested implementation, but `ding` is installed with pipx while experiments run in the repo's own environment, so it would be a second install; and it fixes an interface before two repos have used it.
- **Rules only**: no code to copy, but principles alone are how a repo ends up with one runner per experiment.
- **A drop-in copy adapted by the skill**: the closest to working code, but the repo then carries a copy whose design it did not choose and which drifts from the reference anyway.
