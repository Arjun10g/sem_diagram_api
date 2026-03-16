from __future__ import annotations

import re
from typing import List, Optional, Tuple

from app.models.sem_graph import (
    ConstraintSpec,
    DefinedParameter,
    ParameterSpec,
    ParsedStatement,
    SemGraph,
    Severity,
    StatementType,
)


# ============================================================
# Regex patterns
# ============================================================

IDENTIFIER_RE = r"[A-Za-z_][A-Za-z0-9_\.]*"
NUMBER_RE = r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?"

DEFINED_RE = re.compile(
    rf"^\s*(?P<lhs>{IDENTIFIER_RE})\s*:=\s*(?P<rhs>.+?)\s*$"
)

CONSTRAINT_RE = re.compile(
    r"^\s*(?P<lhs>.+?)\s*(?P<op>==|>=|<=|>|<)\s*(?P<rhs>.+?)\s*$"
)

START_MOD_RE = re.compile(
    rf"^start\(\s*(?P<value>{NUMBER_RE})\s*\)$",
    re.IGNORECASE,
)

# Used only for atomic validation of variable-like names on RHS.
VARIABLE_NAME_RE = re.compile(rf"^{IDENTIFIER_RE}$")


# ============================================================
# Public API
# ============================================================

def parse_sem_syntax(model_text: str) -> SemGraph:
    """
    Parse lavaan-style SEM syntax into a SemGraph containing:
      - ParsedStatement objects
      - DefinedParameter objects
      - ConstraintSpec objects
      - parser messages

    This is a syntax parser, not a model-fitting parser.
    It atomizes RHS expansions, so:

        visual =~ x1 + x2 + x3

    becomes 3 ParsedStatement objects.

    Current parser goals:
    - readable and maintainable
    - helpful diagnostics
    - robust enough for common lavaan path/model syntax
    - extensible for future modifiers and statement types
    """
    graph = SemGraph()

    if model_text is None:
        graph.add_message(
            Severity.ERROR,
            "empty_input",
            "Model text is None.",
        )
        return graph

    if not isinstance(model_text, str):
        graph.add_message(
            Severity.ERROR,
            "invalid_input_type",
            f"Model text must be a string, got {type(model_text).__name__}.",
        )
        return graph

    lines = _preprocess_lines(model_text)

    if not lines:
        graph.add_message(
            Severity.WARNING,
            "empty_model",
            "No non-empty SEM syntax lines found.",
        )
        return graph

    for line_no, raw_line, clean_line in lines:
        _parse_single_line(
            line_no=line_no,
            raw_line=raw_line,
            clean_line=clean_line,
            graph=graph,
        )

    if not graph.statements and not graph.defined_parameters and not graph.constraints:
        graph.add_message(
            Severity.WARNING,
            "no_parsed_content",
            "No parsable SEM statements were found.",
        )

    graph.metadata.setdefault("parser", {})
    graph.metadata["parser"]["n_input_lines"] = len(model_text.splitlines())
    graph.metadata["parser"]["n_nonempty_lines"] = len(lines)
    graph.metadata["parser"]["n_statements"] = len(graph.statements)
    graph.metadata["parser"]["n_defined_parameters"] = len(graph.defined_parameters)
    graph.metadata["parser"]["n_constraints"] = len(graph.constraints)

    return graph


# ============================================================
# Line preprocessing
# ============================================================

def _preprocess_lines(model_text: str) -> List[Tuple[int, str, str]]:
    """
    Returns:
      [(line_number, raw_line, clean_line), ...]

    Cleaning behavior:
    - strip trailing comments beginning with '#'
    - trim whitespace
    - drop empty lines
    """
    output: List[Tuple[int, str, str]] = []

    for idx, raw in enumerate(model_text.splitlines(), start=1):
        no_comment = _strip_comment(raw)
        clean = no_comment.strip()

        if clean:
            output.append((idx, raw, clean))

    return output


def _strip_comment(line: str) -> str:
    """
    Strip comments starting with '#'.

    Current behavior:
    - everything after the first # is treated as a comment
    """
    return re.sub(r"\s*#.*$", "", line)


# ============================================================
# Single-line dispatch
# ============================================================

