"""zonecat.py — zoning categories (the district family without its FAR or Bauklasse number) for the "Zoning category" view"""
import json, os, re
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
VIE_SRC = os.path.abspath(os.path.join(HERE, "..", "..", "..", "Data", "vienna_2026-10-30", "GENFLWIDMUNGOGD.json"))

RAMP = {"R": ("#F5E3A0", "#B97A12"), "C": ("#F0A898", "#A8272B"), "M": ("#CDB8E2", "#5E3F8F"),
        "P": ("#CFE6C0", "#3F7F35"), "S": ("#B9D0E8", "#3A6A9E"), "T": ("#C9CDD2", "#8A9099")}

PHL = [("RSD", "R", "Residential single-family detached"), ("RSA", "R", "Residential single-family attached"),
       ("RTA", "R", "Residential two-family attached"), ("RM", "R", "Residential multi-family"),
       ("RMX", "C", "Residential mixed-use"), ("CMX", "C", "Commercial mixed-use"), ("CA", "C", "Auto-oriented commercial"),
       ("IRMX", "M", "Industrial residential mixed-use"), ("ICMX", "M", "Industrial commercial mixed-use"),
       ("I", "M", "Industrial"), ("I-P", "M", "Port industrial"),
       ("SP-PO-A", "P", "Parks and open space, active"), ("SP-PO-P", "P", "Parks and open space, passive"),
       ("SP-INS", "S", "Institutional"), ("SP-CIV", "S", "Civic"), ("SP-ENT", "S", "Entertainment"),
       ("SP-STA", "S", "Stadium"), ("SP-AIR", "S", "Airport")]

TYO = [("R1L", "R"), ("R2L", "R"), ("R1M", "R"), ("R2M", "R"), ("R1", "R"), ("R2", "R"), ("RQ", "R"),
       ("CN", "C"), ("C", "C"), ("MQ", "M"), ("M", "M"), ("MX", "M")]

VIE = [("W", "R"), ("WGV", "R"), ("WGF", "R"), ("WFB", "R"), ("WGFGV", "R"), ("GS", "R"),
       ("GB", "C"), ("GBGV", "C"), ("GBGF", "C"), ("GBGFGV", "C"), ("GBF", "C"), ("GBFB", "C"),
       ("GBBG", "M"), ("IG", "M"), ("SO", "S"), ("L", "P"), ("E", "P"), ("EKLW", "P"), ("EKL", "P"), ("EPK", "P"),
       ("ESP", "P"), ("EBD", "P"), ("EBH", "P"), ("SWW", "P"), ("SWWL", "P"), ("SPK", "P"), ("F", "P"), ("VB", "T")]

SFO = [("RH", "R", "Residential, house"), ("RM", "R", "Residential, mixed (apartments)"), ("RTO", "R", "Residential, transit oriented"),
       ("RED", "R", "Residential enclave"), ("DTR", "R", "Downtown residential"), ("RC", "C", "Residential-commercial"),
       ("NC", "C", "Neighborhood commercial"), ("NCT", "C", "Neighborhood commercial transit"), ("NCD", "C", "Named neighborhood commercial district"),
       ("C-2", "C", "Community business"), ("C-3", "C", "Downtown commercial"), ("CHN", "C", "Chinatown"), ("RCD", "C", "Regional commercial"),
       ("MU", "M", "Mixed use (Eastern Neighborhoods, SoMa)"), ("SALI", "M", "Service, arts, light industrial"),
       ("PDR", "M", "Production, distribution and repair"), ("M", "M", "Industrial"), ("P", "S", "Public"),
       ("OS", "P", "Open space (plan areas)"), ("PLAN", "T", "Redevelopment and special plan areas")]

def sfo_key(z):
    z = z.strip().upper()
    m = re.match(r"^(RH|RM|RTO|RC|NCT|NCD|PDR|RED)(-|$)", z)
    if m: return m.group(1)
    if "DTR" in z: return "DTR"
    if re.match(r"^NC-", z): return "NC"
    if re.match(r"^C-3", z): return "C-3"
    if z in ("CCB", "CVR", "CRNC"): return "CHN"
    if re.match(r"^M-\d", z): return "M"
    if z in ("MUG", "MUO", "MUR", "UMU", "WMUG", "WMUO", "CMUO", "S-MU"): return "MU"
    if z in ("P", "JOB CORPS"): return "P"
    if z.endswith("-OS"): return "OS"
    if z in ("C-2", "SALI", "RCD"): return z
    return "PLAN"

def phl_key(z):
    z = re.sub(r"[-\s]+", "-", z.strip().upper())
    if z.replace("-", "") in ("SPPOA", "SPPOP"): return "SP-PO-" + z[-1]
    if re.fullmatch(r"I-?P", z): return "I-P"
    if z.startswith("SP-"): return z
    return re.sub(r"-?\d+(\.\d+)?$", "", z)

def vie_names():
    if not os.path.exists(VIE_SRC): return {}
    out = {}
    for f in json.load(open(VIE_SRC, encoding="utf-8"))["features"]:
        p = f["properties"]; w, t = p.get("WIDMUNG") or "", p.get("WIDMUNG_TXT") or ""
        k = re.sub(r"\d+$", "", w)
        if k and k not in out and t: out[k] = re.sub(r"\s*Bauklasse.*$", "", t).strip()
    return out

def mix(a, b, t):
    A = [int(a[i:i + 2], 16) for i in (1, 3, 5)]; B = [int(b[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * t):02X}" for x, y in zip(A, B))

def categories(codes, release):
    codes = ["" if c is None else str(c).strip() for c in codes]
    if release.startswith("phl"):
        key = phl_key; spec = [(k, f, f"{k} {n}") for k, f, n in PHL]
    elif release.startswith("vie"):
        names = vie_names(); key = lambda z: re.sub(r"\d+$", "", z)
        spec = [(k, f, f"{k} {names.get(k, '')}".strip()) for k, f in VIE]
    elif release.startswith("sfo"):
        key = sfo_key; spec = [(k, f, f"{k} {n}") for k, f, n in SFO]
    elif release.startswith("tyo"):
        key = lambda z: z.split()[0]
        spec = [(k, f, None) for k, f in TYO]
    else:
        return None
    keys = [key(z) if z else "" for z in codes]
    used = {k for k in keys if k}
    full = {}
    for z, k in zip(codes, keys):
        if k and k not in full: full[k] = z
    if release.startswith("tyo"): spec = [(k, f, re.sub(r"\s+\d+%$", "", full[k]) if k in full else k) for k, f, _ in spec]
    known = {k for k, _, _ in spec}
    spec = [s for s in spec if s[0] in used] + [(k, "S", k) for k in sorted(used - known)]
    fams = {}
    for k, f, _ in spec: fams.setdefault(f, []).append(k)
    colors = []
    for k, f, _ in spec:
        m = fams[f]; t = 0.5 if len(m) == 1 else 0.15 + 0.75 * m.index(k) / (len(m) - 1)
        colors.append(mix(*RAMP[f], t))
    idx = {k: i for i, (k, _, _) in enumerate(spec)}
    zc = np.array([idx.get(k, 255) for k in keys], np.uint8)
    return zc, [n for _, _, n in spec], colors
