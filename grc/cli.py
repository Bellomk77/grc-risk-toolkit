"""python -m grc assess examples/maplewood --out reports/maplewood --top 5"""
from __future__ import annotations

import argparse
from pathlib import Path

from .engine import load
from .report import build_all


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="grc", description="Risk assessment as code (NIST CSF 2.0)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("assess", help="Score risks and build the register, roadmap and executive report")
    s.add_argument("folder", help="Folder with organization.yaml, assets.yaml, controls.yaml, threats.yaml")
    s.add_argument("--out", default="reports")
    s.add_argument("--top", type=int, default=5, help="Roadmap items in the what-if scenario")
    s.add_argument("--fail-above", type=float, help="Exit 1 if any residual risk score exceeds this (CI gate)")
    args = ap.parse_args(argv)

    a = load(args.folder).score()
    paths = build_all(a, Path(args.out), top_n=args.top)
    print(f"{'ID':<5}{'Residual':>9}  Rating     Scenario")
    for r in a.register:
        print(f"{r['id']:<5}{r['residual_score']:>9}  {r['residual_rating']:<10} {r['scenario']}")
    print(f"\nTotal residual risk {a.total_residual()} · outputs: " + ", ".join(p.name for p in paths.values()))
    if args.fail_above is not None and a.register[0]["residual_score"] > args.fail_above:
        print(f"GATE FAILED: {a.register[0]['id']} residual score {a.register[0]['residual_score']} > {args.fail_above}")
        return 1
    return 0