def _parse_single_line(
    line_no: int,
    raw_line: str,
    clean_line: str,
    graph: SemGraph,
) -> None:
    """
    Parse one already-cleaned line and append results into graph.

    Dispatch order matters.
    """
    if _has_unbalanced_parentheses(clean_line):
        graph.add_message(
            Severity.ERROR,
            "unbalanced_parentheses",
            f"Unbalanced parentheses on line {line_no}.",
            line_no=line_no,
            context=raw_line,
        )
        return

    if ":=" in clean_line:
        _parse_defined_parameter_line(line_no, raw_line, clean_line, graph)
        return

    if "=~" in clean_line:
        _parse_operator_line(
            line_no=line_no,
            raw_line=raw_line,
            clean_line=clean_line,
            operator="=~",
            stmt_kind=StatementType.LOADING,
            graph=graph,
        )
        return

    if "~~" in clean_line:
        _parse_operator_line(
            line_no=line_no,
            raw_line=raw_line,
            clean_line=clean_line,
            operator="~~",
            stmt_kind=None,
            graph=graph,
        )
        return

    # Check constraints before plain "~" only when line does not contain model operators.
    if _looks_like_constraint(clean_line) and "~" not in clean_line:
        _parse_constraint_line(line_no, raw_line, clean_line, graph)
        return

    if "~" in clean_line:
        _parse_operator_line(
            line_no=line_no,
            raw_line=raw_line,
            clean_line=clean_line,
            operator="~",
            stmt_kind=None,
            graph=graph,
        )
        return

    if _looks_like_constraint(clean_line):
        _parse_constraint_line(line_no, raw_line, clean_line, graph)
        return

    graph.add_message(
        Severity.WARNING,
        "unparsed_line",
        f"Unsupported or unparsed syntax on line {line_no}.",
        line_no=line_no,
        context=raw_line,
    )


# ============================================================
# Defined parameters
# ============================================================

def _parse_defined_parameter_line(
    line_no: int,
    raw_line: str,
    clean_line: str,
    graph: SemGraph,
) -> None:
    match = DEFINED_RE.match(clean_line)
    if not match:
        graph.add_message(
            Severity.ERROR,
            "invalid_defined_parameter",
            f"Could not parse defined parameter on line {line_no}.",
            line_no=line_no,
            context=raw_line,
        )
        return

    lhs = match.group("lhs").strip()
    rhs = match.group("rhs").strip()

    if not lhs:
        graph.add_message(
            Severity.ERROR,
            "missing_defined_parameter_name",
            f"Missing defined parameter name on line {line_no}.",
            line_no=line_no,
            context=raw_line,
        )
        return

    if not rhs:
        graph.add_message(
            Severity.ERROR,
            "missing_defined_parameter_expression",
            f"Missing defined parameter expression on line {line_no}.",
            line_no=line_no,
            context=raw_line,
        )
        return

    graph.add_defined_parameter(
        DefinedParameter(
            name=lhs,
            expression=rhs,
            line_no=line_no,
            raw=raw_line,
        )
    )


# ============================================================
# Constraints
# ============================================================

def _looks_like_constraint(line: str) -> bool:
    return any(op in line for op in ["==", ">=", "<=", ">", "<"])


def _parse_constraint_line(
    line_no: int,
    raw_line: str,
    clean_line: str,
    graph: SemGraph,
) -> None:
    match = CONSTRAINT_RE.match(clean_line)
    if not match:
        graph.add_message(
            Severity.ERROR,
            "invalid_constraint",
            f"Could not parse constraint on line {line_no}.",
            line_no=line_no,
            context=raw_line,
        )
        return

    lhs = match.group("lhs").strip()
    rhs = match.group("rhs").strip()

    if not lhs or not rhs:
        graph.add_message(
            Severity.ERROR,
            "malformed_constraint",
            f"Constraint on line {line_no} is missing a left-hand side or right-hand side.",
            line_no=line_no,
            context=raw_line,
        )
        return

    graph.add_constraint(
        ConstraintSpec(
            expression=clean_line.strip(),
            line_no=line_no,
            raw=raw_line,
        )
    )


# ============================================================
# Main operator parsing
# ============================================================

