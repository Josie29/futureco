import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

EVS_BASE = "https://api-evsrest.nci.nih.gov/api/v1/concept/snomedct_us"
ANATOMY_PATH = Path(__file__).resolve().parents[1] / "data" / "authored" / "anatomy.json"


def _search(term: str, match_type: str | None) -> tuple[str, str] | None:
    """Run one EVS search and return the top concept, if any."""
    params = {"term": term, "pageSize": 1}
    if match_type:
        params["type"] = match_type
    query = urllib.parse.urlencode(params)
    with urllib.request.urlopen(f"{EVS_BASE}/search?{query}", timeout=30) as response:
        concepts = json.load(response).get("concepts", [])
    return (concepts[0]["code"], concepts[0]["name"]) if concepts else None


def resolve(term: str) -> tuple[str, str, str] | None:
    """Look an anatomical term up in SNOMED CT via the NCI EVS API.

    SNOMED names body structures inconsistently — some concepts read
    "Knee joint structure", others "Structure of patellofemoral joint" — so an
    exact match is attempted against both forms before falling back to a
    ranked search.

    Args:
        term: Base anatomical term, e.g. "patellofemoral joint".

    Returns:
        `(code, preferred_term, strategy)` for the best match, or None if
        nothing matched. `strategy` names which attempt succeeded, so a
        loosely-matched row is visible rather than silently accepted.

    Raises:
        urllib.error.URLError: If EVS is unreachable.
    """
    attempts = (
        (f"{term} structure", "match", "exact"),
        (f"Structure of {term}", "match", "exact-inverted"),
        (f"{term} structure", None, "ranked"),
    )
    for query, match_type, strategy in attempts:
        found = _search(query, match_type)
        if found:
            return (*found, strategy)
    return None


def main() -> int:
    """Resolve every anatomy row against SNOMED CT and write the codes back.

    Re-running is also the verification pass: an already-populated file is
    rewritten with whatever EVS returns today, so a drifted code or a renamed
    concept shows up as a diff.

    Returns:
        0 if every row resolved, 1 if any did not.
    """
    rows = json.loads(ANATOMY_PATH.read_text())
    unresolved: list[str] = []

    for row in rows:
        match = resolve(row["snomed_query"])
        if match is None:
            unresolved.append(row["name"])
            row["snomed_code"] = None
            row["snomed_term"] = None
            continue
        row["snomed_code"], row["snomed_term"], strategy = match
        flag = "" if strategy == "exact" else f"  <- {strategy}"
        print(f"  {row['name']:<30} {row['snomed_code']:<12} {row['snomed_term']}{flag}")

    ANATOMY_PATH.write_text(json.dumps(rows, indent=2) + "\n")

    if unresolved:
        print(f"\nunresolved ({len(unresolved)}): {', '.join(unresolved)}", file=sys.stderr)
        return 1
    print(f"\nresolved all {len(rows)} structures")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
