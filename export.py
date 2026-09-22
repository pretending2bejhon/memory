"""export.py - vault-city data export (standard library only).

Walks the Obsidian vault at VAULT and writes data/vault-city.json with one
anonymous node per note (numeric id, district, subdistrict, week indices,
type, status, retrieval_count, inbound/outbound link counts) plus edges as
pairs of ids. No titles, filenames, paths or body text are ever stored or
printed.
"""
import os, re, json, datetime, collections

VAULT = r"C:\Users\jhona\TheSystem"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "vault-city.json")
ROOTS = ["00-core", "10-memory", "20-ventures", "30-jhon"]
SKIP_DIRS = {"95-data", "99-archive", "90-machinery", ".obsidian"}
WEEK0 = datetime.date(2026, 6, 29)       # Monday, week 0
LAST_WEEK = 12                            # 2026-09-21 is week 12 -> 13 frames

FM_RE = re.compile(r"^---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|$)", re.S)
LINK_RE = re.compile(r"\[\[([^\]\[]+?)\]\]")
DATE_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")

# A subdistrict folder name is published in data/vault-city.json, so a folder
# that carries a full ISO date (a dated working project) or is personal is
# reduced to the empty string. Month folders like 2026-09 are kept: they carry
# no day component and say nothing beyond the week the layout already encodes.
PRIVATE_SUB_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
PERSONAL_SUBS = {"family"}


def public_sub(sub):
    if sub and (PRIVATE_SUB_RE.search(sub) or sub.lower() in PERSONAL_SUBS):
        return ""
    return sub

QUOTES = "'\""


def parse_frontmatter(text):
    """Return (dict, body). Minimal YAML: scalars, inline lists, block lists."""
    m = FM_RE.match(text)
    if not m:
        return None, text
    fm = {}
    cur_key = None
    for line in m.group(1).splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line[0] in " \t":
            s = line.strip()
            if s.startswith("- ") and cur_key is not None:
                if not isinstance(fm.get(cur_key), list):
                    fm[cur_key] = []
                fm[cur_key].append(s[2:].strip().strip(QUOTES))
            continue
        km = re.match(r"^([A-Za-z_][\w\-]*)\s*:\s*(.*)$", line)
        if not km:
            continue
        key, val = km.group(1), km.group(2).strip()
        cur_key = key
        if val == "":
            fm[key] = []          # may become a block list
        elif val.startswith("[") and val.endswith("]"):
            fm[key] = [v.strip().strip(QUOTES) for v in val[1:-1].split(",") if v.strip()]
        else:
            fm[key] = val.strip(QUOTES)
    return fm, text[m.end():]


def week_index(val):
    if not val:
        return None
    if isinstance(val, list):
        val = val[0] if val else None
        if not val:
            return None
    dm = DATE_RE.search(str(val))
    if not dm:
        return None
    try:
        d = datetime.date(int(dm.group(1)), int(dm.group(2)), int(dm.group(3)))
    except ValueError:
        return None
    return (d - WEEK0).days // 7


def district_of(rel_parts):
    """rel_parts: path parts relative to the vault, excluding the filename."""
    root = rel_parts[0]
    sub = rel_parts[1] if len(rel_parts) > 1 else ""
    subsub = rel_parts[2] if len(rel_parts) > 2 else ""
    if root == "00-core":
        return "core", sub
    if root == "10-memory":
        return (sub if sub else "inbox"), subsub
    if root == "20-ventures":
        return (sub if sub else "ventures"), subsub
    if root == "30-jhon":
        return "jhon", sub
    return "other", sub


def norm(s):
    return s.strip().lower()


def link_target(raw):
    t = raw.split("|")[0].split("#")[0].split("^")[0].strip()
    if "/" in t:
        t = t.rsplit("/", 1)[1]
    if t.lower().endswith(".md"):
        t = t[:-3]
    return norm(t)


def scalar(fm, key):
    if not fm:
        return None
    v = fm.get(key)
    if v in (None, "", []):
        return None
    if isinstance(v, list):
        v = v[0]
    return str(v)


