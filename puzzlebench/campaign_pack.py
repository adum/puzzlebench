"""Seal the edition without opening the original private corpus."""

import hashlib
import io
import json
import os
import secrets
import subprocess
import tarfile
import tempfile
import zipfile
from pathlib import Path

from . import campaign_spec as spec
from .campaign import anonymous, sha
from .campaign_author import STATE, recipe_sources
from .evaluation import unpack_even
from .pilot_boards import board_geometry, core, put, read


def checked_board(folder, number, *, pilot=False):
    key = f"{number:03}" if pilot else str(number)
    raw = (folder / "levels" / (key + ".level")).read_text()
    level = core.parse_level(raw)
    cert = read(folder / "answers" / (key + ".json"))
    rec = read(folder / "records" / (key + ".json"))
    ok, why, program, trace = core.verify_program(level, cert["solution_program"])
    if (not ok or level.level_id is not None or level.solution_hash is not None
            or core.compute_level_hash(level) != cert["level_hash"] or rec["level_hash"] != cert["level_hash"]
            or trace.steps != cert["solution_steps"] or core.compute_program_hash(program) != cert["solution_hash"]
            or board_geometry(level) != rec["geometry"]):
        raise ValueError(f"wrong board or certificate at {key}: {why}")
    return anonymous(raw).encode(), rec


def make_packs(staging, public, extra, pw):
    with zipfile.ZipFile(staging / "public.zip", "w") as z:
        for n, data in sorted(public.items()):
            info = zipfile.ZipInfo(f"{n}.level", date_time=(1980,1,1,0,0,0))
            z.writestr(info, data, compress_type=zipfile.ZIP_DEFLATED)
    # Plaintext tar stays in an owner-only temporary directory, never in the release tree.
    with tempfile.TemporaryDirectory() as private:
        tarpath = Path(private) / "extra.tar"
        with tarfile.open(tarpath, "w") as t:
            for n, data in sorted(extra.items()):
                info = tarfile.TarInfo(f"{n}.level")
                info.size, info.mode = len(data), 0o600
                t.addfile(info, io.BytesIO(data))
        subprocess.run(["openssl","enc","-aes-256-cbc","-pbkdf2","-salt","-pass","stdin",
                        "-in",str(tarpath),"-out",str(staging/"new-even.enc")],
                       input=pw+"\n", text=True, capture_output=True, check=True, timeout=60)
        check = unpack_even(staging/"new-even.enc", pw, Path(private)/"check")
        if set(check) != set(extra) or any(path.read_bytes() != extra[n] for n,path in check.items()):
            raise ValueError("new private overlay did not round-trip")


def pack(work, pilot):
    edition = spec.EDITION
    if (edition / "manifest.json").exists():
        raise ValueError("edition already sealed; issue a new version instead of overwriting")
    recipe = read(work / "recipe.json")
    if recipe["sources"] != recipe_sources():
        raise ValueError("generation inputs changed")
    rows = {int(r["id"]):r for r in recipe["rows"]}
    ids = spec.prefix_ids()
    proposed = read(pilot/"order-proposal/order.json")["order"]
    if [r["source_id"] for r in proposed] != ids:
        raise ValueError("proposal mismatch")
    expected = {n for n,s in enumerate(ids,1) if n%2 == 0 and s[0]=="P"} | {int(r["id"]) for r in spec.frontier_rows()}
    if set(rows) != expected or {p.name for p in (work/"records").glob("*.json")} != {f"{n}.json" for n in rows}:
        raise ValueError("missing or unexpected generated positions")
    archives = read(pilot/"solvers.json")["solvers"]
    refs = [read(Path(s["run"])/"run.json")["corpus_sha256"] for s in archives.values()]
    if not all(ref == refs[0] for ref in refs) or set(refs[0]) != {str(n) for n in range(1,413)}:
        raise ValueError("legacy reference hashes disagree")
    public, extra = {}, {}
    seen = set(recipe["known"])
    for n, s in enumerate(ids,1):
        if n%2 == 0:
            continue
        old = int(s[1:])
        if s[0]=="L":
            path = STATE/"data/robotsrevenge/levels_public"/f"{old}.level"
            if sha(path) != refs[0][str(old)]:
                raise ValueError("legacy public board changed")
            public[n] = anonymous(path.read_text()).encode()
        else:
            public[n], _ = checked_board(pilot, old, pilot=True)
    for n, row in rows.items():
        data, rec = checked_board(work, n)
        if any(rec[k] != v for k,v in row.items()) or rec["geometry"] in seen:
            raise ValueError(f"duplicate layout or changed recipe: {n}")
        seen.add(rec["geometry"])
        (public if n%2 else extra)[n] = data
    total = len(ids) + len(list(spec.frontier_rows()))
    if set(public) != set(range(1,total+1,2)) or set(extra) != {n for n in expected if n%2==0}:
        raise ValueError("incorrect public/private split")
    keys = STATE / "data" / ("robotsrevenge-" + spec.VERSION)
    keys.mkdir(parents=True, exist_ok=True, mode=0o700)
    key = keys / "overlay-password"
    if not key.exists():
        with key.open("x") as f:
            os.fchmod(f.fileno(), 0o600)
            f.write(secrets.token_hex(32)+"\n")
    with tempfile.TemporaryDirectory(dir=edition) as tmp:
        stage = Path(tmp)
        make_packs(stage, public, extra, key.read_text().strip())
        manifest = {"schema":1, "version":spec.VERSION, "count":total, "prefix_sha256":sha(edition/"prefix.txt"),
                    "legacy_sha256":[refs[0][str(i)] for i in range(1,413)],
                    "public_zip_sha256":sha(stage/"public.zip"), "new_even_enc_sha256":sha(stage/"new-even.enc"),
                    "public_levels":{str(n):hashlib.sha256(b).hexdigest() for n,b in sorted(public.items())},
                    "new_even_levels":{str(n):hashlib.sha256(b).hexdigest() for n,b in sorted(extra.items())},
                    "frontier":list(spec.frontier_rows())}
        put(stage/"manifest.json", manifest)
        slots = []
        for n, (sid, placement) in enumerate(zip(ids, proposed), 1):
            if sid.startswith("P"):
                rec = read(pilot / "records" / (sid[1:] + ".json"))
                if n % 2 == 0 and (rec["family"], rec["options"]) != (rows[n]["family"], rows[n]["options"]):
                    raise ValueError("Private replacement does not match the pilot setting")
                slots.append(dict(position=n, pilot=sid, stage=placement["stage"],
                                  family=rec["family"], options=rec["options"]))
        (stage/"pilot-slots.json").write_text("[\n" + ",\n".join("  " + json.dumps(r) for r in slots) + "\n]\n")
        for name in ("public.zip","new-even.enc","pilot-slots.json","manifest.json"):
            (stage/name).chmod(0o644)
            (stage/name).replace(edition/name)
    print(f"Sealed {spec.VERSION}: {total} levels; {len(public)} public, {len(extra)} fresh private, 206 legacy private.")
