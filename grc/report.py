"""Turn an assessment into the deliverables a GRC team hands to management:
a risk register (Excel + CSV), heat maps, a CSF maturity chart and an executive HTML report."""
from __future__ import annotations

import base64
import csv
import html
from datetime import date
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.colors import ListedColormap  # noqa: E402
from openpyxl import Workbook  # noqa: E402
from openpyxl.styles import Alignment, Font, PatternFill  # noqa: E402

from .engine import FUNCTIONS, Assessment, rating  # noqa: E402

RATING_COLOR = {"Critical": "#b42318", "High": "#e8590c", "Medium": "#f2c94c", "Low": "#40a37a"}
RATING_FILL = {"Critical": "F8D0CD", "High": "FDDCC4", "Medium": "FFF1C2", "Low": "D4EFE2"}


# ------------------------------------------------------------------ charts
def heatmaps(before: Assessment, after: Assessment, path: Path) -> Path:
    grid = np.array([[rating(l * i) for i in range(1, 6)] for l in range(1, 6)])
    zones = np.vectorize({"Low": 0, "Medium": 1, "High": 2, "Critical": 3}.get)(grid)
    cmap = ListedColormap(["#d4efe2", "#fff1c2", "#fddcc4", "#f8d0cd"])
    panels = [("Inherent risk (no controls)", before.register, "inherent"),
              ("Residual risk today", before.register, "residual"),
              ("After top-5 roadmap items", after.register, "residual")]
    fig, axes = plt.subplots(1, 3, figsize=(15, 5.2), dpi=150)
    for ax, (title, reg, kind) in zip(axes, panels):
        ax.imshow(zones, cmap=cmap, origin="lower", extent=[0.5, 5.5, 0.5, 5.5], vmin=0, vmax=3)
        placed: list[tuple[float, float]] = []
        offsets = [(0, 0), (0.34, 0), (-0.34, 0), (0, 0.34), (0, -0.34), (0.34, 0.34), (-0.34, -0.34),
                   (0.34, -0.34), (-0.34, 0.34), (0.68, 0), (-0.68, 0)]
        for r in sorted(reg, key=lambda r: r["id"]):
            bx, by = r[f"{kind}_impact"], r[f"{kind}_likelihood"]
            # Nudge markers that would overlap so every risk ID stays readable.
            x, y = next(((bx + dx, by + dy) for dx, dy in offsets
                         if 0.6 <= bx + dx <= 5.4 and 0.6 <= by + dy <= 5.4
                         and all(np.hypot(bx + dx - px, by + dy - py) >= 0.33 for px, py in placed)), (bx, by))
            placed.append((x, y))
            col = RATING_COLOR[r[f"{kind}_rating"]]
            ax.scatter(x, y, s=330, color="white", edgecolor=col, linewidth=2.2, zorder=3)
            ax.text(x, y, r["id"], ha="center", va="center", fontsize=7.5, fontweight="bold", color="#222", zorder=4)
        counts = {k: sum(1 for r in reg if r[f"{kind}_rating"] == k) for k in RATING_COLOR}
        ax.set_title(f"{title}\n" + " · ".join(f"{k} {v}" for k, v in counts.items() if v), fontsize=11, fontweight="bold")
        ax.set_xticks(range(1, 6))
        ax.set_yticks(range(1, 6))
        ax.set_xlim(0.5, 5.5)
        ax.set_ylim(0.5, 5.5)
        ax.set_xlabel("Impact")
        ax.set_ylabel("Likelihood")
    fig.tight_layout()
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return path


def maturity_chart(a: Assessment, path: Path) -> Path:
    m = a.maturity()
    fig, ax = plt.subplots(figsize=(7.5, 3.6), dpi=150)
    vals = [m[f] * 100 for f in FUNCTIONS]
    colors = ["#b42318" if v < 34 else "#e8a33d" if v < 67 else "#40a37a" for v in vals]
    ax.barh(FUNCTIONS, vals, color=colors)
    for i, v in enumerate(vals):
        ax.text(v + 1.5, i, f"{v:.0f}%", va="center", fontsize=9)
    ax.set_xlim(0, 100)
    ax.invert_yaxis()
    ax.set_title("NIST CSF 2.0 implementation by function", loc="left", fontweight="bold")
    ax.set_xlabel("Controls implemented (partial = half credit)")
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return path


