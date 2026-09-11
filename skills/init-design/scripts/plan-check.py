#!/usr/bin/env python3
"""Mechanical checks over a plan/ tree. Usage: plan-check.py PLAN_DIR [--names FILE]

Prints one `PASS <check>` or `FAIL <file>:<line> <check> — <reason>` line per finding and
exits 1 when anything failed. Judgment checks (wording, one behaviour per row) stay with the reader.
"""
import re
import sys
from pathlib import Path

CAP = 120
FIELDS = ("Responsibility", "Path", "Serves", "Operations", "Owns", "Failure", "Depends", "Test seam")
SECTION_CAP, BLOCK_CAP, PARA_CAP, ITEM_CAP, CELL_CAP, LINE_CAP = 60, 20, 6, 4, 160, 120
HEADER_OK = re.compile(r"^(# |Responsibility:|Path:|Serves:|\s+\S|\s*$)")
ITEM_START = re.compile(r"^\s*([-*]|\d+\.)\s|^[A-Z][A-Za-z ]{0,20}( —|:)\s")
SEP_ROW = re.compile(r"^\|[\s:|-]+\|?\s*$")
LIST_SECTIONS = ("Failure", "Depends", "Test seam")
ROUTE = re.compile(r"^\|\s*([A-Za-z][\w-]*)\s*\|.*\|\s*\[([^\]]+)\]\(([^)]+\.md)\)\s*\|")
FAILS = []


def fail(path, line, check, reason):
    FAILS.append(f"FAIL {path}:{line} {check} — {reason}")


def lower(name):
    return name[:1].lower() + name[1:]


def cells(line):
    return [c.strip() for c in re.split(r"(?<!\\)\|", line)[1:-1]]


def read(path):
    return path.read_text(encoding="utf-8").splitlines()


def fields(lines):
    """Component document → {field: (line_no, text)}; a field is a `Field:` line or a `## Field` section."""
    out, cur = {}, None
    for no, line in enumerate(lines, 1):
        h = re.match(r"^## (%s)( — .*)?\s*$" % "|".join(FIELDS), line)
        m = re.match(r"^(%s):\s*(.*)" % "|".join(FIELDS), line)
        if h:
            cur = h.group(1)
            out.setdefault(cur, [no, ""])
        elif m:
            cur = m.group(1)
            out[cur] = [no, m.group(2)]
        elif line.startswith("# ") or line.startswith("## "):
            cur = None
        elif cur:
            out[cur][1] += " " + line.strip()
    return {k: (v[0], v[1].strip()) for k, v in out.items()}


def depends_edges(text):
    """Depends text → (→ side, ← side), one list item or one sentence at a time."""
    left, right = [], []
    for item in re.split(r"(?:^|\s)-\s+(?=[→←])", text):
        if not item.strip():
            continue
        l, _, r = item.partition("←")
        left.append(first_sentence(l))
        right.append(first_sentence(r))
    return " ".join(left), " ".join(right)


