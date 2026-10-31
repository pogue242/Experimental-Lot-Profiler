"""split_tiles.py — split a PMTiles file into 64 MiB parts (<file>.1, <file>.2, …) that the app reads as one file"""
import os, sys

PART = 64 * 1024 * 1024

def split(path):
    n = 0
    with open(path, "rb") as fh:
        while True:
            b = fh.read(PART)
            if not b: break
            n += 1
            with open(f"{path}.{n}", "wb") as out: out.write(b)
    print(f"{os.path.basename(path)}: {n} parts; add \"parts\": {{\"{os.path.basename(path)}\": {n}}} to its release in data/releases.json")
    return n

if __name__ == "__main__":
    for p in sys.argv[1:]: split(p)
