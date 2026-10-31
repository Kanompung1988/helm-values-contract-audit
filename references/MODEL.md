# Evidence and limitations

A chart can refer to `.Values.service.port` while its defaults are refactored to `service.targetPort`. That mismatch is easy to miss in large Helm templates, and should be reviewed before releases.

## Scope and false-positive boundaries

Not a Go template parser, Helm renderer, or policy checker. Missing chart defaults may be intentional because Helm values can come from `--set`, external files, parent charts or required input. Pipelines with `default`/`required` are informational. Dynamic access and aliases are not fully resolved; the result is a review signal, not proof of a broken deployment.

## Authoritative sources

- https://docs.helm.sh/docs/v3/chart_template_guide/values_files/
- https://docs.helm.sh/docs/chart_template_guide/functions_and_pipelines/
- https://helm.sh/docs/topics/charts/

## Output policy

Paths and structured labels only; never print values from secret/config keys. Reports are deterministic for a given input file.