def main():
    notes = []   # private fields (stem, aliases, targets) live in memory only
    for root in ROOTS:
        top = os.path.join(VAULT, root)
        for dp, dns, fns in os.walk(top):
            dns[:] = sorted(d for d in dns if d not in SKIP_DIRS and not d.startswith("."))
            rel = os.path.relpath(dp, VAULT).replace(os.sep, "/")
            parts = rel.split("/")
            if parts[0] == "30-jhon" and len(parts) > 1 and parts[1] == "life":
                dns[:] = []
                continue
            for fn in sorted(fns):
                if not fn.lower().endswith(".md"):
                    continue
                path = os.path.join(dp, fn)
                try:
                    with open(path, encoding="utf-8", errors="replace") as fh:
                        text = fh.read()
                except OSError:
                    continue
                fm, body = parse_frontmatter(text)
                district, subdistrict = district_of(parts)
                stem = norm(fn[:-3])
                aliases = []
                if fm:
                    al = fm.get("aliases", fm.get("alias", []))
                    if isinstance(al, str):
                        al = [al]
                    aliases = [norm(a) for a in al if a]
                rc = 0
                rcs = scalar(fm, "retrieval_count")
                if rcs is not None:
                    try:
                        rc = int(float(rcs))
                    except ValueError:
                        rc = 0
                targets = {link_target(m.group(1)) for m in LINK_RE.finditer(body)}
                targets.discard("")
                notes.append({
                    "stem": stem, "aliases": aliases, "targets": targets,
                    "district": district, "subdistrict": subdistrict,
                    "created": week_index(scalar(fm, "created")),
                    "updated": week_index(scalar(fm, "updated")),
                    "type": scalar(fm, "type"),
                    "status": scalar(fm, "status"),
                    "retrieval_count": rc,
                    "has_fm": fm is not None,
                })

    # resolver: filename stem first, then alias; duplicates resolve to the first seen
    by_stem, by_alias = {}, {}
    for i, n in enumerate(notes):
        by_stem.setdefault(n["stem"], i)
        for a in n["aliases"]:
            by_alias.setdefault(a, i)

    edges = set()
    unresolved = 0
    for i, n in enumerate(notes):
        for t in n["targets"]:
            j = by_stem.get(t)
            if j is None:
                j = by_alias.get(t)
            if j is None:
                unresolved += 1
                continue
            if j == i:
                continue
            edges.add((i, j))

    inbound = collections.Counter()
    outbound = collections.Counter()
    for a, b in edges:
        outbound[a] += 1
        inbound[b] += 1

    nodes = []
    for i, n in enumerate(notes):
        nodes.append({
            "id": i,
            "district": n["district"],
            "subdistrict": public_sub(n["subdistrict"]),
            "created": n["created"],
            "updated": n["updated"],
            "type": n["type"],
            "status": n["status"],
            "retrieval_count": n["retrieval_count"],
            "inbound": inbound[i],
            "outbound": outbound[i],
        })
    edge_list = sorted(edges)
    out = {
        "week0": WEEK0.isoformat(),
        "weeks": LAST_WEEK + 1,
        "nodes": nodes,
        "edges": [list(e) for e in edge_list],
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(out, fh, separators=(",", ":"))

    # census (numbers only)
    print("nodes", len(nodes))
    print("edges", len(edge_list), "(unresolved link targets:", unresolved, ")")
    print("no front-matter", sum(1 for n in notes if not n["has_fm"]))
    print("with retrieval_count", sum(1 for n in notes if n["retrieval_count"] > 0),
          "with updated", sum(1 for n in notes if n["updated"] is not None))
    print("per district:")
    dc = collections.Counter(n["district"] for n in nodes)
    for d, c in sorted(dc.items(), key=lambda kv: -kv[1]):
        print("  %-12s %5d" % (d, c))
    print("per created week (raw index; <0 is before week 0, None = no front-matter):")
    wc = collections.Counter(n["created"] for n in nodes)
    for w in sorted(wc, key=lambda x: (x is None, x if x is not None else 0)):
        print("  %5s %5d" % (w, wc[w]))
    print("types:", dict(collections.Counter(n["type"] for n in nodes).most_common(12)))
    print("status:", dict(collections.Counter(n["status"] for n in nodes).most_common(8)))


if __name__ == "__main__":
    main()
