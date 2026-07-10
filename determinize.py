from pathlib import Path
import argparse
import sys

from pddl import parse_domain
from pddl.formatter import domain_to_string
from pddl.logic.base import OneOf

from fondutils.determizer import determinize
from fondutils.normalizer import normalize


# Returns a compact summary of the all-outcomes determinization.
def count_nondeterministic_actions(domain):
    nondeterministic_actions = 0
    deterministic_variants = 0

    for action in domain.actions:
        normalized_action = normalize(action)
        if isinstance(normalized_action.effect, OneOf):
            nondeterministic_actions += 1
            deterministic_variants += len(normalized_action.effect.operands)

    return nondeterministic_actions, deterministic_variants


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Create an all-outcomes deterministic PDDL domain from a FOND domain."
        )
    )
    parser.add_argument(
        "domain_file",
        help="Path to the non-deterministic PDDL domain file.",
    )
    parser.add_argument(
        "-o",
        "--output",
        help=(
            "Path where the deterministic domain should be written. "
            "If omitted, the domain is printed to stdout."
        ),
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite the output file if it already exists.",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    domain_path = Path(args.domain_file)
    output_path = Path(args.output) if args.output else None

    if output_path and output_path.exists() and not args.force:
        raise SystemExit(
            f"Output file already exists: {output_path}. Use --force to overwrite it."
        )

    domain = parse_domain(domain_path)
    nondeterministic_actions, deterministic_variants = count_nondeterministic_actions(
        domain
    )
    deterministic_domain = determinize(domain)
    output = domain_to_string(deterministic_domain) + "\n"

    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(output, encoding="utf-8")
        print(f"Wrote deterministic domain: {output_path}", file=sys.stderr)
    else:
        sys.stdout.write(output)

    print(
        "Determinized "
        f"{nondeterministic_actions} non-deterministic action(s) into "
        f"{deterministic_variants} deterministic outcome action(s).",
        file=sys.stderr,
    )
    print(
        f"Actions: {len(domain.actions)} -> {len(deterministic_domain.actions)}",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