def _parse_operator_line(
    line_no: int,
    raw_line: str,
    clean_line: str,
    operator: str,
    stmt_kind: Optional[StatementType],
    graph: SemGraph,
) -> None:
    """
    Parse a model statement of the form:

      lhs <operator> rhs1 + rhs2 + rhs3

    and atomize into one ParsedStatement per RHS term.
    """
    parts = _split_on_operator(clean_line, operator)

    if parts is None:
        graph.add_message(
            Severity.ERROR,
            "invalid_operator_statement",
            f"Could not parse statement using operator '{operator}' on line {line_no}.",
            line_no=line_no,
            context=raw_line,
        )
        return

    lhs, rhs_text = parts
    lhs = lhs.strip()
    rhs_text = rhs_text.strip()

    if not lhs:
        graph.add_message(
            Severity.ERROR,
            "missing_lhs",
            f"Missing left-hand side on line {line_no}.",
            line_no=line_no,
            context=raw_line,
        )
        return

    if not _looks_like_identifier(lhs):
        graph.add_message(
            Severity.WARNING,
            "nonstandard_lhs_name",
            f"Left-hand side '{lhs}' on line {line_no} is not a standard identifier.",
            line_no=line_no,
            context=raw_line,
        )

    if not rhs_text:
        graph.add_message(
            Severity.ERROR,
            "missing_rhs",
            f"Missing right-hand side on line {line_no}.",
            line_no=line_no,
            context=raw_line,
        )
        return

    rhs_terms = _split_rhs_terms(rhs_text, line_no=line_no, raw_line=raw_line, graph=graph)

    if not rhs_terms:
        graph.add_message(
            Severity.ERROR,
            "empty_rhs_terms",
            f"No valid right-hand side terms found on line {line_no}.",
            line_no=line_no,
            context=raw_line,
        )
        return

    for term in rhs_terms:
        parameter, rhs_variable, term_metadata = _parse_rhs_term(
            term=term,
            line_no=line_no,
            raw_line=raw_line,
            graph=graph,
        )

        if rhs_variable is None:
            continue

        atomic_stmt_type = stmt_kind or _resolve_statement_type(
            operator=operator,
            lhs=lhs,
            rhs=rhs_variable,
        )

        graph.add_statement(
            ParsedStatement(
                stmt_type=atomic_stmt_type,
                lhs=lhs,
                rhs=rhs_variable,
                operator=operator,
                line_no=line_no,
                raw=raw_line,
                parameter=parameter,
                metadata={
                    "raw_line_clean": clean_line,
                    "lhs": lhs,
                    "rhs_text": rhs_text,
                    **term_metadata,
                },
            )
        )


def _split_on_operator(line: str, operator: str) -> Optional[Tuple[str, str]]:
    """
    Split on the first occurrence of operator.
    """
    parts = line.split(operator, 1)
    if len(parts) != 2:
        return None
    return parts[0], parts[1]


def _resolve_statement_type(operator: str, lhs: str, rhs: str) -> StatementType:
    """
    Determine atomic statement type after one RHS term is isolated.
    """
    if operator == "=~":
        return StatementType.LOADING

    if operator == "~~":
        return StatementType.VARIANCE if lhs == rhs else StatementType.COVARIANCE

    if operator == "~":
        return StatementType.INTERCEPT if rhs == "1" else StatementType.REGRESSION

    return StatementType.UNKNOWN


# ============================================================
# RHS splitting
# ============================================================

def _split_rhs_terms(
    rhs_text: str,
    *,
    line_no: int,
    raw_line: str,
    graph: SemGraph,
) -> List[str]:
    """
    Split RHS on top-level plus signs.

    Handles common cases like:
      x1 + x2 + x3
      a*x1 + b*x2 + start(0.5)*x3

    Plus signs inside parentheses are preserved.
    """
    terms: List[str] = []
    current: List[str] = []
    depth = 0

    for ch in rhs_text:
        if ch == "(":
            depth += 1
            current.append(ch)
        elif ch == ")":
            depth = max(depth - 1, 0)
            current.append(ch)
        elif ch == "+" and depth == 0:
            term = "".join(current).strip()
            if term:
                terms.append(term)
            else:
                graph.add_message(
                    Severity.WARNING,
                    "empty_rhs_term_between_plus",
                    f"Empty RHS term found between '+' separators on line {line_no}.",
                    line_no=line_no,
                    context=raw_line,
                )
            current = []
        else:
            current.append(ch)

    final = "".join(current).strip()
    if final:
        terms.append(final)
    else:
        if rhs_text.rstrip().endswith("+"):
            graph.add_message(
                Severity.WARNING,
                "trailing_plus_rhs",
                f"RHS on line {line_no} ends with '+', leaving an empty final term.",
                line_no=line_no,
                context=raw_line,
            )

    return terms


