"""Deterministic branch/condition evaluation for route & gate nodes (pure).

These nodes are the kernel's *fixed* decision points: they evaluate a small,
safe boolean expression over the current run environment and pick a target —
no model in the loop. This keeps routing deterministic and auditable.

The expression language is deliberately tiny and safe (no ``eval``/``exec``):

    expr    := or
    or      := and ( "or" and )*
    and     := unary ( "and" unary )*
    unary   := "not" unary | primary
    primary := "(" expr ")" | operand ( ("=="|"!="|"in"|"contains") operand )?
    operand := STRING | NUMBER | BOOL | IDENT

Variables are looked up in the run environment (context, report, ok, ...).
Unknown variables raise ``ConditionError`` (deterministic, catches typos).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .models import Node


class ConditionError(Exception):
    """Raised when a condition expression is malformed or references a bad var."""


# -- tokenizer ---------------------------------------------------------------

_TOKEN_RE = re.compile(r"""
    (?P<space>\s+)
  | (?P<lpar>\()
  | (?P<rpar>\))
  | (?P<op>==|!=|in|contains)
  | (?P<not>\bnot\b)
  | (?P<and>\band\b)
  | (?P<or>\bor\b)
  | (?P<number>-?\d+(?:\.\d+)?)
  | (?P<str>"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')
  | (?P<ident>[A-Za-z_][A-Za-z0-9_]*)
""", re.VERBOSE | re.IGNORECASE)

_SKIP = {"space"}

_OPERATORS = {"==", "!=", "in", "contains"}


@dataclass
class _Token:
    kind: str
    value: object


def _tokenize(expr: str) -> list[_Token]:
    tokens: list[_Token] = []
    pos = 0
    while pos < len(expr):
        m = _TOKEN_RE.match(expr, pos)
        if not m:
            raise ConditionError(f"unexpected character at {pos}: {expr[pos]!r}")
        pos = m.end()
        kind = m.lastgroup
        if kind in _SKIP:
            continue
        if kind == "op":
            tokens.append(_Token("op", m.group().lower()))
        elif kind == "str":
            raw = m.group()
            tokens.append(_Token("str", raw[1:-1].replace(r"\'", "'").replace(r'\"', '"')))
        elif kind == "number":
            tokens.append(_Token("number", float(m.group())))
        elif kind == "ident":
            tokens.append(_Token("ident", m.group()))
        else:
            tokens.append(_Token(kind, None))
    tokens.append(_Token("eof", None))
    return tokens


# -- parser (recursive descent) ----------------------------------------------

class _Parser:
    def __init__(self, tokens: list[_Token], env: dict) -> None:
        self.tokens = tokens
        self.pos = 0
        self.env = env

    def peek(self) -> _Token:
        return self.tokens[self.pos]

    def advance(self) -> _Token:
        tok = self.tokens[self.pos]
        self.pos += 1
        return tok

    def expect(self, kind: str) -> None:
        if self.peek().kind != kind:
            raise ConditionError(f"expected {kind}, got {self.peek().kind!r}")
        self.advance()

    def parse(self) -> bool:
        value = self.parse_or()
        if self.peek().kind != "eof":
            raise ConditionError(f"unexpected token {self.peek().kind!r}")
        return value

    def parse_or(self) -> bool:
        left = self.parse_and()
        while self.peek().kind == "or":
            self.advance()
            right = self.parse_and()
            left = bool(left) or bool(right)
        return left

    def parse_and(self) -> bool:
        left = self.parse_unary()
        while self.peek().kind == "and":
            self.advance()
            right = self.parse_unary()
            left = bool(left) and bool(right)
        return left

    def parse_unary(self) -> bool:
        if self.peek().kind == "not":
            self.advance()
            return not self.parse_unary()
        return self.parse_primary()

    def parse_primary(self) -> object:
        tok = self.peek()
        if tok.kind == "lpar":
            self.advance()
            value = self.parse_or()
            self.expect("rpar")
            return value
        if tok.kind in ("str", "number", "ident"):
            left_tok = self.advance()
            left = self._operand_value(left_tok)
            # bare value truthiness (e.g. `ok` or `report`)
            if self.peek().kind != "op":
                return bool(left)
            op = self.advance().value
            right_tok = self.advance()
            if right_tok.kind not in ("str", "number", "ident"):
                raise ConditionError(f"expected operand after {op!r}, got {right_tok.kind!r}")
            right = self._operand_value(right_tok)
            return self._compare(left, op, right)
        raise ConditionError(f"unexpected token {tok.kind!r}")

    # -- semantics -----------------------------------------------------------

    def _operand_value(self, tok: _Token) -> object:
        """Resolve an operand token: identifiers from env, literals as-is."""
        if tok.kind == "ident":
            if tok.value not in self.env:
                raise ConditionError(
                    f"unknown variable {tok.value!r} (known: {', '.join(sorted(self.env))})"
                )
            return self.env[tok.value]
        return tok.value

    @staticmethod
    def _compare(left: object, op: str, right: object) -> bool:
        if op == "in":
            return str(left) in str(right)  # `X in Y`: X is substring of Y
        if op == "contains":
            return str(right) in str(left)  # `X contains Y`: Y is substring of X
        if op == "==":
            return _same_value(left, right)
        if op == "!=":
            return not _same_value(left, right)
        raise ConditionError(f"unknown operator {op!r}")


def evaluate(expr: str, env: dict) -> bool:
    """Evaluate a condition expression against an environment dict.

    Raises ``ConditionError`` on malformed expressions or unknown variables.
    """
    if not expr or not expr.strip():
        return True
    return _Parser(_tokenize(expr), env).parse()


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _same_value(left: object, right: object) -> bool:
    """Value equality: numeric operands compare numerically, else stringified.

    Avoids the int/float mismatch (e.g. ``x == 3`` with ``x=3`` should hold
    even though ``str(3) != str(3.0)``).
    """
    if _is_number(left) and _is_number(right):
        return left == right
    return str(left) == str(right)


def resolve_branch(node: Node, env: dict) -> str | None:
    """Return the ``goto`` of the first matching branch, or None.

    Branches are evaluated in declaration order; the first whose ``when``
    condition is true wins. Returns None when no branch matches (the caller
    falls back to ``node.next``, or blocks for a hard gate).
    """
    for branch in node.branches or []:
        if evaluate(branch.when, env):
            return branch.goto
    return None