def check_form(p, lines, arch_doc, element):
    """Section, block, paragraph, item and cell caps; list-only sections; header lines of an element doc."""
    fence, seen_h2 = False, False
    sec, blk, prev = None, None, ""
    run = [None, 0, 0]  # kind, start, length

    def close_run():
        kind, start, n = run
        if kind == "para" and n > PARA_CAP:
            fail(p, start, "form", f"paragraph of {n} lines, cap {PARA_CAP}; write it as a list")
        elif kind == "item" and n > ITEM_CAP:
            fail(p, start, "form", f"list item of {n} lines, cap {ITEM_CAP}; split it into sub-items")
        run[0], run[2] = None, 0

    def close_block(no):
        if arch_doc and blk and no - blk[0] > BLOCK_CAP:
            fail(p, blk[0], "form", f"block `{blk[1]}` is {no - blk[0]} lines, cap {BLOCK_CAP}")

    def close_section(no):
        close_block(no)
        if arch_doc and sec and no - sec[0] > SECTION_CAP:
            fail(p, sec[0], "form", f"section `{sec[1]}` is {no - sec[0]} lines, cap {SECTION_CAP}")

    for no, line in enumerate(lines, 1):
        if line.startswith("```"):
            fence = not fence
            close_run()
            prev = line
            continue
        if fence:
            prev = line
            continue
        if line.startswith("#"):
            close_run()
            if no > 1 and prev.strip() and not prev.startswith("#"):
                fail(p, no, "form", "no blank line before the heading")
            if line.startswith("### "):
                close_block(no)
                blk = (no, line[4:].strip())
            else:
                close_section(no)
                sec = (no, line.lstrip("#").strip()) if line.startswith("## ") else None
                blk = None
                seen_h2 = seen_h2 or line.startswith("## ")
            prev = line
            continue
        if element and not seen_h2 and not HEADER_OK.match(line):
            fail(p, no, "form", "only the title, Responsibility, Path and Serves precede the first `## ` heading")
        if line.startswith("|"):
            close_run()
            if prev.strip() and not prev.startswith("|") and not prev.startswith("#"):
                fail(p, no, "form", "no blank line before the table")
            if not SEP_ROW.match(line):
                for c in cells(line):
                    if len(c) > CELL_CAP:
                        fail(p, no, "form", f"cell of {len(c)} chars, cap {CELL_CAP}; move it into a `### ` block")
                    elif re.search(r"[^.\s]\. [A-Z`(]", c):
                        fail(p, no, "form", "cell holds a second sentence; one clause per cell")
            prev = line
            continue
        if not line.strip():
            close_run()
            prev = line
            continue
        if len(line) > LINE_CAP:
            fail(p, no, "form", f"line of {len(line)} chars, cap {LINE_CAP}; wrap it")
        is_item = bool(ITEM_START.match(line))
        if element and sec and sec[1] in LIST_SECTIONS and not is_item and not line[0].isspace():
            fail(p, no, "form", f"`## {sec[1]}` holds prose; one list item per clause")
        if element and sec and sec[1].startswith("Operations") and not is_item and not line[0].isspace() and not line.startswith("`"):
            fail(p, no, "form", "`## Operations` holds prose; a `### ` block per operation, a signature line, then items")
        if is_item:
            close_run()
            run[:] = ["item", no, 1]
        elif run[0]:
            run[2] += 1
        else:
            run[:] = ["para", no, 1]
        prev = line
    close_run()
    close_section(len(lines) + 1)


def first_sentence(text):
    """Text up to the first period outside parentheses and backticks; notes after it name no edge."""
    depth, tick = 0, False
    for i, ch in enumerate(text):
        if ch == "`":
            tick = not tick
        elif not tick and ch in "([":
            depth += 1
        elif not tick and ch in ")]":
            depth = max(0, depth - 1)
        elif ch == "." and depth == 0 and not tick and (i + 1 == len(text) or text[i + 1] == " "):
            return text[:i]
    return text


def names_in(text):
    return set(re.findall(r"\b([A-Z][A-Za-z0-9]+)\b", text))


