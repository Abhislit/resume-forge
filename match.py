"""Match JD requirements against the user's canonical profile.

profile.md is authoritative and read-only to this module. Every 'covered' claim
carries the evidence line it was matched from, so a match is always traceable to
something the user actually wrote.
"""

import re

COVERED = "covered"
PARTIAL = "partial"
GAP = "gap"

# Explicit synonym map. A real cover that reads "k8s" against a posting that
# says "Kubernetes" must not read as a gap. No embedding model — a false
# negative here costs the user one click in the UI, and a large dependency to
# remove it is a bad trade.
SYNONYMS = {
    "k8s": "kubernetes",
    "kubernetes": "kubernetes",
    "postgres": "postgresql",
    "postgresql": "postgresql",
    "psql": "postgresql",
    "js": "javascript",
    "ecmascript": "javascript",
    "ts": "typescript",
    "node": "nodejs",
    "node js": "nodejs",
    "nodejs": "nodejs",
    "nextjs": "next.js",
    "next js": "next.js",
    "next.js": "next.js",
    "golang": "go",
    "ml": "machine learning",
    "machine learning": "machine learning",
    "dl": "deep learning",
    "deep learning": "deep learning",
    "llms": "llm",
    "nlp": "nlp",
    "ci cd": "ci/cd",
    "cicd": "ci/cd",
    "continuous integration": "ci/cd",
    "rest api": "rest",
    "rest apis": "rest",
    "restful": "rest",
    "rest": "rest",
    "graphql": "graphql",
    "gql": "graphql",
    "powerbi": "power bi",
    "bi": "power bi",
    "ab testing": "a/b testing",
    "experimentation": "a/b testing",
    "agile methodologies": "agile",
    "scrum": "scrum",
    "kanban": "kanban",
    "stakeholder management": "stakeholder management",
    "cross functional": "cross-functional collaboration",
    "product roadmap": "roadmap",
    "roadmapping": "roadmap",
    "microservice": "microservices",
    "cloud": "aws",
    "infrastructure as code": "terraform",
    "iac": "terraform",
    "ux": "wireframing",
    "ui ux": "wireframing",
    "figma": "figma",
    "statistics": "statistics",
    "data analysis": "analytics",
    "data analytics": "analytics",
    "business intelligence": "analytics",
    "tableau": "tableau",
    "looker": "looker",
    "jira": "jira",
    "confluence": "confluence",
    "version control": "git",
    "code review": "code review",
    "pair programming": "pair programming",
    "oop": "object-oriented programming",
    "dsa": "data structures and algorithms",
    "data structures": "data structures and algorithms",
    "system design": "system design",
}

# Terms that imply the user does adjacent work — a partial, which the user then
# confirms or corrects. Kept short on purpose: a long fuzzy list produces
# confident nonsense.
ADJACENT = {
    "leadership": ("mentored", "led a team", "ownership", "directed"),
    "mentoring": ("coached", "onboarded", "mentored", "trained"),
    "communication": ("presented", "stakeholder", "documented", "wrote"),
    "stakeholder management": ("stakeholder", "cross-functional", "partnered"),
    "agile": ("sprint", "iteration", "standup"),
    "scrum": ("sprint", "backlog refinement"),
    "system design": ("architected", "architecture", "design doc"),
    "microservices": ("service", "api", "distributed"),
    "distributed systems": ("distributed", "consistency", "sharding"),
    "data modeling": ("schema", "data model", "normalized"),
    "analytics": ("metric", "dashboard", "analyzed", "analysis"),
    "machine learning": ("model", "training", "inference", "dataset"),
    "security": ("oauth", "auth", "encryption", "compliance", "pci", "soc2"),
    "compliance": ("compliance", "audit", "gdpr", "soc2", "pci"),
    "automation": ("automated", "automation", "script"),
    "mentorship": ("mentor", "coach"),
}

_EVIDENCE_STOP = {
    "and", "the", "for", "with", "our", "you", "your", "will", "have", "are",
    "this", "that", "from", "who", "all", "can", "not", "but", "they", "them",
    "their", "there", "what", "when", "where", "which", "while", "about",
}


def _canon(term):
    """Same normalization as parse._canonical — the two must agree, or a term
    extracted from the posting will never match the profile copy of itself."""
    t = str(term).strip().lower().strip(".,;:()[]{}*\"'")
    t = re.sub(r"\s+", " ", t)
    # A word in the synonym map is a whole word, never a plural to strip:
    # "Kubernetes" -> "kubernete" would match nothing at all.
    if t in SYNONYMS:
        return SYNONYMS[t]
    if t.endswith("ies") and len(t) > 4:
        t = t[:-3] + "y"
    elif t.endswith("s") and not t.endswith("ss") and len(t) > 3:
        t = t[:-1]
    return SYNONYMS.get(t, t)


