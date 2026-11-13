#!/usr/bin/env python3
"""Materialize the manually reviewed Stage-1 shortlist and exclusion audit."""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path


SELECTED = {
    # Educational first-/second-order barrier tradition: origins, major definitions,
    # reviews, extensions, and empirical reassessments.
    "W1539492040": ("education-barriers", "Earliest retrieved dissertation using the first-/second-order distinction; origin candidate."),
    "W1968529788": ("education-barriers", "Canonical 1999 formulation of external first-order and internal second-order barriers."),
    "W1578143833": ("education-barriers", "Early empirical work on teacher beliefs accompanying the canonical formulation."),
    "W2097000295": ("education-barriers", "Influential early review of factors affecting teachers' ICT use."),
    "W2096294317": ("education-barriers", "Early empirical study of experienced teachers responding to technology change."),
    "W2151920968": ("education-barriers", "Influential argument that pedagogical beliefs remain a major integration frontier."),
    "W1966370548": ("education-barriers", "Highly cited synthesis of K-12 integration knowledge gaps and recommendations."),
    "W2122954012": ("education-barriers", "Influential literature review of ICT integration barriers."),
    "W2104647037": ("education-barriers", "Conceptual synthesis connecting knowledge, confidence, beliefs, and culture."),
    "W2159433048": ("education-barriers", "Highly cited empirical examination of beliefs and integration practices."),
    "W2146974309": ("education-barriers", "Introduces a third-order/design-oriented extension; important for avoiding conflation with divide levels."),
    "W1598919364": ("education-barriers", "Empirical extension beyond the dominant US setting."),
    "W2783413559": ("education-barriers", "Direct comparison of second- and third-order barriers where first-order barriers remain high."),
    "W2982032074": ("education-barriers", "Time-series evidence on persistence and change in integration barriers."),
    "W2979556548": ("education-barriers", "Empirical study focused on overcoming second-order barriers."),
    "W3193973490": ("education-barriers", "Transfers the distinction to K-12 online teaching conditions."),
    "W4386556327": ("education-barriers", "Multi-stakeholder evidence that first-order barriers remain consequential."),
    "W4416410471": ("education-barriers", "Recent review of publications from 2000–2024; included to assess cumulative extensions."),

    # Digital divide / inequality: origins, definitions, and conceptual development.
    "W2125728730": ("digital-inequality-origins", "Foundational 2001 shift from binary divide to differentiated inequality."),
    "W2612125261": ("digital-inequality-origins", "Published synthesis of unequal access and differentiated use."),
    "W2127081335": ("digital-inequality-origins", "Canonical second-level digital divide study focused on online skills."),
    "W2110873030": ("digital-inequality-origins", "Influential account of the divide as complex and dynamic."),
    "W2037830455": ("meaningful-effective-use", "Foundational effective-use argument explicitly moving beyond access."),
    "W2888949376": ("meaningful-effective-use", "Foundational book reframing access through social inclusion and use."),
    "W2157767588": ("digital-inequality-origins", "Critical reconsideration of popular and political divide framings."),
    "W1977037734": ("digital-inequality-origins", "Influential early cross-national treatment of access, information poverty, and participation."),
    "W1873175055": ("digital-inequality-origins", "Major book developing cumulative resource-and-appropriation inequalities."),
    "W1536831375": ("digital-inequality-review", "Influential review of digital-divide research directions."),
    "W2040484355": ("digital-inequality-review", "Highly cited assessment of achievements and shortcomings in divide research."),
    "W2168637053": ("digital-inclusion", "Empirical gradations-of-inclusion framework among young people."),
    "W2000304796": ("digital-skills-use", "Strong empirical evidence of differentiated use among young adults."),
    "W2025747271": ("divide-levels", "Explicit three-level model of access, capability, and outcomes; tests relations among levels."),
    "W1814389775": ("social-digital-relations", "Corresponding-fields model connecting social and digital exclusion."),
    "W1557790403": ("access-forms-of-use", "Empirical comparison moving from access to differentiated activities across devices."),
    "W2150326215": ("access-forms-of-use", "Multifaceted model showing access itself has several dimensions."),
    "W2268109066": ("divide-levels", "Canonical formulation of third-level inequalities in tangible benefits."),
    "W1984234945": ("digital-inequality-review", "Influential cross-domain review explaining why digital inequalities matter."),
    "W2508628588": ("outcomes", "Empirical differentiation of benefits and harms from internet use."),
    "W2735791018": ("digital-inequality-review", "Systematic review of determinants of skills, uses, and outcomes."),
    "W2585678387": ("cumulative-inequality", "Conceptual and empirical account of compound and sequential inequality."),
    "W2726236692": ("outcomes", "Empirical analysis of diverse outcomes of internet engagement."),
    "W2892254122": ("access", "Shows first-level inequalities persist as unequal material access after connectivity diffuses."),
    "W2895899893": ("digital-capital", "Conceptual extension from divides toward digital capital."),
    "W2940900846": ("digital-inequality-review", "Review extending three-level inequalities to AI, datafication, and platform contexts."),
    "W3034797898": ("meaningful-effective-use", "Direct conceptual treatment of meaningful internet use, skills, and socio-technical awareness."),
    "W3172861707": ("social-digital-relations", "Major synthetic book on social causes and consequences of digital inequalities."),
    "W4284880397": ("criticism-extension", "Global South critique introducing adverse digital incorporation beyond inclusion/exclusion."),

    # Skills, confidence, support, capabilities, organizations, and empirical breadth.
    "W2064582337": ("skills-confidence", "Concise access-plus-ability formulation leading to confident use."),
    "W2151303580": ("digital-skills", "Empirical reconceptualization and measurement of internet skills."),
    "W1993189109": ("skills-support-outcomes", "Links skills and sources of support to beneficial internet use."),
    "W1740027447": ("digital-skills", "Major validated multidimensional Internet Skills Scale."),
    "W2309695813": ("meaningful-connectivity", "Reframes inequality through multilevel meaningful connectivity."),
    "W2801186751": ("population-variation", "Strong study of access and skills among older adults."),
    "W2618164195": ("population-variation", "Empirical evidence on skills and uses among older adults."),
    "W2886224444": ("global-empirical", "Study separating motivation, access, skills, and use in Cuba."),
    "W2166659008": ("global-empirical", "Five-country model of social differences in internet use."),
    "W3047011259": ("outcomes", "Large empirical study separating access, skills, uses, and outcomes during COVID-19."),
    "W3171450345": ("global-empirical", "Developing-country study explicitly distinguishing connection, activities, and outcomes."),
    "W3195618163": ("outcomes-review", "Systematic evidence review of outcomes from gaining digital skills among young people."),
    "W2098879444": ("organizational-institutional", "Examines government initiatives and forms of capital affecting ICT utilization."),
    "W3127885541": ("global-organizational", "Indian study distinguishing adoption, access, capabilities, and usage barriers."),
    "W4210992515": ("global-organizational", "Institutional account of refugee women and grassroots digital inclusion in Kenya."),
    "W4400315705": ("capabilities", "Recent capabilities-divide study under structural discrimination."),
    "W3025069554": ("skills-social-context", "Biographical study stating access is necessary but insufficient and tracing literacy formation."),
    "W4311705858": ("capabilities-outcomes", "Empirical service-context study of access, capabilities, and outcomes."),
}


