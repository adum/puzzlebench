"""Public instruction prior for the experimental branching levels and their auditor."""

from __future__ import annotations

import random
from dataclasses import dataclass

if __package__:
    from . import sensejump_core as core
else:
    import sensejump_core as core


F, L, R, S = range(4)
J = 128  # A jump is encoded as J + its signed displacement.


def random_jump(rng: random.Random, length: int) -> int:
    if length < 4:
        return J - 1
    span = length - 2 if rng.random() < 0.35 else min(length - 2, 9)
    return J + rng.choice((-1, 1)) * rng.randint(2, span)


def sample(rng: random.Random, length: int) -> tuple[int, ...]:
    code = []
    while len(code) < length:
        if len(code) + 2 <= length and rng.random() < 0.25:
            code.extend((S, random_jump(rng, length) if rng.random() < 0.56 else rng.choice((L, R))))
        else:
            code.append(rng.choice((F, F, F, F, L, R)))
    # Single-slot substitutions can split guards or introduce independent jumps;
    # there is no fixed block layout or required direction of travel.
    for _ in range(rng.randrange(1, 6)):
        slot = rng.randrange(length)
        code[slot] = rng.choice((F, F, L, R, S, random_jump(rng, length)))
    return tuple(code)


def instructions(code) -> list[core.Instruction]:
    return [core.Instruction("FLRS"[op]) if 0 <= op < 4 else core.Instruction("J", op - J) for op in code]


def encoded(program) -> tuple[int, ...]:
    n = len(program)
    return tuple(J + ((inst.arg or 1) % n or n) if inst.op == "J" else "FLRS".index(inst.op) for inst in program)


def without(code, start, count):
    """Jumps into deleted slots land on the next surviving slot."""
    keep = [i for i in range(len(code)) if not start <= i < start + count]
    if not keep:
        return ()
    new = {old: i for i, old in enumerate(keep)}
    out = []
    for i, old in enumerate(keep):
        op = code[old]
        if op >= 4:
            dest = (old + op - J) % len(code)
            while dest not in new:
                dest = (dest + 1) % len(code)
            diff = new[dest] - i
            op = J + (diff or len(keep))  # J+0 means fall through, not a self-loop.
        out.append(op)
    return tuple(out)


@dataclass
class Trace:
    cells: dict
    path: list
    steps: int
    active_slots: int
    variable_sensors: int
    live_jumps: int


def trace_program(rng, code, size):
    x, y = start = (rng.randint(6, size - 7), rng.randint(6, size - 7))
    pc = d = slots = blocked = clear = jumps = 0
    cells, path, seen = {start: False}, [start], set()
    n = len(code)
    for t in range(min(4000, 25 * size)):
        state = (x, y, d, pc)
        if state in seen:
            return None
        seen.add(state)
        slots |= 1 << pc
        op, advance = code[pc], 1
        if op == F or op == S:
            dx, dy = core.DIR_DELTAS[d]
            pos = (x + dx, y + dy)
            inside = 0 <= pos[0] < size and 0 <= pos[1] < size
            if op == F:
                if not inside:
                    if (t < 3 * n or len(path) < n + 15 or abs(x - start[0]) + abs(y - start[1]) < size * .67
                            or slots.bit_count() < n * .8 or (blocked & clear).bit_count() < 3 or jumps.bit_count() < 3):
                        return None
                    # A single open perimeter tile, including cells merely sensed clear.
                    if any(p != (x, y) and not wall and (0 in p or size - 1 in p) for p, wall in cells.items()):
                        return None
                    return Trace(cells, path, t + 1, slots.bit_count(), (blocked & clear).bit_count(), jumps.bit_count())
                if cells.get(pos):
                    return None
                cells[pos] = False
                path.append(pos)
                x, y = pos
            else:
                if inside and pos not in cells:
                    cells[pos] = rng.random() < .35
                if inside and cells[pos]:
                    blocked |= 1 << pc
                else:
                    clear |= 1 << pc
                    advance = 2
        elif op == L:
            d = (d - 1) % 4
        elif op == R:
            d = (d + 1) % 4
        else:
            advance = op - J
            jumps |= 1 << pc
        pc = (pc + advance) % n
    return None