def parse_profile(text):
    """Split profile.md into (preferences, roles, skill_terms, evidence_lines).

    Deliberately structural rather than clever: a `###` heading starts a role,
    `- ` lines under it are that role's bullets/facts, and every non-heading
    line is candidate evidence.
    """
    preferences = {}
    roles = []
    skill_terms = set()
    evidence = []
    section = None
    current_role = None

    for raw in (text or "").replace("\r\n", "\n").split("\n"):
        line = raw.strip()
        if not line:
            continue

        if line.startswith("###"):
            current_role = {
                "title": line.lstrip("#").strip(),
                "lines": [],
            }
            roles.append(current_role)
            section = "role"
            continue

        if line.startswith("##"):
            section = line.lstrip("#").strip().lower()
            current_role = None
            continue

        if line.startswith("#"):
            section = "header"
            current_role = None
            continue

        clean = re.sub(r"^\s*[-*•]\s*", "", line).strip()
        if not clean:
            continue

        if section in ("preferences", "preference"):
            if ":" in clean:
                k, v = clean.split(":", 1)
                preferences[k.strip().lower()] = v.strip()
            continue

        if section in ("skills", "tech", "technical skills", "tools"):
            for tok in re.split(r"[,;|]", clean):
                c = _canon(tok)
                if c and len(c) > 1 and c not in _EVIDENCE_STOP:
                    skill_terms.add(c)
            continue

        if current_role is not None:
            current_role["lines"].append(clean)

        evidence.append(clean)

    # Roles' own content is evidence for skill terms too.
    for role in roles:
        blob = " ".join(role["lines"]).lower()
        for tok in re.split(r"[^a-z0-9+#./-]+", blob):
            c = _canon(tok)
            if c and len(c) > 1:
                skill_terms.add(c)

    return {
        "preferences": preferences,
        "roles": roles,
        "skills": skill_terms,
        "evidence": evidence,
        "profile_text": (text or "").lower(),
    }


def _find_evidence(term, profile, limit=2):
    """Lines in the profile that support this term, verbatim."""
    t = _canon(term)
    if not t:
        return []
    hits = []
    # Word-boundary-ish match, allowing compound tokens like "node.js".
    pattern = re.compile(rf"(?<![a-z0-9]){re.escape(t)}(?![a-z0-9])", re.IGNORECASE)
    for line in profile["evidence"]:
        if pattern.search(line.lower()):
            hits.append(line.strip())
            if len(hits) >= limit:
                break
    return hits


def _adjacent_evidence(term, profile, limit=1):
    cues = ADJACENT.get(_canon(term), ())
    if not cues:
        return []
    hits = []
    for line in profile["evidence"]:
        low = line.lower()
        if any(c in low for c in cues):
            hits.append(line.strip())
            if len(hits) >= limit:
                break
    return hits


def match(requirements, profile_text):
    """requirements x profile -> matrix rows.

    Row shape: {text, kind, terms, verbs, status, evidence, term_status}
    where term_status maps each extracted term to its own status, so the UI can
    show which word in a requirement is the weak one.
    """
    profile = parse_profile(profile_text)

    rows = []
    for req in requirements:
        terms = req.get("terms", [])
        term_status = {}
        evidence = []

        for term in terms:
            c = _canon(term)
            found = _find_evidence(c, profile)
            if found or c in profile["skills"]:
                term_status[term] = COVERED
                evidence.extend(found or [f"listed under skills: {c}"])
                continue

            adj = _adjacent_evidence(c, profile)
            if adj:
                term_status[term] = PARTIAL
                evidence.append(adj[0])
                continue

            term_status[term] = GAP

        if not term_status:
            status = GAP
        else:
            statuses = set(term_status.values())
            if statuses == {COVERED}:
                status = COVERED
            elif COVERED in statuses:
                status = PARTIAL
            elif statuses == {GAP}:
                status = GAP
            else:
                status = GAP if GAP in statuses else PARTIAL

        rows.append({
            "text": req["text"],
            "kind": req.get("kind", "required"),
            "terms": terms,
            "verbs": req.get("verbs", []),
            "status": status,
            "term_status": term_status,
            "evidence": list(dict.fromkeys(evidence)),
        })

    return {
        "rows": rows,
        "profile": {
            "preferences": profile["preferences"],
            "roles": profile["roles"],
            "skill_count": len(profile["skills"]),
            "evidence_count": len(profile["evidence"]),
        },
    }


def guess_role(profile_text):
    """The role family this profile targets, for looking up learned history.

    Takes the most recent role heading, strips company and dates, and drops
    seniority words — "Senior Backend Engineer" and "Backend Engineer" should
    find the same history.
    """
    for role in parse_profile(profile_text)["roles"]:
        title = role["title"].split("|")[0].strip()
        title = re.sub(
            r"\b(senior|sr|staff|principal|lead|junior|jr|entry|intern|"
            r"i|ii|iii|head of|director|vp|chief)\b",
            "",
            title,
            flags=re.IGNORECASE,
        )
        title = re.sub(r"\s+", " ", title).strip(" -|,.")
        if len(title) > 3:
            return title
    return ""


def summary(matrix):
    """Counts for the UI header."""
    rows = matrix["rows"]
    counts = {COVERED: 0, PARTIAL: 0, GAP: 0}
    for r in rows:
        counts[r["status"]] += 1
    required = [r for r in rows if r["kind"] == "required"]
    req_covered = sum(1 for r in required if r["status"] == COVERED)
    return {
        "total": len(rows),
        "covered": counts[COVERED],
        "partial": counts[PARTIAL],
        "gap": counts[GAP],
        "required_total": len(required),
        "required_covered": req_covered,
    }


def open_items(matrix, weights=None):
    """Everything the user still has to answer, worst first.

    With learned weights, a gap on a term that keeps recurring across postings
    outranks a gap on a term seen once. That is the archive doing its job.
    """
    weights = weights or {}
    items = []
    for r in matrix["rows"]:
        if r["status"] == COVERED:
            continue
        missing = [t for t, s in r["term_status"].items() if s != COVERED]
        items.append({
            "text": r["text"],
            "kind": r["kind"],
            "status": r["status"],
            "missing": missing,
            "weights": {t: weights.get(t, 0.0) for t in missing},
            "adjacent_evidence": r["evidence"] if r["status"] == PARTIAL else [],
        })
    order = {GAP: 0, PARTIAL: 1}

    def rank(item):
        top = max(item["weights"].values(), default=0.0)
        return (
            order.get(item["status"], 2),
            item["kind"] != "required",
            -top,
        )

    items.sort(key=rank)
    return items