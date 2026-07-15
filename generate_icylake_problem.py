#!/usr/bin/env python3
"""Genera problemas PDDL aleatorios compatibles con domain.pddl (icylake)."""

import argparse
import random
import re
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple


Position = Tuple[int, int]
PDDL_NAME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_-]*$")


def non_negative_int(value: str) -> int:
    number = int(value)
    if number < 0:
        raise argparse.ArgumentTypeError("debe ser un entero no negativo")
    return number


def positive_int(value: str) -> int:
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("debe ser un entero positivo")
    return number


def pddl_name(value: str) -> str:
    if not PDDL_NAME_RE.fullmatch(value):
        raise argparse.ArgumentTypeError(
            "debe ser un identificador PDDL (letras, numeros, '-' o '_')"
        )
    return value.lower()


def tile_name(position: Position) -> str:
    x, y = position
    return f"tile_{x}_{y}"


def reward_names(prefix: str, count: int) -> List[str]:
    if count == 1:
        return [prefix]
    return [f"{prefix}-{index}" for index in range(1, count + 1)]


def generate_problem(
    width: int,
    height: int,
    wall_count: int,
    pit_count: int,
    diamond_count: int,
    first_aid_count: int,
    seed: int,
    problem_name: str,
    bound: int,
    normal_step_cost: int,
    slip_step_cost: int,
    diamond_utility: int,
    first_aid_utility: int,
) -> str:
    """Devuelve un problema PDDL; una misma semilla produce el mismo problema."""
    if width <= 0 or height <= 0:
        raise ValueError("La anchura y la altura deben ser positivas")

    start = (0, height - 1)
    available = [(x, y) for y in range(height) for x in range(width) if (x, y) != start]
    needed = wall_count + pit_count + diamond_count + first_aid_count
    if needed > len(available):
        raise ValueError(
            f"Se necesitan {needed} celdas libres, pero solo hay {len(available)} "
            "despues de reservar la posicion inicial"
        )

    rng = random.Random(seed)
    selected = rng.sample(available, needed)
    cursor = 0

    walls = set(selected[cursor : cursor + wall_count])
    cursor += wall_count
    pits = set(selected[cursor : cursor + pit_count])
    cursor += pit_count

    aid_positions = selected[cursor : cursor + first_aid_count]
    cursor += first_aid_count
    diamond_positions = selected[cursor : cursor + diamond_count]

    aids = reward_names("first-aid-kit", first_aid_count)
    diamonds = reward_names("diamond", diamond_count)
    rewards: Dict[str, Position] = dict(zip(aids, aid_positions))
    rewards.update(zip(diamonds, diamond_positions))

    lines = [
        f"(define (problem {problem_name})",
        "  (:domain icylake)",
        "",
        "  (:objects",
    ]

    lines.append("    " + " ".join(f"upperwall-{x} - wall" for x in range(width)))
    for y in range(height - 1, -1, -1):
        row = [f"leftwall-{y} - wall"]
        for x in range(width):
            position = (x, y)
            kind = "wall" if position in walls else "pit" if position in pits else "ice"
            row.append(f"{tile_name(position)} - {kind}")
        row.append(f"rightwall-{y} - wall")
        lines.append("    " + " ".join(row))
    lines.append("    " + " ".join(f"bottomwall-{x} - wall" for x in range(width)))
    if rewards:
        lines.append("    " + " ".join(f"{name} - reward" for name in rewards))
    lines.extend(["  )", "", "  (:init", f"    (at {tile_name(start)})"])

    for name, position in rewards.items():
        lines.append(f"    (reward-position {name} {tile_name(position)})")

    lines.append("")
    for y in range(height - 1, -1, -1):
        row = [f"leftwall-{y}"] + [tile_name((x, y)) for x in range(width)] + [f"rightwall-{y}"]
        lines.append("    " + " ".join(f"(left-of {left} {right})" for left, right in zip(row, row[1:])))

    lines.append("")
    for x in range(width):
        column = [f"upperwall-{x}"] + [tile_name((x, y)) for y in range(height - 1, -1, -1)] + [f"bottomwall-{x}"]
        lines.append("    " + " ".join(f"(down-of {down} {up})" for up, down in zip(column, column[1:])))

    lines.extend(
        [
            "",
            "    (= (total-cost) 0)",
            f"    (= (normal-step-cost) {normal_step_cost})",
            f"    (= (slip-step-cost) {slip_step_cost})",
            "  )",
        ]
    )

    if rewards:
        lines.append("  (:utility")
        for name in aids:
            lines.append(f"    (= (has-reward {name}) {first_aid_utility})")
        for name in diamonds:
            lines.append(f"    (= (has-reward {name}) {diamond_utility})")
        lines.append("  )")

    lines.extend([f"  (:bound {bound})", ")", ""])
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Genera un problema aleatorio para el dominio PDDL icylake."
    )
    parser.add_argument("--width", type=positive_int, required=True, help="anchura del grid")
    parser.add_argument("--height", type=positive_int, required=True, help="altura del grid")
    parser.add_argument("--diamonds", type=non_negative_int, default=1, help="numero de diamantes (default: 1)")
    parser.add_argument("--first-aid-kits", type=non_negative_int, default=1, help="numero de botiquines (default: 1)")
    parser.add_argument("--walls", type=non_negative_int, default=3, help="numero de paredes internas (default: 3)")
    parser.add_argument("--pits", type=non_negative_int, default=3, help="numero de pits (default: 3)")
    parser.add_argument("--seed", type=int, default=None, help="semilla; si se omite se genera una aleatoria")
    parser.add_argument("--problem-name", type=pddl_name, default="generated-icylake", help="nombre PDDL del problema")
    parser.add_argument("--bound", type=non_negative_int, default=20, help="cota del problema (default: 20)")
    parser.add_argument("--normal-step-cost", type=non_negative_int, default=1)
    parser.add_argument("--slip-step-cost", type=non_negative_int, default=2)
    parser.add_argument("--diamond-utility", type=int, default=20)
    parser.add_argument("--first-aid-utility", type=int, default=10)
    parser.add_argument("-o", "--output", type=Path, required=True, help="fichero PDDL de salida")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    seed = args.seed if args.seed is not None else random.SystemRandom().randrange(2**63)
    try:
        problem = generate_problem(
            width=args.width,
            height=args.height,
            wall_count=args.walls,
            pit_count=args.pits,
            diamond_count=args.diamonds,
            first_aid_count=args.first_aid_kits,
            seed=seed,
            problem_name=args.problem_name,
            bound=args.bound,
            normal_step_cost=args.normal_step_cost,
            slip_step_cost=args.slip_step_cost,
            diamond_utility=args.diamond_utility,
            first_aid_utility=args.first_aid_utility,
        )
    except ValueError as error:
        build_parser().error(str(error))

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="\n") as output_file:
        output_file.write(problem)
    print(f"Problema escrito en {args.output} (seed={seed})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
