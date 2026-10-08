"""Extract structured requirements from a job description.

Deliberately heuristic: this is a first pass whose output the user corrects in
the UI, not a universal JD parser.
"""

import io
import re
import urllib.request
import zipfile
import xml.etree.ElementTree as ET

REQUIRED = "required"
PREFERRED = "preferred"

_W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

# Markers that flip a requirement line's polarity. Checked in order; required
# markers win over preferred ones so a term listed under both counts as required.
_REQUIRED_MARKERS = (
    "required", "requirement", "must have", "must-have", "you have",
    "you will have", "you must", "minimum", "at least", "essential",
    "need to have", "should have", "solid understanding of", "proficiency in",
    "experience with", "knowledge of", "familiar with", "ability to",
)
_PREFERRED_MARKERS = (
    "bonus", "plus", "preferred", "nice to have", "nice-to-have",
    "desirable", "a plus", "good to have", "ideally", "optional",
    "familiarity with", "exposure to", "interest in",
)

# Section headings in a posting that scope the lines beneath them.
_SECTION_RE = re.compile(
    r"^\s*(?:#{1,4}\s*)?(minimum qualifications|basic qualifications|"
    r"required qualifications|required|requirements|must have|minimum|"
    r"what you.ll need|who you are|"
    r"preferred qualifications|bonus qualifications|nice to have|preferred|"
    r"bonus|pluses|desired|"
    r"responsibilities|what you.ll do|duties|about the role|"
    r"qualifications|skills|requirements & qualifications)\s*:?\s*$",
    re.IGNORECASE,
)

_BULLET_RE = re.compile(r"^\s*(?:[-*•·–]|\d+[.)])\s*")
_MIN_LINE_CHARS = 25

# Canonical tech vocabulary. Terms outside this list still get picked up by the
# capitalization heuristic below; this just catches the lowercase ones.
_SKILL_LEXICON = {
    "python", "java", "javascript", "typescript", "go", "golang", "rust",
    "c++", "c#", "ruby", "php", "scala", "kotlin", "swift", "elixir", "r",
    "sql", "nosql", "bash", "r",
    "react", "angular", "vue", "svelte", "next.js", "nextjs", "django",
    "flask", "fastapi", "express", "rails", "spring", "spring boot", "dotnet",
    "node", "node.js", "nodejs", "redux",
    "kubernetes", "k8s", "docker", "terraform", "ansible", "helm",
    "aws", "gcp", "azure", "lambda", "s3", "ec2", "eks", "gke",
    "postgres", "postgresql", "mysql", "mongodb", "redis", "kafka",
    "elasticsearch", "cassandra", "dynamodb", "sqlite",
    "pandas", "numpy", "pytorch", "tensorflow", "spark", "hadoop",
    "airflow", "dbt", "snowflake", "bigquery", "redshift",
    "git", "github", "gitlab", "jenkins", "ci/cd", "linux", "unix",
    "graphql", "rest", "rest api", "rest apis", "grpc", "grpc api",
    "microservices", "api", "apis",
    "agile", "scrum", "kanban", "jira", "confluence",
    "figma", "sketch", "wireframe", "wireframing", "prototyping",
    "machine learning", "ml", "deep learning", "nlp", "llm", "ai",
    "statistics", "a/b testing", "experimentation", "analytics",
    "tableau", "power bi", "looker", "excel", "salesforce",
    "leadership", "mentoring", "stakeholder management", "communication",
    "product management", "roadmap", "strategy", "roadmapping",
    "security", "compliance", "oauth", "authentication", "authorization",
    "distributed systems", "system design", "data modeling",
}

_STOPWORDS = {
    "the", "and", "with", "for", "our", "you", "your", "will", "have", "are",
    "this", "that", "from", "who", "all", "can", "not", "but", "they", "them",
    "their", "there", "here", "what", "when", "where", "which", "while",
    "about", "other", "others", "such", "other", "using", "use", "used",
    "including", "include", "includes", "etc", "well", "good", "strong",
    "excellent", "plus", "must", "should", "would", "could", "able",
    "years", "year", "experience", "work", "working", "ability", "knowledge",
    "understanding", "familiar", "solid", "proven", "track", "record",
    "building", "build", "develop", "developing", "development",
    "candidate", "candidates", "role", "roles", "position", "team", "teams",
    "company", "workplace", "environment", "job", "jobs", "employer",
    "opportunity", "benefits", "salary", "please", "apply", "email",
    "responsibilities", "qualifications", "requirements", "skills", "must",
}

# Verbs the posting uses; these signal what the role emphasizes.
_ACTION_VERBS = set("""
lead lead led manage managed manage build built build drive drove own owned
develop developed engineer engineered design designed architect architected
implement implemented ship shipped deliver delivered create created
implement improved improve optimize optimized optimise scale scaled migrate
migrated automate automated mentor mentored coach coached collaborate
collaborated partner partnered analyze analyzed analyse research researched
review reviewed refactor refactored integrate integrated deploy deployed
""".split())

