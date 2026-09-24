# Toolkit development contract

- Preserve a harness-neutral core. Product bindings belong only in `adapters/` or target-project context.
- Apply organization policy before repository, path, skill, task, or runtime instructions.
- Inspect consumers and neighboring conventions before editing; make the smallest coherent change.
- Never apply changes to protected policy or released skills automatically. Use an explicit maintenance workflow and human review.
- Preserve unrelated user work and avoid destructive Git operations.
- Do not add empty directories, placeholders, unused scripts, speculative abstractions, or duplicate instructions.
- Use only synthetic, non-sensitive eval data. Never store secrets, raw customer rows, or hidden reasoning traces.
- Run `python3 -B tooling/validate-kit.py` and `python3 -B -m unittest discover -s tests -v` after substantive changes; `-B` prevents validation itself from creating release-forbidden bytecode caches.
- Report only commands and checks actually run; distinguish verified facts, assumptions, and remaining uncertainty.