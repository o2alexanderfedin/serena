"""calcpy.calcpy - headline monolith for Stage 1H.

Lexer -> parser -> AST -> evaluator. Single-file calculator implemented as
the canonical "ugly-on-purpose" Python fixture per specialist-python.md
sec.11.2. The ten ugly features below are enumerated in the leaf 06 spec
and exercised verbatim by the leaf 04 integration tests; the file is
deliberately monolithic so split-file refactors have something realistic
to chew on.

The ten ugly-on-purpose features (all present below):

1. Deeply nested classes (``Token`` / ``TokenKind`` / ``TokenStream``)
2. Monkey-patched module-level constants (``DEBUG``, ``_MAX_DEPTH``)
3. ``from __future__ import annotations``
4. ``if TYPE_CHECKING:`` import shadowing (re-import ``Iterator`` from
   ``collections.abc``)
5. ``__all__`` declaration
6. ``_private`` + ``__name_mangle`` attributes inside ``evaluate``'s helper
7. ``if __name__ == "__main__":`` REPL shim (read stdin, print result)
8. ``@dataclass(frozen=True)`` ``Token``
9. doctest-bearing functions (``>>>`` blocks on ``tokenize``, ``parse``,
   ``evaluate``, ``ParseError``)
10. PEP 604 union types (``int | float``, ``int | float | None``)

Public API (kept stable - downstream tests assert ``__all__``):

* ``tokenize(source: str) -> list[Token]``
* ``parse(source: str) -> AstNode``
* ``evaluate(node: AstNode) -> int | float``
* ``Token``, ``TokenKind``, ``ParseError``, ``AstNode``,
  ``IntLit``, ``FloatLit``, ``BinOp``, ``UnaryOp``

Grammar (recursive descent with precedence climbing)::

    expr    := term ((PLUS | MINUS) term)*
    term    := factor ((STAR | SLASH) factor)*
    factor  := (PLUS | MINUS) factor | INT | FLOAT | LPAREN expr RPAREN
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Iterator, Sequence

if TYPE_CHECKING:
    # Ugly-on-purpose feature #4: TYPE_CHECKING import shadowing.
    # `Iterator` is already imported above from `typing`; re-importing
    # the same name from `collections.abc` exercises pyright's import
    # shadowing handling and the split-file flow's import-rewrite path.
    from collections.abc import Iterator  # noqa: F401,F811

# Ugly-on-purpose feature #5: __all__ declaration.
__all__ = [
    "AstNode",
    "BinOp",
    "FloatLit",
    "IntLit",
    "ParseError",
    "Token",
    "TokenKind",
    "UnaryOp",
    "evaluate",
    "parse",
    "tokenize",
]

# Ugly-on-purpose feature #2: monkey-patched module-level constants.
# Tests/fixtures may rebind ``DEBUG`` to ``True`` or shrink ``_MAX_DEPTH``
# to drive ParseError paths in the evaluator's recursion guard.
DEBUG: bool = False
_MAX_DEPTH: int = 64


# ---------------------------------------------------------------------------
# Token + Token kinds (ugly-on-purpose features #1 and #8)
# ---------------------------------------------------------------------------


class TokenKind:
    """Namespace of token kind string constants.

    Kept as a class (rather than ``enum.Enum``) so the deeply-nested
    classes feature stays readable and so the kind values are plain
    strings - simplifying the doctests + ``Token.kind`` checks.
    """

    INT: str = "INT"
    FLOAT: str = "FLOAT"
    PLUS: str = "PLUS"
    MINUS: str = "MINUS"
    STAR: str = "STAR"
    SLASH: str = "SLASH"
    LPAREN: str = "LPAREN"
    RPAREN: str = "RPAREN"
    EOF: str = "EOF"

    # Ugly-on-purpose feature #1: a class nested inside another class.
    # ``TokenStream`` is logically a Token concern (peek/advance over
    # tokens) so it lives here. Parsers consume a TokenStream rather
    # than indexing the raw list.
    class TokenStream:
        """Cursor over a list of ``Token`` with lookahead.

        The stream synthesises an EOF sentinel locally rather than
        requiring the lexer to emit it - keeps ``tokenize``'s public
        contract a clean list of "real" tokens.
        """

        def __init__(self, tokens: Sequence["Token"]) -> None:
            self._tokens: list[Token] = list(tokens)
            self._pos: int = 0
            # Synthesised EOF sentinel; pos = end of source if the
            # stream is non-empty, else 0.
            last_pos = self._tokens[-1].pos + len(self._tokens[-1].text) if self._tokens else 0
            self._eof: Token = Token(kind=TokenKind.EOF, text="", pos=last_pos)

        def peek(self) -> "Token":
            """Return the current token without advancing.

            Returns the synthesised EOF sentinel once the stream is
            exhausted.
            """
            if self._pos >= len(self._tokens):
                return self._eof
            return self._tokens[self._pos]

        def advance(self) -> "Token":
            """Return the current token and advance the cursor."""
            tok = self.peek()
            if self._pos < len(self._tokens):
                self._pos += 1
            return tok

        def at_end(self) -> bool:
            """Return ``True`` if no real tokens remain."""
            return self._pos >= len(self._tokens)


# Ugly-on-purpose feature #8: frozen dataclass.
@dataclass(frozen=True)
class Token:
    """A single lexed token.

    Frozen so tokens are hashable + safely shared across stream copies.
    ``kind`` is one of the string constants on ``TokenKind``.
    ``text`` is the raw source slice (useful for error messages and
    INT/FLOAT value parsing). ``pos`` is the 0-based source offset of
    the first character.
    """

    kind: str
    text: str
    pos: int


# ---------------------------------------------------------------------------
# AST nodes (ugly-on-purpose features #8 and #10 again)
# ---------------------------------------------------------------------------


class AstNode:
    """Marker base for AST nodes - subclasses are frozen dataclasses."""


@dataclass(frozen=True)
class IntLit(AstNode):
    """Integer literal."""

    value: int


@dataclass(frozen=True)
class FloatLit(AstNode):
    """Floating-point literal."""

    value: float


@dataclass(frozen=True)
class BinOp(AstNode):
    """Binary operation. ``op`` is one of ``+``, ``-``, ``*``, ``/``."""

    op: str
    left: AstNode
    right: AstNode


@dataclass(frozen=True)
class UnaryOp(AstNode):
    """Unary prefix operation. ``op`` is one of ``+``, ``-``."""

    op: str
    operand: AstNode


# ---------------------------------------------------------------------------
# ParseError (ugly-on-purpose feature #9: doctest-bearing)
# ---------------------------------------------------------------------------


class ParseError(Exception):
    """Raised on syntactic errors.

    >>> from calcpy import parse, ParseError
    >>> try: parse("1 + + 2")
    ... except ParseError: print("caught")
    caught
    """


# ---------------------------------------------------------------------------
# Lexer
# ---------------------------------------------------------------------------


# Single-character operator -> token kind mapping. Module level so it
# only allocates once.
_SINGLE_CHAR_OPS: dict[str, str] = {
    "+": TokenKind.PLUS,
    "-": TokenKind.MINUS,
    "*": TokenKind.STAR,
    "/": TokenKind.SLASH,
    "(": TokenKind.LPAREN,
    ")": TokenKind.RPAREN,
}


def _is_digit(ch: str) -> bool:
    """Return ``True`` if ``ch`` is an ASCII digit (0-9)."""
    return "0" <= ch <= "9"


def _scan_number(source: str, start: int) -> tuple[str, int, bool]:
    """Scan a numeric literal starting at ``source[start]``.

    Returns ``(text, end, is_float)`` where ``end`` is the exclusive
    end index of the literal in ``source`` and ``is_float`` is True if
    the literal contains a decimal point. Does not handle exponents -
    the calculator grammar is intentionally minimal.
    """
    end = start
    saw_dot = False
    while end < len(source):
        ch = source[end]
        if _is_digit(ch):
            end += 1
            continue
        if ch == "." and not saw_dot:
            # Only consume the dot if it is followed by a digit;
            # otherwise it is a stray punctuation character that the
            # main lexer loop will reject.
            if end + 1 < len(source) and _is_digit(source[end + 1]):
                saw_dot = True
                end += 1
                continue
            break
        break
    return source[start:end], end, saw_dot


def tokenize(source: str) -> list[Token]:
    """Lex ``source`` into a list of ``Token``.

    Whitespace is skipped. INT/FLOAT literals are produced for runs of
    digits (with optional decimal point). Single-character operators
    +/-/*//()/()/ map to their corresponding ``TokenKind``. Any other
    character raises ``ParseError`` with the offending position.

    The returned list contains only "real" tokens; the parser
    synthesises an EOF sentinel locally via ``TokenKind.TokenStream``.
    This keeps ``tokenize``'s public contract simple - one Token per
    lexed lexeme.

    >>> [t.kind for t in tokenize("1 + 2")]
    ['INT', 'PLUS', 'INT']
    """
    tokens: list[Token] = []
    i = 0
    n = len(source)
    while i < n:
        ch = source[i]

        # 1. Skip whitespace - any Python-considered whitespace char.
        if ch.isspace():
            i += 1
            continue

        # 2. Numeric literal.
        if _is_digit(ch):
            text, end, is_float = _scan_number(source, i)
            kind = TokenKind.FLOAT if is_float else TokenKind.INT
            tokens.append(Token(kind=kind, text=text, pos=i))
            i = end
            continue

        # 3. Leading-dot float ("0.5" is fine via the digit branch; the
        # bare ".5" form is rejected by the calculator grammar to keep
        # the lexer simple).
        # (Falls through to the operator branch below.)

        # 4. Single-character operator.
        op_kind = _SINGLE_CHAR_OPS.get(ch)
        if op_kind is not None:
            tokens.append(Token(kind=op_kind, text=ch, pos=i))
            i += 1
            continue

        # 5. Unknown character.
        raise ParseError(f"unexpected character {ch!r} at position {i}")

    if DEBUG:
        # The DEBUG path is dead code in tests by default but exists so
        # the monkey-patched-module-level-constant feature has a real
        # observable effect when a fixture sets ``calcpy.DEBUG = True``.
        for tok in tokens:
            print(f"[calcpy.tokenize] {tok!r}")

    return tokens


# ---------------------------------------------------------------------------
# Parser (recursive descent with precedence climbing)
# ---------------------------------------------------------------------------


def _expect(stream: "TokenKind.TokenStream", kind: str) -> Token:
    """Consume and return the next token, asserting its kind.

    Raises ``ParseError`` if the next token's kind does not match.
    """
    tok = stream.peek()
    if tok.kind != kind:
        raise ParseError(
            f"expected {kind} at position {tok.pos}, got {tok.kind} ({tok.text!r})"
        )
    return stream.advance()


def _parse_atom(stream: "TokenKind.TokenStream") -> AstNode:
    """Parse an atom: literal or parenthesised expr (no unary prefix).

    This is what binary-operator RHS positions consume - rejecting
    chained unary like ``1 + + 2`` directly at the grammar level.
    """
    tok = stream.peek()

    if tok.kind == TokenKind.INT:
        stream.advance()
        try:
            return IntLit(value=int(tok.text))
        except ValueError as exc:
            raise ParseError(f"invalid int literal {tok.text!r}") from exc

    if tok.kind == TokenKind.FLOAT:
        stream.advance()
        try:
            return FloatLit(value=float(tok.text))
        except ValueError as exc:
            raise ParseError(f"invalid float literal {tok.text!r}") from exc

    if tok.kind == TokenKind.LPAREN:
        stream.advance()
        inner = _parse_expr(stream)
        _expect(stream, TokenKind.RPAREN)
        return inner

    raise ParseError(
        f"unexpected token {tok.kind} ({tok.text!r}) at position {tok.pos}"
    )


def _parse_factor(stream: "TokenKind.TokenStream") -> AstNode:
    """Parse a factor: optional unary prefix +/- followed by an atom.

    The unary prefix is only legal at the start of a factor, NOT on the
    RHS of a binary operator - that's enforced by ``_parse_term`` and
    ``_parse_expr`` calling ``_parse_atom`` (not ``_parse_factor``) on
    the RHS. This is what makes ``parse("1 + + 2")`` raise
    ``ParseError`` at the second ``+``: the binary-RHS position calls
    ``_parse_atom``, which does not accept ``+`` as a starter.

    Chained unary like ``+ + 5`` is also rejected - exactly one prefix
    is permitted.
    """
    tok = stream.peek()

    if tok.kind == TokenKind.PLUS or tok.kind == TokenKind.MINUS:
        op_tok = stream.advance()
        # Reject chained unary prefix.
        next_tok = stream.peek()
        if next_tok.kind == TokenKind.PLUS or next_tok.kind == TokenKind.MINUS:
            raise ParseError(
                f"unexpected operator {next_tok.text!r} at position {next_tok.pos}; "
                f"only one unary prefix permitted"
            )
        operand = _parse_atom(stream)
        return UnaryOp(op=op_tok.text, operand=operand)

    return _parse_atom(stream)


def _parse_term(stream: "TokenKind.TokenStream") -> AstNode:
    """Parse a term: factor (* atom | / atom)*."""
    node = _parse_factor(stream)
    while True:
        tok = stream.peek()
        if tok.kind == TokenKind.STAR or tok.kind == TokenKind.SLASH:
            op_tok = stream.advance()
            rhs = _parse_atom(stream)
            node = BinOp(op=op_tok.text, left=node, right=rhs)
            continue
        break
    return node


def _parse_expr(stream: "TokenKind.TokenStream") -> AstNode:
    """Parse an expression: term (+ term-rhs | - term-rhs)*.

    The RHS of a top-level +/- still gets *-/-precedence parsing, but
    that RHS-term itself starts with an atom (no unary). This keeps
    multiplication-on-the-RHS working (``1 + 2 * 3`` -> 7) while
    rejecting unary-on-the-RHS (``1 + + 2`` -> ParseError).
    """
    node = _parse_term(stream)
    while True:
        tok = stream.peek()
        if tok.kind == TokenKind.PLUS or tok.kind == TokenKind.MINUS:
            op_tok = stream.advance()
            # _parse_term itself starts with _parse_factor (which may
            # accept unary). To reject unary-on-binop-RHS we instead
            # parse an atom and then continue with *-/-precedence.
            rhs: AstNode = _parse_atom(stream)
            while True:
                inner = stream.peek()
                if inner.kind == TokenKind.STAR or inner.kind == TokenKind.SLASH:
                    inner_op = stream.advance()
                    inner_rhs = _parse_atom(stream)
                    rhs = BinOp(op=inner_op.text, left=rhs, right=inner_rhs)
                    continue
                break
            node = BinOp(op=op_tok.text, left=node, right=rhs)
            continue
        break
    return node


def parse(source: str) -> AstNode:
    """Parse ``source`` into an ``AstNode`` AST.

    Recursive-descent with precedence climbing (``+``/``-`` lower than
    ``*``/``/``). Raises ``ParseError`` on syntax errors, including
    trailing tokens after a complete expression.

    >>> parse("42")
    IntLit(value=42)
    """
    tokens = tokenize(source)
    if not tokens:
        raise ParseError("empty expression")
    stream = TokenKind.TokenStream(tokens)
    node = _parse_expr(stream)
    if not stream.at_end():
        trailing = stream.peek()
        raise ParseError(
            f"unexpected trailing token {trailing.kind} ({trailing.text!r}) "
            f"at position {trailing.pos}"
        )
    return node


# ---------------------------------------------------------------------------
# Evaluator (ugly-on-purpose features #6 and #10)
# ---------------------------------------------------------------------------


class _Evaluator:
    """Tree-walking interpreter helper.

    Carries the recursion guard + per-evaluation memoisation cache.
    The leading underscore on ``_private`` and the double underscore
    on ``__cache`` (which Python name-mangles to
    ``_Evaluator__cache``) exercise feature #6.
    """

    def __init__(self, max_depth: int) -> None:
        self._private_max_depth: int = max_depth
        # Name-mangled attribute - lookup as ``self.__cache`` inside
        # the class body works; outside the class it's
        # ``ev._Evaluator__cache``. Keys are ``id(node)`` so we don't
        # require AstNode to be hashable beyond dataclass defaults.
        self.__cache: dict[int, int | float] = {}

    def evaluate(self, node: AstNode, depth: int = 0) -> int | float:
        """Evaluate ``node``, guarding against runaway recursion."""
        if depth > self._private_max_depth:
            raise ParseError(
                f"max recursion depth {self._private_max_depth} exceeded"
            )

        cache_key = id(node)
        if cache_key in self.__cache:
            return self.__cache[cache_key]

        result = self._eval_dispatch(node, depth)
        self.__cache[cache_key] = result
        return result

    def _eval_dispatch(self, node: AstNode, depth: int) -> int | float:
        """Dispatch on AST node type."""
        if isinstance(node, IntLit):
            return node.value
        if isinstance(node, FloatLit):
            return node.value
        if isinstance(node, UnaryOp):
            return self._eval_unary(node, depth)
        if isinstance(node, BinOp):
            return self._eval_binop(node, depth)
        raise ParseError(f"unknown AST node type: {type(node).__name__}")

    def _eval_unary(self, node: UnaryOp, depth: int) -> int | float:
        """Evaluate a unary prefix operation."""
        operand_value = self.evaluate(node.operand, depth + 1)
        if node.op == "+":
            return +operand_value
        if node.op == "-":
            return -operand_value
        raise ParseError(f"unknown unary operator: {node.op!r}")

    def _eval_binop(self, node: BinOp, depth: int) -> int | float:
        """Evaluate a binary operation.

        Division by zero propagates ``ZeroDivisionError`` rather than
        being wrapped into ``ParseError`` - the calculator surfaces the
        same exception Python's own arithmetic would.
        """
        left = self.evaluate(node.left, depth + 1)
        right = self.evaluate(node.right, depth + 1)
        if node.op == "+":
            return left + right
        if node.op == "-":
            return left - right
        if node.op == "*":
            return left * right
        if node.op == "/":
            # Note: not coerced to float; integer division by integer
            # follows Python's true-division semantics, which produces
            # a float. The fixture's tests assert ``1 / 0`` raises
            # ``ZeroDivisionError`` (via Python's `/` operator).
            return left / right
        raise ParseError(f"unknown binary operator: {node.op!r}")


def evaluate(node: AstNode) -> int | float:
    """Evaluate an ``AstNode`` AST and return the numeric result.

    Tree-walking interpreter with ``_MAX_DEPTH`` recursion guard and
    a name-mangled ``__cache`` for repeated subtree evaluation.

    >>> evaluate(parse("1 + 2 * 3"))
    7
    """
    helper = _Evaluator(max_depth=_MAX_DEPTH)
    return helper.evaluate(node)


# ---------------------------------------------------------------------------
# REPL shim (ugly-on-purpose feature #7)
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    import sys

    line = sys.stdin.readline().strip()
    print(evaluate(parse(line)))
