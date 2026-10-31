#!/usr/bin/env python3
"""Offline, conservative Helm .Values reference / values.yaml contract check."""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml

MAX_FILE_BYTES = 1024 * 1024
MAX_TEMPLATE_FILES = 256
# Only statically spelled, literal, dot-based references. Not a Go template interpreter.
DOT_REF = re.compile(r"(?<![\w.])(?:\$\.)?\.Values((?:\.[a-zA-Z_][a-zA-Z_0-9-]*)+)")
INDEX_REF = re.compile(r'\bindex\s+(?:\$\.)?\.Values((?:\s+"[^"\n]+")+)')
INDEX_KEYS = re.compile(r'"([^"\n]+)"')
ACTION = re.compile(r"\{\{[-]?(.+?)[-]?\}\}", re.DOTALL)


class InvalidChart(ValueError):
    pass


class UniqueLoader(yaml.SafeLoader):
    pass


def _map(loader: yaml.Loader, node: yaml.nodes.MappingNode) -> dict:
    loader.flatten_mapping(node)
    data = {}
    for kn, vn in node.value:
        key = loader.construct_object(kn, deep=True)
        if not isinstance(key, (str, int, float, bool, tuple)):
            raise InvalidChart("unsupported YAML mapping key")
        if key in data:
            raise InvalidChart("duplicate YAML mapping key")
        data[key] = loader.construct_object(vn, deep=True)
    return data


UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _map)


@dataclass(frozen=True)
class Finding:
    code: str
    severity: str
    file: str
    line: int
    key: str
    detail: str


def _read(path: Path) -> str:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_FILE_BYTES:
        raise InvalidChart("missing, symlinked or oversized chart file")
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise InvalidChart(f"cannot read chart file: {type(exc).__name__}") from exc


def _has_path(values: dict, keys: tuple[str, ...]) -> bool:
    node: Any = values
    for key in keys:
        if not isinstance(node, dict) or key not in node:
            return False
        node = node[key]
    return True


def _file_actions(content: str) -> list[tuple[str, int]]:
    # Ignore comments in Go templates, which can span lines.
    clean = re.sub(r"\{\{[-]?/\*.*?\*/[-]?\}\}", lambda m: "\n" * m.group().count("\n"), content, flags=re.DOTALL)
    out = []
    for m in ACTION.finditer(clean):
        out.append((m.group(1), clean.count("\n", 0, m.start()) + 1))
    return out


def audit(chart: Path) -> list[Finding]:
    if chart.is_symlink() or not chart.is_dir():
        raise InvalidChart("chart path must be a local directory")
    try:
        meta = yaml.load(_read(chart / "Chart.yaml"), Loader=UniqueLoader)
        values = yaml.load(_read(chart / "values.yaml"), Loader=UniqueLoader)
    except (yaml.YAMLError, RecursionError) as exc:
        raise InvalidChart(f"invalid YAML: {type(exc).__name__}") from exc
    if not isinstance(meta, dict) or not isinstance(meta.get("name"), str):
        raise InvalidChart("Chart.yaml requires chart name")
    if values is None:
        values = {}
    if not isinstance(values, dict):
        raise InvalidChart("values.yaml must contain a mapping")
    template_root = chart / "templates"
    if template_root.is_symlink() or not template_root.is_dir():
        raise InvalidChart("chart requires a local templates/ directory")
    files = sorted(p for p in template_root.rglob("*") if p.is_file())
    if len(files) > MAX_TEMPLATE_FILES:
        raise InvalidChart("too many template files")
    findings: list[Finding] = []
    for path in files:
        relative = path.relative_to(chart).as_posix()
        data = _read(path)
        for action, line in _file_actions(data):
            refs: dict[tuple[str, ...], str] = {}
            for m in DOT_REF.finditer(action):
                refs[tuple(m.group(1)[1:].split("."))] = m.group()
            for m in INDEX_REF.finditer(action):
                keys = tuple(INDEX_KEYS.findall(m.group(1)))
                if keys:
                    refs[keys] = "index .Values " + " ".join(keys)
            for keys, label in refs.items():
                if _has_path(values, keys):
                    continue
                key = ".".join(keys)
                # Default/required are intentional missing-value patterns: warn, but don't fail.
                optional = bool(re.search(r"\|\s*(default|required|coalesce|empty)\b", action))
                findings.append(Finding("OPTIONAL_UNDECLARED" if optional else "UNDECLARED_VALUE",
                    "INFO" if optional else "REVIEW", relative, line, key,
                    ("A template references a value absent from values.yaml, but a fallback/required check is present."
                     if optional else "A template references a value absent from values.yaml; callers may intentionally override it.")))
            if (re.search(r"\b(?:get|dig|pluck|tpl)\s+(?:\$\.)?\.Values\b", action)
                    or re.search(r"\b(?:range|with)\s+(?:\$\.)?\.Values\b", action)):
                findings.append(Finding("DYNAMIC_VALUES", "INFO", relative, line, "(dynamic)",
                    "A dynamic template expression may access values this static scanner cannot resolve."))
    return sorted(findings, key=lambda f: (f.file, f.line, f.code, f.key))


def run(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("chart", type=Path, help="Local Helm chart directory")
    p.add_argument("--format", choices=("text", "json"), default="text")
    p.add_argument("--fail-on", choices=("never", "review"), default="review")
    args = p.parse_args(argv)
    try:
        findings = audit(args.chart)
    except InvalidChart as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    if args.format == "json":
        print(json.dumps({"findings": [asdict(x) for x in findings],
            "counts": {x: sum(y.severity == x for y in findings) for x in ("REVIEW", "INFO")}}, indent=2))
    else:
        for finding in findings:
            print(f"[{finding.severity}] {finding.code} {finding.file}:{finding.line} {finding.key}: {finding.detail}")
        print(f"Findings: {len(findings)} (static reference checks, not helm template execution)")
    return 1 if args.fail_on == "review" and any(f.severity == "REVIEW" for f in findings) else 0


if __name__ == "__main__":
    sys.exit(run())
