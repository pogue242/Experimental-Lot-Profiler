"""native.py — encode a city's own land-use classes for the "Land use (original)" view"""
import json
import numpy as np, pandas as pd

def encode(values, colors, title, out_json, order=None):
    s = pd.Series(values, dtype=object).where(lambda x: x.notna() & (x.astype(str).str.strip() != ""), None)
    names = order or list(s.dropna().value_counts().index)
    if len(names) > 254: raise SystemExit(f"{len(names)} original classes; at most 254 fit")
    idx = {n: k for k, n in enumerate(names)}
    codes = np.array([idx.get(v, 255) if v is not None else 255 for v in s], dtype=np.int16)
    json.dump({"title": title, "names": [str(n) for n in names], "colors": [colors(n, k) for k, n in enumerate(names)]},
              open(out_json, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return codes

PALETTE = ["#4E79A7", "#F28E2B", "#E15759", "#76B7B2", "#59A14F", "#EDC948", "#B07AA1", "#FF9DA7", "#9C755F", "#BAB0AC",
           "#1F77B4", "#AEC7E8", "#FFBB78", "#98DF8A", "#C5B0D5", "#C49C94", "#F7B6D2", "#DBDB8D", "#9EDAE5", "#8C6D31"]

def by_keyword(rules):
    def f(name, k):
        n = str(name).lower()
        for pat, c in rules:
            if pat in n: return c
        return PALETTE[k % len(PALETTE)]
    return f
