"""
Orchestrated pipeline: P&ID + SCD  ->  graph  ->  analyses  ->  reports.

Run:
    python src/main.py                      # defaults to the HO27 pair
    python src/main.py 27                    # any system present in data/raw
    python src/main.py P&ID/foo.pdf SCD/bar.pdf   # explicit files

Everything below reuses the modules in extraction/, analysis/, ai/.
"""
from __future__ import annotations
import sys, os
from pathlib import Path

# make src/ importable no matter where we're run from
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import PID_DIR, SCD_DIR, REPORTS, AI_REPORTS
from extraction.pdf_parser import diagnose
from extraction.tag_extractor import extract_tags, create_objects
from analysis.build_dependency_graph import build_graph, save_png, save_json, save_html
from analysis.consistency_check import check_consistency, write_flagged_issues
from analysis.kpi_analysis import compute_kpis, quality_flags
from analysis.analyze_scd import safety_register, failure_propagation
from ai.explain_system import explain_system
import csv


def _find(directory: Path, system: str) -> Path | None:
    hits = sorted(directory.glob(f"*H*{system}*.PDF")) + \
           sorted(directory.glob(f"*H*{system}*.pdf"))
    return hits[0] if hits else None


def resolve_inputs(argv) -> tuple[Path, Path, str]:
    if len(argv) == 3:                       # explicit files
        return (PID_DIR.parent / argv[1], SCD_DIR.parent / argv[2], "custom")
    system = argv[1] if len(argv) == 2 else "27"
    pid, scd = _find(PID_DIR, system), _find(SCD_DIR, system)
    if not pid or not scd:
        sys.exit(f"Could not find a P&ID and SCD for system {system} "
                 f"in {PID_DIR} and {SCD_DIR}")
    return pid, scd, system


def main():
    pid_pdf, scd_pdf, system = resolve_inputs(sys.argv)
    REPORTS.mkdir(parents=True, exist_ok=True)
    print(f"System {system}\n  P&ID: {pid_pdf.name}\n  SCD : {scd_pdf.name}\n")

    # 1. diagnose
    for p in (pid_pdf, scd_pdf):
        print("  diagnose:", diagnose(p)["verdict"], "-", p.name)

    # 2. extract -> objects
    pid_objs = create_objects(extract_tags(pid_pdf), "P&ID")
    scd_objs = create_objects(extract_tags(scd_pdf), "SCD")
    all_objs = sorted(set(pid_objs) | set(scd_objs), key=lambda o: o.tag)
    print(f"\n  P&ID tags: {len(pid_objs)}   SCD tags: {len(scd_objs)}   "
          f"union: {len(all_objs)}")

    # 3. graph
    graph = build_graph(all_objs)
    save_png(graph, REPORTS / "system_dependency_graph.png", f"System {system}")
    save_json(graph, REPORTS / "system_dependency_graph.json")
    save_html(graph, REPORTS / "system_dependency_graph.html", f"System {system}")

    # 4. consistency + flags
    cons = check_consistency(pid_objs, scd_objs)
    write_flagged_issues(cons, REPORTS / "flagged_issues.csv")
    print(f"  consistency: both={len(cons['both'])}  "
          f"P&ID-only={len(cons['pid_only'])}  SCD-only={len(cons['scd_only'])}")

    # 5. KPIs + quality report
    kpis = compute_kpis(graph, all_objs)
    flags = quality_flags(all_objs)
    _write_quality_report(system, kpis, cons, flags, REPORTS / "quality_report.md")

    # 6. tags.csv + safety register
    _write_tags_csv(all_objs, REPORTS / "tags.csv")
    safety = safety_register(all_objs, REPORTS / "safety_register.csv")
    print(f"  safety-related tags: {len(safety)}")

    # 7. failure-propagation demo on one input
    demo_tag = next((o.tag for o in pid_objs if o.category == "input"), None)
    if demo_tag:
        fp = failure_propagation(graph, demo_tag)
        print(f"\n  failure demo - if {demo_tag} fails -> "
              f"affects {len(fp['all_affected'])} tag(s), "
              f"{len(fp['safety_functions_affected'])} safety function(s)")

    # 8. AI (or templated) summary
    explain_system(system, kpis, cons, AI_REPORTS)

    print(f"\nDone. Reports written to {REPORTS}/")


def _write_tags_csv(objs, path):
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["tag", "system", "type", "number", "category", "source"])
        for o in objs:
            w.writerow([o.tag, o.system, o.type_code, o.number, o.category, o.source])


def _write_quality_report(system, kpis, cons, flags, path):
    c = kpis["by_category"]
    lines = [
        f"# System {system} - quality report\n",
        f"Components: **{kpis['components']}** "
        f"(input {c.get('input',0)}, logic {c.get('logic',0)}, "
        f"output {c.get('output',0)}, equipment {c.get('equipment',0)})  ",
        f"Functional loops: **{kpis['functional_loops']}**  ",
        f"Connections: **{kpis['connections']}**\n",
        "## Consistency P&ID vs SCD",
        f"- On both: {len(cons['both'])}",
        f"- SCD-only (verify): {len(cons['scd_only'])} -> {cons['scd_only']}",
        f"- P&ID-only (usually expected): {len(cons['pid_only'])}\n",
        "## Quality flags",
    ]
    lines += [f"- {fl}" for fl in flags] or ["- none"]
    lines += ["\n_Draft from AI-extracted data - verify against source drawings._"]
    path.write_text("\n".join(lines))


if __name__ == "__main__":
    main()