_CAP_PHRASE_RE = re.compile(r"\b([A-Z][A-Za-z0-9+#./]*(?:\s+[A-Z][A-Za-z0-9+#./]*)*)\b")
_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9+#./-]*")


# Words that mark a capitalized phrase as an organization rather than a skill.
# "Globex Corporation" and "Acme Technologies" are the company, and reporting
# either as a requirement is pure noise.
_ORG_WORDS = {
    "corp", "corporation", "inc", "incorporated", "llc", "ltd", "plc", "gmbh",
    "co", "company", "group", "holdings", "holding", "labs", "technologies",
    "technology", "solutions", "systems", "ventures", "partners", "studios",
    "university", "college", "institute", "foundation", "association",
    "department", "ministry", "agency", "authority", "council", "committee",
    "team", "teams", "division", "business", "sector", "industry",
}

# A job title is not a skill either. "Platform Engineer" extracted from a
# posting is the role being advertised.
_ROLE_WORDS = {
    "engineer", "engineering", "manager", "management", "developer",
    "analyst", "designer", "scientist", "architect", "consultant",
    "specialist", "administrator", "scientist", "intern", "apprentice",
    "recruiter", "advisor", "coordinator", "officer", "president", "owner",
    "founder", "vp", "sre", "devops", "programmer", "technician",
}

# Adjectives that lead a capitalized tech name. "Expert COBOL" is COBOL.
_MODIFIER_WORDS = {
    "expert", "strong", "senior", "solid", "proven", "advanced", "excellent",
    "deep", "hands", "on", "working", "familiar", "proficient", "extensive",
    "demonstrated", "proven", "proven", "core", "key", "primary", "main",
    "modern", "real", "time", "high", "low", "level", "large", "small",
}


def _canonical(term: str) -> str:
    """Lowercase, strip punctuation noise, singularize easy plurals.

    A lexicon hit is returned untouched: "Kubernetes" ends in "s" but is not a
    plural, and stripping it yields "kubernete", which then matches nothing.
    """
    t = term.strip().lower().strip(".,;:()[]{}")
    t = re.sub(r"\s+", " ", t)
    if t in _SKILL_LEXICON:
        return t
    if t.endswith("ies") and len(t) > 4:
        t = t[:-3] + "y"
    elif t.endswith("s") and not t.endswith("ss") and len(t) > 3:
        t = t[:-1]
    return t


def _normalize_keyword(term: str) -> str:
    """Canonical form used for matching and for emitting to the draft."""
    return _canonical(term)


def _section_kind(text: str):
    """Map a heading to ('required'|'preferred'|None). None means neutral."""
    low = text.strip().lower()
    if low.startswith(("preferred", "bonus", "nice to have", "nice-to-have",
                       "desirable", "pluses", "desired")):
        return PREFERRED
    if low.startswith(("minimum", "required", "must have", "what you",
                       "basic", "who you are", "requirements", "qualifications",
                       "skills")):
        return REQUIRED
    return None


def _line_polarity(line: str) -> str:
    """Classify a single requirement line. Default is REQUIRED.

    A posting lists the things it cannot work without first, so absent explicit
    markers the safe read is that the line is a hard requirement.
    """
    low = line.lower()
    # Required markers are checked first: a line saying "3+ years Python, AWS
    # exposure a plus" must land on required.
    if any(m in low for m in _REQUIRED_MARKERS):
        return REQUIRED
    if any(m in low for m in _PREFERRED_MARKERS):
        return PREFERRED
    return REQUIRED


def _extract_terms(line: str):
    """Pull skill candidates out of one requirement line."""
    found = set()

    for tok in _TOKEN_RE.findall(line.lower()):
        c = _canonical(tok)
        if c in _SKILL_LEXICON and c not in _STOPWORDS:
            found.add(c)

    # Multi-word lexicon entries next, so "machine learning" wins over "machine"
    # and "rest api" wins over a bare "api" that would then read as a gap.
    low = line.lower()
    for skill in _SKILL_LEXICON:
        if " " in skill and skill in low:
            found.add(skill)
            for word in skill.split():
                found.discard(word)

    # Capitalized phrases: proper nouns and branded tools. A word is only
    # evidence of a skill if it is capitalized somewhere other than the start of
    # the line — "Production experience with Kubernetes" means Kubernetes, and
    # "Familiarity with Terraform is a plus" means Terraform. Sentence-initial
    # capitalization carries no signal, so the first word is always skipped.
    for m in _CAP_PHRASE_RE.finditer(line):
        phrase = m.group(1).strip()
        if m.start() == 0 and " " not in phrase:
            continue
        c = _canonical(phrase)
        if c in _STOPWORDS or len(c) < 2:
            continue
        words = c.split()
        # Reject phrases whose words are all stopwords ("The Team" -> "team"),
        # keep anything with a real token in it.
        if all(w in _STOPWORDS for w in words):
            continue
        # A phrase naming an organization is the employer, not a requirement.
        if any(w in _ORG_WORDS for w in words):
            continue
        # A phrase naming a role is the job being advertised, not a skill.
        if any(w in _ROLE_WORDS for w in words):
            continue
        if len(words) > 4:
            continue
        # Keep only the words that are themselves known terms. "Expert Kafka" is one
        # term, Kafka. If no word is in the lexicon, drop the leading
        # adjectives instead — "Expert COBOL" is COBOL, and COBOL is a real
        # technology even though the lexicon has never heard of it.
        keep = [w for w in words if w in _SKILL_LEXICON]
        if len(keep) == 1:
            found.add(keep[0])
            continue
        if keep:
            continue
        tail = [w for w in words if w not in _MODIFIER_WORDS]
        if len(tail) == 1:
            found.add(tail[0])
        continue

    # Drop noise: single common words that slipped through capitalization.
    return {t for t in found if t not in _STOPWORDS and len(t) > 1}


