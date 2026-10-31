---
name: helm-values-contract-audit
description: Use when you need to review static .Values paths and literal index lookups in Helm Go templates against local values.yaml defaults, flagging undeclared references and dynamic expressions requiring human review. Trigger for Helm chart templates are edited, chart values are refactored, or an agent needs a quick reproducible path/line report before helm lint/template; do not use for live deployment proof or cluster access.
license: MIT
compatibility: Python 3.10+; install PyYAML>=6,<7; local filesystem read only.
---

# Helm Values Contract Audit

Use this skill to help an agent review a local config change without guessing about runtime reachability. Read [references/MODEL.md](references/MODEL.md) for source-backed semantics and limitations.

## When to use

- Helm chart templates are edited, chart values are refactored, or an agent needs a quick reproducible path/line report before helm lint/template.
- Need a reproducible review artifact from local files to attach to a pull request.

## Do not use

- You need complete go template execution, render-time behavior, subchart resolution, values.schema.json validation, live cluster access, or proof that a chart deployment fails.
- Do not infer operational exposure or broken deploys without running the platform-native tool in the actual target environment.

## Procedure

1. Confirm the repository location and ask for only the minimum local configuration file/chart path (do not request secret values).
2. Install the declared Python dependency: `python -m pip install -r requirements.txt`.
3. Run `python scripts/audit.py ./mychart --format text --fail-on review` from the skill repository. To avoid CI hard failures while reviewing, add `--fail-on never`.
4. Record actual `code`, `severity`, `file`/`path` and source line where present. Do not conflate `INFO` or `REVIEW` with a confirmed vulnerability.
5. For each finding, explain the precise static evidence, a narrow remediation suggestion, and what runtime check is still needed.
6. Validate any proposed change with the official Docker Compose or Helm CLI (outside this skill), plus unit/fixture tests. Never make code changes without user approval.
7. If input is malformed (exit code 2), stop instead of presenting incomplete results as clean.

## Command and exit codes

```
python scripts/audit.py examples/chart --format json --fail-on never
python -m unittest discover -s tests -v
```

`0`: no configured failure threshold reached; `1`: a finding at the selected threshold; `2`: invalid/unreadable input. Exit 0 is not a proof of security.

## Safety and limits

Not a Go template parser, Helm renderer, or policy checker. Missing chart defaults may be intentional because Helm values can come from `--set`, external files, parent charts or required input. Pipelines with `default`/`required` are informational. Dynamic access and aliases are not fully resolved; the result is a review signal, not proof of a broken deployment.

Outputs are static, deterministic and do not contact Docker, Kubernetes, Helm repositories, or network endpoints.
