from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile

from pddl import parse_problem


@dataclass(frozen=True)
class UtilityAssignment:
    predicate: str
    arguments: tuple
    value: float


# Parses a PDDL problem while preserving custom utility assignments.
def parse_problem_with_utility(problem_file):
    text = Path(problem_file).read_text(encoding="utf-8")
    stripped_text, utility_sections = _extract_sections(text, ":utility")

    with NamedTemporaryFile(
        mode="w",
        suffix=".pddl",
        encoding="utf-8",
        delete=False,
    ) as tmp:
        tmp.write(stripped_text)
        tmp_path = tmp.name

    try:
        problem = parse_problem(tmp_path)
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    problem.utility = []
    for section in utility_sections:
        problem.utility.extend(_parse_utility_section(section))

    return problem


# Extracts sections.
def _extract_sections(text, section_name):
    section_name = section_name.lower()
    spans = []
    sections = []
    i = 0

    while i < len(text):
        if text[i] == ";":
            i = _skip_comment(text, i)
            continue

        if text[i] != "(":
            i += 1
            continue

        token_start = _skip_ws_and_comments(text, i + 1)
        token_end = _read_token_end(text, token_start)
        token = text[token_start:token_end].lower()

        if token == section_name:
            section_end = _find_matching_paren(text, i)
            spans.append((i, section_end))
            sections.append(text[i:section_end])
            i = section_end
            continue

        i += 1

    stripped = []
    last = 0
    for start, end in spans:
        stripped.append(text[last:start])
        last = end
    stripped.append(text[last:])

    return "".join(stripped), sections


# Parses utility section.
def _parse_utility_section(section):
    tokens = _tokenize(section)
    pos = 0

    pos = _expect(tokens, pos, "(")
    if tokens[pos].lower() != ":utility":
        raise ValueError("Expected :utility section.")
    pos += 1

    assignments = []
    while pos < len(tokens) and tokens[pos] != ")":
        assignment, pos = _parse_utility_assignment(tokens, pos)
        assignments.append(assignment)

    pos = _expect(tokens, pos, ")")
    if pos != len(tokens):
        raise ValueError("Unexpected tokens after :utility section.")

    return assignments


# Parses utility assignment.
def _parse_utility_assignment(tokens, pos):
    pos = _expect(tokens, pos, "(")
    pos = _expect(tokens, pos, "=")
    pos = _expect(tokens, pos, "(")

    if pos >= len(tokens) or tokens[pos] in {"(", ")"}:
        raise ValueError("Expected predicate name in :utility assignment.")

    predicate = tokens[pos]
    pos += 1
    arguments = []
    while pos < len(tokens) and tokens[pos] != ")":
        if tokens[pos] in {"(", "="}:
            raise ValueError("Unexpected token in utility literal.")
        arguments.append(tokens[pos])
        pos += 1

    pos = _expect(tokens, pos, ")")

    if pos >= len(tokens):
        raise ValueError("Expected numeric utility value.")
    try:
        value = float(tokens[pos])
    except ValueError as exc:
        raise ValueError(f"Invalid utility value: {tokens[pos]}") from exc
    pos += 1

    pos = _expect(tokens, pos, ")")
    return UtilityAssignment(predicate, tuple(arguments), value), pos


# Handles the internal tokenize step.
def _tokenize(text):
    tokens = []
    i = 0
    while i < len(text):
        c = text[i]
        if c == ";":
            i = _skip_comment(text, i)
            continue
        if c.isspace():
            i += 1
            continue
        if c in "()":
            tokens.append(c)
            i += 1
            continue

        j = i
        while j < len(text) and not text[j].isspace() and text[j] not in "();":
            j += 1
        tokens.append(text[i:j])
        i = j

    return tokens


# Handles the internal expect step.
def _expect(tokens, pos, expected):
    if pos >= len(tokens) or tokens[pos] != expected:
        found = "<eof>" if pos >= len(tokens) else tokens[pos]
        raise ValueError(f"Expected {expected}, found {found}.")
    return pos + 1


# Handles the internal skip comment step.
def _skip_comment(text, i):
    while i < len(text) and text[i] != "\n":
        i += 1
    return i


# Handles the internal skip ws and comments step.
def _skip_ws_and_comments(text, i):
    while i < len(text):
        if text[i].isspace():
            i += 1
            continue
        if text[i] == ";":
            i = _skip_comment(text, i)
            continue
        break
    return i


# Handles the internal read token end step.
def _read_token_end(text, i):
    while i < len(text) and not text[i].isspace() and text[i] not in "();":
        i += 1
    return i


# Handles the internal find matching paren step.
def _find_matching_paren(text, start):
    depth = 0
    i = start

    while i < len(text):
        if text[i] == ";":
            i = _skip_comment(text, i)
            continue
        if text[i] == "(":
            depth += 1
        elif text[i] == ")":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1

    raise ValueError("Unclosed parenthesized section.")