def oid_tail(value: str) -> str:
    return (value or "").rstrip("/").rsplit("/", 1)[-1]


def main() -> int:
    if len(sys.argv) != 3:
        raise SystemExit("usage: select_ict_access_stage1.py UNION_JSON OUTPUT_DIR")
    union_path, output_dir = Path(sys.argv[1]), Path(sys.argv[2])
    output_dir.mkdir(parents=True, exist_ok=True)
    records = json.loads(union_path.read_text(encoding="utf-8"))["records"]
    by_id = {oid_tail(r.get("openalex_id", "")): r for r in records}
    missing = sorted(set(SELECTED) - set(by_id))
    if missing:
        raise SystemExit(f"Selected IDs absent from union: {missing}")

    selected = []
    decisions = []
    for short_id, record in by_id.items():
        if short_id in SELECTED:
            strand, rationale = SELECTED[short_id]
            decision = "include"
            selected.append({**record, "strand": strand, "selection_rationale": rationale})
        else:
            strand = ""
            rationale = "Not selected after title/abstract review: duplicate version, lower centrality, narrow application, weak metadata, or insufficient fit within the bounded central-source corpus."
            decision = "exclude"
        decisions.append({
            "openalex_id": record.get("openalex_id"),
            "title": record.get("title"),
            "year": record.get("year"),
            "type": record.get("type"),
            "decision": decision,
            "strand": strand,
            "reason": rationale,
        })

    selected.sort(key=lambda r: (r.get("year") or 9999, r.get("title") or ""))
    decisions.sort(key=lambda r: (r["decision"] != "include", r.get("year") or 9999, r.get("title") or ""))
    (output_dir / "selected-sources.json").write_text(json.dumps({
        "method": "Manual title/abstract review informed by transparent triage; inclusion balances origins, reviews, empirical tests, criticisms, organizational conditions, populations, and research traditions.",
        "selected_count": len(selected),
        "records": selected,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    with (output_dir / "selection.csv").open("w", newline="", encoding="utf-8") as handle:
        fields = ["openalex_id", "title", "year", "type", "authors", "doi", "is_open_access", "has_abstract", "strand", "selection_rationale"]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in selected:
            writer.writerow({
                "openalex_id": row.get("openalex_id"),
                "title": row.get("title"),
                "year": row.get("year"),
                "type": row.get("type"),
                "authors": "; ".join(row.get("authors") or []),
                "doi": row.get("doi"),
                "is_open_access": row.get("is_open_access"),
                "has_abstract": bool(row.get("abstract")),
                "strand": row["strand"],
                "selection_rationale": row["selection_rationale"],
            })

    with (output_dir / "all-decisions.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(decisions[0]))
        writer.writeheader()
        writer.writerows(decisions)

    summary = {
        "screened_unique": len(records),
        "selected": len(selected),
        "selected_missing_abstract": sum(not bool(r.get("abstract")) for r in selected),
        "selected_open_access": sum(bool(r.get("is_open_access")) for r in selected),
        "by_strand": {},
    }
    for row in selected:
        summary["by_strand"][row["strand"]] = summary["by_strand"].get(row["strand"], 0) + 1
    (output_dir / "selection-summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