def main():
    args = sys.argv[1:]
    names_file = None
    if "--names" in args:
        i = args.index("--names")
        names_file = Path(args[i + 1])
        del args[i:i + 2]
    plan = Path(args[0] if args else "plan")
    arch = plan / "architecture"
    root = arch / "ARCHITECTURE.md"
    rel = lambda p: p.relative_to(plan.parent).as_posix()
    if not root.is_file():
        print(f"FAIL {rel(root)}:0 layout — root document missing")
        return 1
    root_lines = read(root)

    # --- layout: routing rows resolve, every doc is routed, titles match, line cap ---
    comps, routed = {}, {root.resolve()}
    section = None
    for no, line in enumerate(root_lines, 1):
        if line.startswith("## "):
            section = line[3:].strip()
        m = ROUTE.match(line)
        if m and section == "Components":
            name, target = m.group(1), (arch / m.group(3))
            comps[name] = target
            routed.add(target.resolve())
            if m.group(3) != f"{lower(name)}/{lower(name)}.md":
                fail(rel(root), no, "layout", f"routing row {name} → {m.group(3)}, expected {lower(name)}/{lower(name)}.md")
            if not target.is_file():
                fail(rel(root), no, "layout", f"routing row {name} → missing {m.group(3)}")
        elif section in ("Data", "Interfaces", "Budgets", "Coverage"):
            for t in re.findall(r"\]\(([^)]+\.md)\)", line):
                routed.add((arch / t).resolve())
    for table in ("data", "interfaces", "budgets", "coverage"):
        p = arch / table / f"{table}.md"
        if not p.is_file():
            fail(rel(root), 0, "layout", f"{table}/{table}.md missing")
        elif p.resolve() not in routed:
            fail(rel(root), 0, "layout", f"{table}/{table}.md not linked from ## {table.capitalize()}")
        routed.add(p.resolve())
    for sc in sorted((arch / "coverage").glob("sc-*/sc-*.md")) if (arch / "coverage").is_dir() else []:
        routed.add(sc.resolve())
    docs = {}  # component name → (path, fields)
    subs = {}  # sub-element name → (path, fields, parent)
    queue = [(n, p, None) for n, p in comps.items()]
    while queue:
        name, path, parent = queue.pop(0)
        if not path.is_file():
            continue
        lines = read(path)
        if not lines or lines[0].strip() != f"# {name}":
            fail(rel(path), 1, "layout", f"title is not `# {name}`")
        if parent is None:
            docs[name] = (path, fields(lines))
        else:
            subs[name] = (path, fields(lines), parent)
        in_sub = False
        for no, line in enumerate(lines, 1):
            if line.startswith("## "):
                in_sub = line[3:].strip() == "Sub-elements"
            m = ROUTE.match(line)
            if m and in_sub:
                sub = path.parent / m.group(3)
                routed.add(sub.resolve())
                if m.group(3) != f"{lower(m.group(1))}/{lower(m.group(1))}.md":
                    fail(rel(path), no, "layout", f"sub-element row {m.group(1)} → {m.group(3)}, expected camelCase path")
                if not sub.is_file():
                    fail(rel(path), no, "layout", f"sub-element row {m.group(1)} → missing {m.group(3)}")
                queue.append((m.group(1), sub, name))
    for p in sorted(arch.rglob("*.md")):
        if p.resolve() not in routed:
            fail(rel(p), 0, "layout", "document is routed from nowhere")
        n = len(read(p))
        if n > CAP:
            fail(rel(p), n, "size", f"{n} lines, cap {CAP}")
        for no, line in enumerate(read(p), 1):
            if line.startswith("Intent:"):
                fail(rel(p), no, "intent", "Intent: line survives")

    # --- form ---
    element_paths = {p.resolve() for p, _ in docs.values()} | {p.resolve() for p, _, _ in subs.values()}
    for p in sorted(plan.rglob("*.md")):
        check_form(rel(p), read(p), arch in p.parents, p.resolve() in element_paths)

    # --- OVERVIEW facts ---
    ov = plan / "OVERVIEW.md"
    ov_lines = read(ov) if ov.is_file() else []
    ov_text = "\n".join(ov_lines)
    reqs, acc_ids = {}, []
    for no, line in enumerate(ov_lines, 1):
        m = re.match(r"^\|\s*(R-\d+)\s*\|", line)
        if m:
            reqs[m.group(1)] = no
            c = cells(line)
            if len(c) >= 5:
                for tok in re.findall(r"`([^`]+)`", c[4]):
                    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{2,}", tok):
                        acc_ids.append((no, tok))
    scenarios = {}  # SC id → (steps set, failure count)
    cur = None
    for line in ov_lines:
        m = re.match(r"^### (SC-\d+)", line)
        if m:
            cur = m.group(1)
            scenarios[cur] = (set(), 0)
        elif cur and re.match(r"^\d+\.", line):
            scenarios[cur][0].add(int(line.split(".")[0]))
        elif cur and line.startswith("Failure —"):
            scenarios[cur] = (scenarios[cur][0], scenarios[cur][1] + 1)
        elif line.startswith("## ") and cur:
            cur = None

    # --- Serves ---
    served = {}
    for name, (path, f) in list(docs.items()) + [(n, (p, f)) for n, (p, f, _) in subs.items()]:
        for r in re.findall(r"R-\d+", f.get("Serves", (0, ""))[1]):
            served.setdefault(r, []).append(name)
            if r not in reqs:
                fail(rel(path), f["Serves"][0], "serves", f"{r} is not in OVERVIEW")
    for r, no in reqs.items():
        if r not in served:
            fail(rel(ov), no, "serves", f"{r} is in no Serves:")

    # --- Interfaces, Coverage, Budgets tables ---
    iface_rows = set()
    ip = arch / "interfaces" / "interfaces.md"
    if ip.is_file():
        for line in read(ip):
            c = cells(line)
            if len(c) >= 5 and not set(c[0]) <= set("-") and c[0] != "Name":
                iface_rows.add(c[0].strip("`"))
    fwd, back = {}, {}
    for name, (path, f) in docs.items():
        no, text = f.get("Depends", (0, ""))
        left, right = depends_edges(text)
        fwd[name] = names_in(left) & (set(docs) | iface_rows)
        back[name] = names_in(right) & set(docs)
        for tok in re.findall(r"`([^`]+)`", left):
            if tok in iface_rows:
                fwd[name].add(tok)
    cov_rows, cov_comps = {}, {}
    cp = arch / "coverage" / "coverage.md"
    arch_text = "\n".join("\n".join(read(p)) for p in arch.rglob("*.md") if p != cp)
    if cp.is_file():
        for no, line in enumerate(read(cp), 1):
            m = re.match(r"^\|\s*(SC-\d+) (step (\d+)|failure)", line)
            if not m:
                continue
            c = cells(line)
            key = (m.group(1), int(m.group(3)) if m.group(3) else "failure")
            comp_names = [x.strip() for x in c[1].split(",") if x.strip() and x.strip() != "—"]
            if not comp_names:
                fail(rel(cp), no, "coverage", "no component serves this step")
            cov_rows.setdefault(key, []).append((no, comp_names))
            for x in comp_names:
                cov_comps.setdefault(x, []).append(no)
                if x not in docs:
                    fail(rel(cp), no, "coverage", f"{x} is not a routed component")
            if len(c) < 3:
                fail(rel(cp), no, "coverage", "no Check cell")
            elif c[2] != "—":
                for tok in re.findall(r"`([^`]+)`", c[2]) or [c[2]]:
                    if tok not in ov_text and tok not in arch_text:
                        fail(rel(cp), no, "coverage", f"check `{tok}` named nowhere else")
    for sc, (steps, nfail) in scenarios.items():
        for s in steps:
            if (sc, s) not in cov_rows:
                fail(rel(cp), 0, "coverage", f"{sc} step {s} has no row")
        got = len(cov_rows.get((sc, "failure"), []))
        if got != nfail:
            fail(rel(cp), 0, "coverage", f"{sc} has {nfail} failure flows, {got} failure rows")
    for (sc, s), rows in cov_rows.items():
        if sc not in scenarios or (s != "failure" and s not in scenarios[sc][0]):
            fail(rel(cp), rows[0][0], "coverage", f"{sc} step {s} is not in OVERVIEW")
    actor_side = {n for n in docs if n not in cov_comps and not back[n]}
    for n in docs:
        if n not in cov_comps and n not in actor_side:
            fail(rel(docs[n][0]), 1, "coverage", f"{n} serves no scenario step")
    # Sequence rule: three or more components ⇒ a Sequence section, and only then
    for (sc, s), rows in cov_rows.items():
        sp = arch / "coverage" / sc.lower() / f"{sc.lower()}.md"
        seq = read(sp) if sp.is_file() else []
        if s == "failure":
            want = sum(1 for _, cn in rows if len(cn) >= 3)
            got = sum(1 for l in seq if l.startswith(f"## Sequence — {sc} failure"))
            if want != got:
                fail(rel(sp), 0, "sequence", f"{sc}: {want} failure rows with 3+ components, {got} failure Sequences")
        else:
            has = any(l.strip() == f"## Sequence — {sc} step {s}" for l in seq)
            if len(rows[0][1]) >= 3 and not has:
                fail(rel(sp), 0, "sequence", f"{sc} step {s} has 3+ components and no Sequence")
            if len(rows[0][1]) < 3 and has:
                fail(rel(sp), 0, "sequence", f"{sc} step {s} has a Sequence but fewer than 3 components")
    bp = arch / "budgets" / "budgets.md"
    if bp.is_file():
        for no, line in enumerate(read(bp), 1):
            c = cells(line)
            if len(c) < 8 or not re.fullmatch(r"B-\d+", c[0]):
                continue
            if c[6] not in reqs:
                fail(rel(bp), no, "budget", f"{c[0]} bounds {c[6]}, not in OVERVIEW")
            try:
                number = float(c[2])
            except ValueError:
                fail(rel(bp), no, "budget", f"{c[0]} number `{c[2]}` is not numeric")
                continue
            owners = [o.strip() for o in c[7].split(",") if o.strip()]
            shares = [re.match(r"([A-Za-z][\w-]*)\s*([\d.]+)?", o) for o in owners]
            for o, m in zip(owners, shares):
                if not m or m.group(1) not in docs:
                    fail(rel(bp), no, "budget", f"{c[0]} owner `{o}` is not a routed component")
                elif m.group(1) in actor_side:
                    fail(rel(bp), no, "budget", f"{c[0]} owner {m.group(1)} is actor-side; it belongs in Measurement")
            nums = [m.group(2) for m in shares if m]
            if all(nums) and nums and abs(sum(map(float, nums)) - number) > 1e-9:
                fail(rel(bp), no, "budget", f"{c[0]} shares sum to {sum(map(float, nums)):g}, number is {number:g}")
            if any(nums) and not all(nums):
                fail(rel(bp), no, "budget", f"{c[0]} mixes shares with and without numbers")
            if not any(nums) and len(owners) != 1:
                fail(rel(bp), no, "budget", f"{c[0]} names {len(owners)} owners without shares")

    # --- Depends: mirrors, cycles, actor-side ---
    for x in docs:
        for y in fwd[x] & set(docs):
            if x not in back.get(y, set()):
                fail(rel(docs[y][0]), docs[y][1].get("Depends", (0, ""))[0], "mirror", f"{x} → {y} has no ← {x}")
        for y in back[x]:
            if x not in fwd.get(y, set()):
                fail(rel(docs[y][0]), docs[y][1].get("Depends", (0, ""))[0], "mirror", f"{x} ← {y} has no → {x}")
            if y in actor_side:
                fail(rel(docs[x][0]), docs[x][1]["Depends"][0], "actor", f"actor-side {y} named in ←")
    for a in actor_side:
        if fwd[a] & set(docs):
            fail(rel(docs[a][0]), docs[a][1]["Depends"][0], "actor", f"{a} → names components; name Interfaces rows")
    state, order = {}, list(docs)
    def dfs(n, stack):
        state[n] = 1
        for m in fwd.get(n, ()) & set(docs):
            if state.get(m) == 1:
                fail(rel(docs[n][0]), docs[n][1].get("Depends", (0, ""))[0], "cycle", " → ".join(stack + [n, m]))
            elif m not in state:
                dfs(m, stack + [n])
        state[n] = 2
    for n in order:
        if n not in state:
            dfs(n, [])

    # --- OPEN markers ↔ README ---
    readme = plan / "README.md"
    items = {}
    for no, line in enumerate(read(readme) if readme.is_file() else [], 1):
        m = re.match(r"^- (OPEN-\d+) \[(user|measure)\]", line)
        if m:
            items[m.group(1)] = no
    seen = {}
    for p in sorted(plan.rglob("*.md")):
        if p == readme:
            continue
        for no, line in enumerate(read(p), 1):
            for o in re.findall(r"OPEN-\d+", line):
                if o not in seen or seen[o][0] == rel(plan / "DECISIONS.md"):
                    seen[o] = (rel(p), no)
    for o, (f, no) in seen.items():
        if o not in items and f != rel(plan / "DECISIONS.md"):
            fail(f, no, "open", f"{o} has no plan/README.md item")
    for o, no in items.items():
        if o not in seen:
            fail(rel(readme), no, "open", f"{o} has no (OPEN) marker in any document")

    # --- acceptance identifiers exist in the design ---
    for no, tok in acc_ids:
        if tok not in arch_text:
            fail(rel(ov), no, "acceptance", f"`{tok}` appears in no architecture document")

    # --- name list ---
    if names_file:
        everything = {rel(p): read(p) for p in plan.rglob("*.md")}
        for line in read(names_file):
            m = re.search(r"`?([A-Za-z_][\w]*)`?\s*→\s*`?([A-Za-z_][\w]*)`?", line)
            if not m:
                continue
            old, new = m.groups()
            for f, lines in everything.items():
                for no, l in enumerate(lines, 1):
                    if re.search(rf"\b{re.escape(old)}\b", l):
                        fail(f, no, "names", f"old spelling {old} survives (→ {new})")
            if not any(re.search(rf"\b{re.escape(new)}\b", l) for lines in everything.values() for l in lines):
                fail(names_file.as_posix(), 0, "names", f"new spelling {new} appears nowhere")

    checks = ["layout", "size", "form", "intent", "serves", "coverage", "sequence", "budget", "mirror", "actor", "cycle", "open", "acceptance"] + (["names"] if names_file else [])
    failed = {f.split()[2] for f in FAILS}
    for c in checks:
        if c not in failed:
            print(f"PASS {c}")
    for f in FAILS:
        print(f)
    print(f"{len(checks)} checks, {len(FAILS)} failures")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
