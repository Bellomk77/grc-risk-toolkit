"""Risk assessment as code: load an organization's assets, controls and threat
scenarios, score inherent and residual risk, and build a prioritized roadmap.

Scoring model (documented so it can be challenged, like any GRC methodology):
- Control effectiveness for a scenario = average of its linked controls
  (implemented = 1.0, partial = 0.5, not implemented = 0.0).
- Preventive controls (Govern, Identify, Protect, Detect) reduce LIKELIHOOD by up to 60%.
- Response controls (Respond, Recover, and backups) reduce IMPACT by up to 40%.
- Risk score = likelihood x impact on a 1-25 scale.
  Critical >= 15 · High >= 10 · Medium >= 5 · Low < 5
"""
from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

STATUS_WEIGHT = {"implemented": 1.0, "partial": 0.5, "not_implemented": 0.0}
EFFORT_WEIGHT = {"S": 1, "M": 2, "L": 4}
IMPACT_REDUCING = {"Respond", "Recover"}
IMPACT_REDUCING_IDS = {"PR.DS-11"}  # backups limit the damage rather than preventing the event
MAX_LIKELIHOOD_REDUCTION, MAX_IMPACT_REDUCTION = 0.6, 0.4
CSF_ID = re.compile(r"^(GV|ID|PR|DE|RS|RC)\.[A-Z]{2}-\d{2}$")
FUNCTIONS = ["Govern", "Identify", "Protect", "Detect", "Respond", "Recover"]


def rating(score: float) -> str:
    return "Critical" if score >= 15 else "High" if score >= 10 else "Medium" if score >= 5 else "Low"


@dataclass
class Assessment:
    org: dict
    assets: dict[str, dict]
    controls: dict[str, dict]
    scenarios: list[dict]
    register: list[dict] = field(default_factory=list)

    # ------------------------------------------------------------ scoring
    def score(self) -> "Assessment":
        self.register = [self._score_scenario(s) for s in self.scenarios]
        self.register.sort(key=lambda r: -r["residual_score"])
        return self

    def _effectiveness(self, ids: list[str]) -> tuple[float, float]:
        prev = [STATUS_WEIGHT[self.controls[c]["status"]] for c in ids if not self._impact_reducing(c)]
        resp = [STATUS_WEIGHT[self.controls[c]["status"]] for c in ids if self._impact_reducing(c)]
        avg = lambda xs: sum(xs) / len(xs) if xs else 0.0  # noqa: E731
        return avg(prev), avg(resp)

    def _impact_reducing(self, cid: str) -> bool:
        return cid in IMPACT_REDUCING_IDS or self.controls[cid]["function"] in IMPACT_REDUCING

    def _score_scenario(self, s: dict) -> dict:
        likelihood, impact = s["likelihood"], max(s["impact"].values())
        prev, resp = self._effectiveness(s["controls"])
        res_l = max(1.0, likelihood * (1 - MAX_LIKELIHOOD_REDUCTION * prev))
        has_resp = any(self._impact_reducing(c) for c in s["controls"])
        res_i = max(1.0, impact * (1 - MAX_IMPACT_REDUCTION * resp)) if has_resp else float(impact)
        gaps = [c for c in s["controls"] if self.controls[c]["status"] != "implemented"]
        return {
            "id": s["id"], "scenario": s["name"], "source": s["source"],
            "assets": ", ".join(self.assets[a]["name"] for a in s["assets"]),
            "inherent_likelihood": likelihood, "inherent_impact": impact,
            "inherent_score": likelihood * impact, "inherent_rating": rating(likelihood * impact),
            "control_effectiveness": round((prev + resp) / 2 if has_resp else prev, 2),
            "residual_likelihood": round(res_l, 1), "residual_impact": round(res_i, 1),
            "residual_score": round(res_l * res_i, 1), "residual_rating": rating(res_l * res_i),
            "worst_impact_dimension": max(s["impact"], key=s["impact"].get),
            "control_gaps": gaps,
        }

    # ------------------------------------------------------------ insights
    def total_residual(self) -> float:
        return round(sum(r["residual_score"] for r in self.register), 1)

    def maturity(self) -> dict[str, float]:
        out = {}
        for fn in FUNCTIONS:
            vals = [STATUS_WEIGHT[c["status"]] for c in self.controls.values() if c["function"] == fn]
            out[fn] = round(sum(vals) / len(vals), 2) if vals else 0.0
        return out

    def with_controls_implemented(self, ids: list[str]) -> "Assessment":
        other = copy.deepcopy(self)
        for cid in ids:
            other.controls[cid]["status"] = "implemented"
        return other.score()

    def roadmap(self) -> list[dict]:
        """Rank every control gap by residual-risk reduction per unit of effort."""
        base = self.total_residual()
        items = []
        for cid, c in self.controls.items():
            if c["status"] == "implemented":
                continue
            reduction = round(base - self.with_controls_implemented([cid]).total_residual(), 1)
            if reduction <= 0:
                continue
            affected = [r["id"] for r in self.register if cid in r["control_gaps"]]
            items.append({"control": cid, "title": c["title"], "function": c["function"], "status": c["status"],
                          "effort": c["effort"], "owner": c.get("owner", ""), "risk_reduction": reduction,
                          "priority": round(reduction / EFFORT_WEIGHT[c["effort"]], 2), "risks_addressed": affected})
        return sorted(items, key=lambda x: -x["priority"])


# ------------------------------------------------------------ loading + validation
def load(folder: Path | str) -> Assessment:
    folder = Path(folder)
    read = lambda name: yaml.safe_load((folder / name).read_text())  # noqa: E731
    org = read("organization.yaml")
    assets = {a["id"]: a for a in read("assets.yaml")["assets"]}
    controls = {c["id"]: c for c in read("controls.yaml")["controls"]}
    scenarios = read("threats.yaml")["scenarios"]
    validate(assets, controls, scenarios)
    return Assessment(org, assets, controls, scenarios)


def validate(assets: dict, controls: dict, scenarios: list[dict]) -> None:
    errors = []
    for cid, c in controls.items():
        if not CSF_ID.match(cid):
            errors.append(f"Control id '{cid}' is not a NIST CSF 2.0 subcategory id (e.g. PR.AA-03)")
        if not isinstance(c.get("title"), str) or None in c.values():
            errors.append(f"{cid}: every field needs a value (quote titles that contain commas)")
        if c.get("status") not in STATUS_WEIGHT:
            errors.append(f"{cid}: status must be one of {list(STATUS_WEIGHT)}")
        if c.get("effort") not in EFFORT_WEIGHT:
            errors.append(f"{cid}: effort must be S, M or L")
        if c.get("function") not in FUNCTIONS:
            errors.append(f"{cid}: function must be one of {FUNCTIONS}")
    for s in scenarios:
        if not 1 <= s.get("likelihood", 0) <= 5:
            errors.append(f"{s['id']}: likelihood must be 1-5")
        if not s.get("impact") or not all(1 <= v <= 5 for v in s["impact"].values()):
            errors.append(f"{s['id']}: every impact dimension must be 1-5")
        errors += [f"{s['id']}: unknown asset {a}" for a in s["assets"] if a not in assets]
        errors += [f"{s['id']}: unknown control {c}" for c in s["controls"] if c not in controls]
    if errors:
        raise ValueError("Invalid assessment input:\n- " + "\n- ".join(errors))