# ============================================================
# RHS term parsing
# ============================================================

def _parse_rhs_term(
    term: str,
    line_no: int,
    raw_line: str,
    graph: SemGraph,
) -> Tuple[ParameterSpec, Optional[str], dict]:
    """
    Parse a single RHS term.

    Supported examples:
      x1
      a*x1
      1*x1
      NA*x1
      start(0.5)*x1
      label*start(0.5)*x1
      start(0.5)*label*x1

    Returns:
      (ParameterSpec, rhs_variable, metadata)
    """
    term = term.strip()

    if not term:
        graph.add_message(
            Severity.WARNING,
            "empty_rhs_term",
            f"Encountered an empty RHS term on line {line_no}.",
            line_no=line_no,
            context=raw_line,
        )
        return ParameterSpec(), None, {}

    pieces = _split_top_level_stars(term, line_no=line_no, raw_line=raw_line, graph=graph)

    if not pieces:
        graph.add_message(
            Severity.ERROR,
            "invalid_rhs_term",
            f"Invalid RHS term on line {line_no}: '{term}'",
            line_no=line_no,
            context=raw_line,
        )
        return ParameterSpec(), None, {}

    # Plain variable
    if len(pieces) == 1:
        rhs_variable = pieces[0].strip()

        if not rhs_variable:
            graph.add_message(
                Severity.ERROR,
                "invalid_rhs_term",
                f"Invalid RHS term on line {line_no}: '{term}'",
                line_no=line_no,
                context=raw_line,
            )
            return ParameterSpec(), None, {}

        if rhs_variable != "1" and not _looks_like_identifier(rhs_variable):
            graph.add_message(
                Severity.WARNING,
                "nonstandard_rhs_variable",
                f"RHS variable '{rhs_variable}' on line {line_no} is not a standard identifier.",
                line_no=line_no,
                context=raw_line,
            )

        return ParameterSpec(), rhs_variable, {
            "raw_term": term,
            "rhs_variable": rhs_variable,
            "modifiers": [],
            "n_modifiers": 0,
        }

    variable = pieces[-1].strip()
    modifiers = [piece.strip() for piece in pieces[:-1] if piece.strip()]

    if not variable:
        graph.add_message(
            Severity.ERROR,
            "missing_rhs_variable",
            f"Missing RHS variable in term '{term}' on line {line_no}.",
            line_no=line_no,
            context=raw_line,
        )
        return ParameterSpec(), None, {}

    if variable != "1" and not _looks_like_identifier(variable):
        graph.add_message(
            Severity.WARNING,
            "nonstandard_rhs_variable",
            f"RHS variable '{variable}' on line {line_no} is not a standard identifier.",
            line_no=line_no,
            context=raw_line,
        )

    parameter = ParameterSpec()
    metadata = {
        "raw_term": term,
        "rhs_variable": variable,
        "modifiers": modifiers,
        "n_modifiers": len(modifiers),
    }

    for mod in modifiers:
        _apply_modifier(
            modifier=mod,
            parameter=parameter,
            metadata=metadata,
            line_no=line_no,
            raw_line=raw_line,
            graph=graph,
        )

    return parameter, variable, metadata