# ------------------------------------------------------------------ register
def write_register(a: Assessment, roadmap: list[dict], out: Path) -> tuple[Path, Path]:
    cols = ["id", "scenario", "source", "assets", "inherent_score", "inherent_rating", "control_effectiveness",
            "residual_likelihood", "residual_impact", "residual_score", "residual_rating", "worst_impact_dimension",
            "control_gaps"]
    csv_path = out / "risk_register.csv"
    with open(csv_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for r in a.register:
            w.writerow([", ".join(r[c]) if isinstance(r[c], list) else r[c] for c in cols])

    wb = Workbook()
    head = Font(bold=True, color="FFFFFF")
    head_fill = PatternFill("solid", fgColor="1F3B73")

    def sheet(ws, headers, rows, widths):
        ws.append(headers)
        for cell in ws[1]:
            cell.font, cell.fill = head, head_fill
            cell.alignment = Alignment(wrap_text=True, vertical="center")
        for row in rows:
            ws.append(row)
        for i, w in enumerate(widths, start=1):
            ws.column_dimensions[ws.cell(1, i).column_letter].width = w
        ws.freeze_panes = "A2"

    ws = wb.active
    ws.title = "Risk Register"
    sheet(ws, ["ID", "Scenario", "Threat source", "Assets", "Inherent score", "Inherent rating", "Control effectiveness",
               "Residual score", "Residual rating", "Worst impact", "Control gaps"],
          [[r["id"], r["scenario"], r["source"], r["assets"], r["inherent_score"], r["inherent_rating"],
            r["control_effectiveness"], r["residual_score"], r["residual_rating"], r["worst_impact_dimension"],
            ", ".join(r["control_gaps"])] for r in a.register],
          [6, 48, 18, 34, 10, 11, 12, 10, 11, 12, 40])
    for row in ws.iter_rows(min_row=2):
        for idx in (5, 8):  # rating columns
            row[idx].fill = PatternFill("solid", fgColor=RATING_FILL[row[idx].value])

    sheet(wb.create_sheet("Roadmap"), ["Priority", "Control", "Title", "Function", "Current status", "Effort",
                                       "Owner", "Risk reduction", "Risks addressed"],
          [[i + 1, x["control"], x["title"], x["function"], x["status"], x["effort"], x["owner"], x["risk_reduction"],
            ", ".join(x["risks_addressed"])] for i, x in enumerate(roadmap)],
          [8, 10, 46, 10, 15, 7, 16, 13, 18])
    sheet(wb.create_sheet("Controls"), ["CSF ID", "Function", "Title", "Status", "Effort", "Owner", "Evidence"],
          [[c["id"], c["function"], c["title"], c["status"], c["effort"], c.get("owner", ""), c.get("evidence", "")]
           for c in a.controls.values()], [10, 10, 46, 15, 7, 16, 60])
    sheet(wb.create_sheet("Assets"), ["ID", "Asset", "Type", "Owner", "Classification", "Criticality", "Internet-facing"],
          [[x["id"], x["name"], x["type"], x["owner"], x["classification"], x["criticality"], x.get("internet_facing", False)]
           for x in a.assets.values()], [6, 34, 14, 18, 14, 10, 14])
    xlsx_path = out / "risk_register.xlsx"
    wb.save(xlsx_path)
    return csv_path, xlsx_path


# ------------------------------------------------------------------ executive report
def _img(path: Path) -> str:
    return f'<img src="data:image/png;base64,{base64.b64encode(path.read_bytes()).decode()}" alt="{path.stem}">'


def executive_html(a: Assessment, after: Assessment, roadmap: list[dict], top_n: int, imgs: dict[str, Path]) -> str:
    e = html.escape
    count = lambda reg, k: sum(1 for r in reg if r["residual_rating"] == k)  # noqa: E731
    hi_now = count(a.register, "Critical") + count(a.register, "High")
    hi_after = count(after.register, "Critical") + count(after.register, "High")
    reduction = 100 * (1 - after.total_residual() / a.total_residual())
    weakest = min(a.maturity(), key=a.maturity().get)
    top = roadmap[:top_n]
    gov_gaps = [c["title"][0].lower() + c["title"][1:] for c in a.controls.values()
                if c["function"] == "Govern" and c["status"] == "not_implemented"]
    gov_note = f" Missing governance controls ({'; '.join(e(g) for g in gov_gaps)}) leave risks without clear ownership." if gov_gaps else ""
    effort_mix = ", ".join(f"{sum(1 for x in top if x['effort'] == k)} {lbl}" for k, lbl in
                           [("S", "small"), ("M", "medium"), ("L", "large")] if any(x["effort"] == k for x in top))
    risk_rows = "".join(
        f"<tr><td class=m>{e(r['id'])}</td><td>{e(r['scenario'])}</td>"
        f"<td><span class=b style='background:{RATING_COLOR[r['inherent_rating']]}'>{r['inherent_score']}</span></td>"
        f"<td><span class=b style='background:{RATING_COLOR[r['residual_rating']]}'>{r['residual_score']} {e(r['residual_rating'])}</span></td>"
        f"<td class=s>{e(', '.join(r['control_gaps']))}</td></tr>" for r in a.register)
    road_rows = "".join(
        f"<tr><td class=m>{i + 1}</td><td class=m>{e(x['control'])}</td><td>{e(x['title'])}</td><td>{e(x['effort'])}</td>"
        f"<td>{e(x['owner'])}</td><td>−{x['risk_reduction']}</td><td class=s>{e(', '.join(x['risks_addressed']))}</td></tr>"
        for i, x in enumerate(roadmap[:8]))
    return f"""<!doctype html><html lang=en><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>Cyber Risk Assessment</title><style>
body{{margin:0;background:#f6f7f9;color:#101828;font-family:Inter,system-ui,-apple-system,Segoe UI,sans-serif}}
.w{{max-width:1120px;margin:0 auto;padding:28px 20px}}h1{{margin:0;font-size:25px}}h2{{font-size:17px;margin:0 0 12px}}
.sub{{color:#667085;font-size:14px;margin-top:4px}}.c{{background:#fff;border:1px solid #e4e7ec;border-radius:14px;padding:18px 20px;margin-top:16px}}
.g{{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:14px;margin-top:18px}}
.k{{color:#667085;font-size:13px}}.v{{font-size:30px;font-weight:800;margin-top:4px}}
table{{width:100%;border-collapse:collapse;font-size:13.5px}}td,th{{text-align:left;padding:9px 8px;border-bottom:1px solid #eef0f3;vertical-align:top}}
th{{font-size:12px;text-transform:uppercase;color:#667085;letter-spacing:.04em}}.m{{font-family:ui-monospace,Menlo,monospace;white-space:nowrap}}
.s{{color:#475467;font-size:12.5px}}.b{{color:#fff;font-weight:700;border-radius:6px;padding:2px 7px;font-size:12px;white-space:nowrap}}
img{{width:100%;height:auto}}ul{{margin:6px 0 0;padding-left:20px;line-height:1.6}}
</style></head><body><div class=w>
<h1>Cyber Risk Assessment: {e(a.org['name'])}</h1>
<div class=sub>{e(a.org['sector'])} · {e(a.org['location'])} · Framework: NIST CSF 2.0 · {date.today():%B %d, %Y}</div>
<div class=g>
 <div class=c><div class=k>High or critical residual risks</div><div class=v style="color:#b42318">{hi_now}</div></div>
 <div class=c><div class=k>After top-{top_n} roadmap items</div><div class=v style="color:#067647">{hi_after}</div></div>
 <div class=c><div class=k>Total residual risk reduction</div><div class=v>{reduction:.0f}%</div></div>
 <div class=c><div class=k>Weakest CSF function</div><div class=v>{e(weakest)}</div></div>
</div>
<div class=c><h2>Executive summary</h2><ul>
 <li>{hi_now} of {len(a.register)} risk scenarios remain <b>high or critical</b> after existing controls. The largest is <b>{e(a.register[0]['scenario'].lower())}</b> (residual score {a.register[0]['residual_score']} of 25).</li>
 <li>Control maturity is lowest in <b>{e(weakest)}</b> ({a.maturity()[weakest]:.0%} implemented).{gov_note}</li>
 <li>Implementing the <b>top {top_n} roadmap items</b> ({effort_mix} effort) cuts total residual risk by <b>{reduction:.0f}%</b> and reduces high or critical risks from {hi_now} to {hi_after}.</li>
 <li>Risk appetite: <i>{e(a.org['risk_appetite'])}</i></li>
</ul></div>
<div class=c><h2>Risk heat maps</h2>{_img(imgs['heatmaps'])}</div>
<div class=c><h2>Risk register</h2><table><tr><th>ID</th><th>Scenario</th><th>Inherent</th><th>Residual</th><th>Control gaps</th></tr>{risk_rows}</table></div>
<div class=c><h2>Prioritized remediation roadmap</h2><div class=sub style="margin:-6px 0 10px">Ranked by residual-risk reduction per unit of effort</div>
<table><tr><th>#</th><th>Control</th><th>Action</th><th>Effort</th><th>Owner</th><th>Risk ↓</th><th>Risks</th></tr>{road_rows}</table></div>
<div class=c><h2>Control maturity</h2>{_img(imgs['maturity'])}</div>
</div></body></html>"""


def build_all(a: Assessment, out: Path, top_n: int = 5) -> dict[str, Path]:
    out.mkdir(parents=True, exist_ok=True)
    roadmap = a.roadmap()
    after = a.with_controls_implemented([x["control"] for x in roadmap[:top_n]])
    imgs = {"heatmaps": heatmaps(a, after, out / "heatmaps.png"), "maturity": maturity_chart(a, out / "csf_maturity.png")}
    csv_path, xlsx_path = write_register(a, roadmap, out)
    html_path = out / "executive_report.html"
    html_path.write_text(executive_html(a, after, roadmap, top_n, imgs))
    return {**imgs, "csv": csv_path, "xlsx": xlsx_path, "html": html_path}
