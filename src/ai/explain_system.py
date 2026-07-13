"""Optional natural-language system summary. Falls back to a template if no key."""
from __future__ import annotations
import os
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()


def explain_system(system: str, kpis: dict, consistency: dict, out_dir: Path) -> Path:
    text = _llm_summary(system, kpis, consistency) if os.getenv("ANTHROPIC_API_KEY") \
        else _template_summary(system, kpis, consistency)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"system_{system}.md"
    path.write_text(text)
    return path


def _template_summary(system, kpis, consistency) -> str:
    c = kpis["by_category"]
    return (
        f"# System {system} - automated summary\n\n"
        f"- Components extracted: {kpis['components']} "
        f"(inputs {c.get('input',0)}, logic {c.get('logic',0)}, "
        f"outputs {c.get('output',0)}, equipment {c.get('equipment',0)})\n"
        f"- Functional loops: {kpis['functional_loops']}\n"
        f"- Tags on both P&ID and SCD: {len(consistency['both'])}\n"
        f"- Flagged (SCD-only, verify): {len(consistency['scd_only'])}\n\n"
        f"Most-connected tags (potential single points of dependency): "
        f"{', '.join(kpis['most_connected'])}\n\n"
        f"_Draft, generated from AI-extracted data. Verify against the source "
        f"drawings before use._\n"
    )


def _llm_summary(system, kpis, consistency) -> str:
    import anthropic
    prompt = (
        f"Summarise offshore system {system} for a mechanical engineer in 4-6 "
        f"sentences, from this extracted data. Be factual, flag uncertainty.\n\n"
        f"KPIs: {kpis}\nConsistency: {consistency}\n"
    )
    msg = anthropic.Anthropic().messages.create(
        model="claude-sonnet-4-6", max_tokens=600,
        messages=[{"role": "user", "content": prompt}])
    return f"# System {system} - AI summary\n\n{msg.content[0].text}\n"