def _split_top_level_stars(
    term: str,
    *,
    line_no: int,
    raw_line: str,
    graph: SemGraph,
) -> List[str]:
    """
    Split on '*' not inside parentheses.

    Examples:
      start(0.5)*x1 -> ["start(0.5)", "x1"]
      a*x1 -> ["a", "x1"]
      label*start(1.2)*x1 -> ["label", "start(1.2)", "x1"]
    """
    pieces: List[str] = []
    current: List[str] = []
    depth = 0

    for ch in term:
        if ch == "(":
            depth += 1
            current.append(ch)
        elif ch == ")":
            depth = max(depth - 1, 0)
            current.append(ch)
        elif ch == "*" and depth == 0:
            piece = "".join(current).strip()
            if not piece:
                graph.add_message(
                    Severity.WARNING,
                    "empty_modifier_piece",
                    f"Empty modifier piece found around '*' in term '{term}' on line {line_no}.",
                    line_no=line_no,
                    context=raw_line,
                )
            pieces.append(piece)
            current = []
        else:
            current.append(ch)

    final = "".join(current).strip()
    if not final:
        graph.add_message(
            Severity.WARNING,
            "missing_rhs_after_star",
            f"Term '{term}' on line {line_no} ends with '*', leaving an empty final piece.",
            line_no=line_no,
            context=raw_line,
        )
    pieces.append(final)

    return pieces


def _apply_modifier(
    modifier: str,
    parameter: ParameterSpec,
    metadata: dict,
    line_no: int,
    raw_line: str,
    graph: SemGraph,
) -> None:
    """
    Apply one modifier to a ParameterSpec.

    Supported:
      - numeric fixed values: 1, 0.5, -1
      - labels: a, beta1, load_x2
      - NA
      - start(0.5)

    Current policy:
    - first/last repeated modifier wins, but a warning is emitted
    - numeric modifier sets fixed and free=False
    - NA marks free=True and records metadata
    - label sets parameter.label
    - start(...) sets parameter.start
    """
    mod = modifier.strip()

    if not mod:
        graph.add_message(
            Severity.WARNING,
            "blank_modifier",
            f"Blank modifier found on line {line_no}.",
            line_no=line_no,
            context=raw_line,
        )
        return

    start_match = START_MOD_RE.match(mod)
    if start_match:
        value = float(start_match.group("value"))
        if parameter.start is not None:
            graph.add_message(
                Severity.WARNING,
                "duplicate_start_modifier",
                f"Multiple start() modifiers found on line {line_no}; keeping latest.",
                line_no=line_no,
                context=raw_line,
            )
        parameter.start = value
        metadata["has_start_modifier"] = True
        return

    if mod.upper() == "NA":
        metadata["na_modifier"] = True
        parameter.free = True
        return

    if _is_number(mod):
        value = float(mod)
        if parameter.fixed is not None:
            graph.add_message(
                Severity.WARNING,
                "duplicate_fixed_modifier",
                f"Multiple fixed numeric modifiers found on line {line_no}; keeping latest.",
                line_no=line_no,
                context=raw_line,
            )
        parameter.fixed = value
        parameter.free = False
        metadata["has_fixed_modifier"] = True
        return

    if _looks_like_label(mod):
        if parameter.label is not None:
            graph.add_message(
                Severity.WARNING,
                "duplicate_label_modifier",
                f"Multiple label-like modifiers found on line {line_no}; keeping latest.",
                line_no=line_no,
                context=raw_line,
            )
        parameter.label = mod
        metadata["has_label_modifier"] = True
        return

    graph.add_message(
        Severity.WARNING,
        "unknown_modifier",
        f"Unknown modifier '{modifier}' on line {line_no}.",
        line_no=line_no,
        context=raw_line,
    )
    metadata.setdefault("unknown_modifiers", []).append(modifier)


# ============================================================
# Primitive checks
# ============================================================

def _is_number(text: str) -> bool:
    return re.fullmatch(NUMBER_RE, text.strip()) is not None


def _looks_like_label(text: str) -> bool:
    """
    Conservative label rule:
    - starts with letter or underscore
    - continues with letters/digits/underscore/dot
    """
    return re.fullmatch(IDENTIFIER_RE, text.strip()) is not None


def _looks_like_identifier(text: str) -> bool:
    return VARIABLE_NAME_RE.fullmatch(text.strip()) is not None


def _has_unbalanced_parentheses(text: str) -> bool:
    depth = 0
    for ch in text:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth < 0:
                return True
    return depth != 0