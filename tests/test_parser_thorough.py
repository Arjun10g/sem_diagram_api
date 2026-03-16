import pytest
from app.services.parser import parse_sem_syntax


def test_basic_loading_parsing():
    syntax = "f =~ x1 + x2 + x3"
    g = parse_sem_syntax(syntax)
    assert len(g.statements) == 3
    assert all(s.stmt_type.value == "loading" for s in g.statements)


def test_regression_and_covariance():
    syntax = "y ~ x\nx ~~ z"
    g = parse_sem_syntax(syntax)
    types = [s.stmt_type.value for s in g.statements]
    assert "regression" in types
    assert "covariance" in types


def test_defined_parameter():
    syntax = "ind := a*b"
    g = parse_sem_syntax(syntax)
    assert len(g.defined_parameters) == 1


def test_constraint():
    syntax = "a > 0"
    g = parse_sem_syntax(syntax)
    assert len(g.constraints) == 1


def test_comments_ignored():
    syntax = "f =~ x1 + x2  # comment"
    g = parse_sem_syntax(syntax)
    assert len(g.statements) == 2