def read_docx(path_or_bytes):
    """Read word/document.xml out of a .docx (it is just a zip)."""
    data = path_or_bytes
    if isinstance(data, (bytes, bytearray)):
        zf = zipfile.ZipFile(io.BytesIO(data))
    else:
        zf = zipfile.ZipFile(data)
    with zf.open("word/document.xml") as fh:
        xml = fh.read()
    root = ET.fromstring(xml)

    paragraphs = []
    for p in root.iter(_W_NS + "p"):
        texts = [t.text or "" for t in p.iter(_W_NS + "t")]
        paragraphs.append("".join(texts))
    return "\n".join(paragraphs)


def fetch_url(url, timeout=15):
    """Fetch a posting as text. Best effort; a block is not a crash."""
    req = urllib.request.Request(
        url, headers={"User-Agent": "Mozilla/5.0 (resume-forge)"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    charset = resp.headers.get_content_charset() or "utf-8"
    html = raw.decode(charset, errors="replace")

    # Strip script/style, then tags. Deliberately crude — the alternative is an
    # HTML parser dependency, and the requirement lines survive this fine.
    html = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", html)
    html = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</li>|</h[1-6]>", "\n", html)
    text = re.sub(r"(?s)<[^>]+>", " ", html)
    text = (
        text.replace("&nbsp;", " ").replace("&amp;", "&")
        .replace("&lt;", "<").replace("&gt;", ">").replace("&#39;", "'")
        .replace("&quot;", '"')
    )
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n", text).strip()


def parse(text):
    """JD text -> list of {text, kind, terms, verbs}.

    Section headings scope their lines; a requirement appearing under both a
    required and a preferred heading resolves to required.
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    requirements = []
    current_kind = None
    seen_terms = {}
    saw_heading = False

    for raw_line in text.split("\n"):
        line = raw_line.strip()
        if not line:
            continue

        if _SECTION_RE.match(line):
            current_kind = _section_kind(line)
            saw_heading = True
            continue

        if _BULLET_RE.match(line):
            # Strip the marker before anything reads position 0 — otherwise the
            # sentence-initial capitalization check sees "-" and treats the first
            # real word as mid-sentence.
            line = _BULLET_RE.sub("", line)
        else:
            # Prose is only mined when the document has structure to say where
            # requirements begin. With no headings at all, an unbulleted JD
            # would otherwise yield nothing.
            if current_kind is None and saw_heading:
                continue
            if not _BULLET_RE.match(raw_line.strip()) and saw_heading:
                continue

        if len(line) < _MIN_LINE_CHARS:
            # Short lines are usually headings and stray fragments, but a short
            # requirement is often the hard one — "Kubernetes in production" is
            # 24 characters and more important than most long ones. Keep it if
            # it names something the lexicon recognizes.
            if not (set(_extract_terms(line)) & set(_SKILL_LEXICON)):
                continue

        kind = _line_polarity(line) if current_kind in (None, REQUIRED) else current_kind
        # A line inside a preferred section stays preferred unless it carries an
        # explicit required marker.
        if current_kind == PREFERRED and kind == REQUIRED:
            kind = PREFERRED

        terms = sorted(_extract_terms(line))
        if not terms:
            continue

        verbs = sorted({
            _canonical(v) for v in _ACTION_VERBS
            if re.search(rf"\b{re.escape(v)}\w*\b", line.lower())
        })

        requirements.append({
            "text": line,
            "kind": kind,
            "terms": terms,
            "verbs": verbs,
        })

        # Stronger signal wins across duplicates of the same term.
        for t in terms:
            prev = seen_terms.get(t)
            if prev != REQUIRED:
                seen_terms[t] = REQUIRED if kind == REQUIRED else PREFERRED

    # Promote any term seen in a required context.
    for req in requirements:
        if any(seen_terms.get(t) == REQUIRED for t in req["terms"]):
            req["kind"] = REQUIRED

    return requirements


def keywords(requirements):
    """Flat term -> kind map across all requirements."""
    out = {}
    for req in requirements:
        for t in req["terms"]:
            if t not in out or req["kind"] == REQUIRED:
                out[t] = REQUIRED if req["kind"] == REQUIRED else out.get(t, PREFERRED)
    return out