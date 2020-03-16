#!/usr/bin/env python3
"""Pattern matching for ASTs"""
import ast
import math
from typing import Any, Dict

import torch
from beanmachine.ppl.utils.patterns import (
    ListAll as list_all,
    MatchResult,
    Pattern,
    PatternBase,
    PredicatePattern,
    anyPattern as _any,
    match,
    match_any,
    match_every,
    negate,
    type_and_attributes,
)
from beanmachine.ppl.utils.rules import RuleDomain


def _get_children(node: Any) -> Dict[str, Any]:
    if isinstance(node, ast.AST):
        return dict(ast.iter_fields(node))
    return {}


def _construct(typ: type, children: Dict[str, ast.AST]) -> ast.AST:
    return typ(**children)


ast_domain = RuleDomain(_get_children, _construct)


ast_and: Pattern = ast.And

add: Pattern = ast.Add

bit_and: Pattern = ast.BitAnd

bit_or: Pattern = ast.BitOr

bit_xor: Pattern = ast.BitXor

div: Pattern = ast.Div

eq: Pattern = ast.Eq

gt: Pattern = ast.Gt

gte: Pattern = ast.GtE

invert: Pattern = ast.Invert

ast_is: Pattern = ast.Is

ast_is_not: Pattern = ast.IsNot

load: Pattern = ast.Load

lshift: Pattern = ast.LShift

lt: Pattern = ast.Lt

lte: Pattern = ast.LtE

mod: Pattern = ast.Mod

mult: Pattern = ast.Mult

not_eq: Pattern = ast.NotEq

ast_or: Pattern = ast.Or

ast_pass: Pattern = ast.Pass

ast_pow: Pattern = ast.Pow

rshift: Pattern = ast.RShift

sub: Pattern = ast.Sub

uadd: Pattern = ast.UAdd

usub: Pattern = ast.USub


def arguments(
    args: Pattern = _any,
    vararg: Pattern = _any,
    kwonlyargs: Pattern = _any,
    kw_defaults: Pattern = _any,
    kwarg: Pattern = _any,
    defaults: Pattern = _any,
) -> Pattern:
    return type_and_attributes(
        ast.arguments,
        {
            "args": args,
            "vararg": vararg,
            "kwonlyargs": kwonlyargs,
            "kw_defaults": kw_defaults,
            "kwarg": kwarg,
            "defaults": defaults,
        },
    )


def assign(targets: Pattern = _any, value: Pattern = _any) -> Pattern:
    return type_and_attributes(ast.Assign, {"targets": targets, "value": value})


def attribute(
    value: Pattern = _any, attr: Pattern = _any, ctx: Pattern = _any
) -> Pattern:
    return type_and_attributes(
        ast.Attribute, {"value": value, "attr": attr, "ctx": ctx}
    )


def binop(op: Pattern = _any, left: Pattern = _any, right: Pattern = _any) -> Pattern:
    return type_and_attributes(ast.BinOp, {"op": op, "left": left, "right": right})


def boolop(op: Pattern = _any, values: Pattern = _any) -> Pattern:
    return type_and_attributes(ast.BoolOp, {"op": op, "values": values})


def call(
    func: Pattern = _any, args: Pattern = _any, keywords: Pattern = _any
) -> Pattern:
    return type_and_attributes(
        ast.Call, {"func": func, "args": args, "keywords": keywords}
    )


def call_to(id: Pattern = _any, args: Pattern = _any) -> Pattern:
    return call(func=match_any(attribute(attr=id), name(id=id)), args=args)


def id_from_call(c: ast.Call) -> str:
    f = c.func
    if isinstance(f, ast.Name):
        return f.id
    if isinstance(f, ast.Attribute):
        return f.attr
    raise ValueError("Unexpected argument to id_from_call")


def compare(left: Pattern = _any, ops: Pattern = _any, comparators: Pattern = _any):
    return type_and_attributes(
        ast.Compare, {"left": left, "ops": ops, "comparators": comparators}
    )


def expr(value: Pattern = _any) -> Pattern:
    return type_and_attributes(ast.Expr, {"value": value})


def function_def(
    name: Pattern = _any,
    args: Pattern = _any,
    body: Pattern = _any,
    decorator_list: Pattern = _any,
    returns: Pattern = _any,
) -> Pattern:
    return type_and_attributes(
        ast.FunctionDef,
        {
            "name": name,
            "args": args,
            "body": body,
            "decorator_list": decorator_list,
            "returns": returns,
        },
    )


def if_exp(
    test: Pattern = _any, body: Pattern = _any, orelse: Pattern = _any
) -> Pattern:
    return type_and_attributes(
        ast.IfExp, {"test": test, "body": body, "orelse": orelse}
    )


def ast_list(elts: Pattern = _any) -> Pattern:
    return type_and_attributes(ast.List, {"elts": elts})


def module(body: Pattern = _any) -> Pattern:
    return type_and_attributes(ast.Module, {"body": body})


def name(id: Pattern = _any, ctx: Pattern = _any) -> Pattern:
    return type_and_attributes(ast.Name, {"id": id, "ctx": ctx})


def name_constant(value: Pattern = _any) -> Pattern:
    return type_and_attributes(ast.NameConstant, {"value": value})


def num(n: Pattern = _any) -> Pattern:
    return type_and_attributes(ast.Num, {"n": n})


def ast_str(s: Pattern = _any) -> Pattern:
    return type_and_attributes(ast.Str, {"s": s})


def ast_return(value: Pattern = _any) -> Pattern:
    return type_and_attributes(ast.Return, {"value": value})


def unaryop(op: Pattern = _any, operand: Pattern = _any) -> Pattern:
    return type_and_attributes(ast.UnaryOp, {"op": op, "operand": operand})


zero: Pattern = match_any(num(0), num(0.0))

number_constant: Pattern = ast.Num

non_zero_num: Pattern = match_every(number_constant, negate(zero))

negative_num: Pattern = match_every(
    number_constant, PredicatePattern(lambda n: n.n < 0)
)

ast_true: Pattern = name_constant(True)

ast_false: Pattern = name_constant(False)

# TODO: Rename this constant_bool for consistency
bool_constant: Pattern = match_any(ast_true, ast_false)

constant_literal: Pattern = match_any(number_constant, bool_constant)

any_list: Pattern = ast.List

constant_list: PatternBase


class ConstantList(PatternBase):
    """A recursively-defined pattern which matches a list expression containing only
    numeric literals, or lists of numeric literals, and so on."""

    # Note that the empty list does match; that's by design.

    def match(self, test: Any) -> MatchResult:
        return match(
            ast_list(elts=list_all(match_any(constant_literal, constant_list))), test
        )

    def _to_str(self, test: str) -> str:
        return f"{test} is a constant list"


constant_list = ConstantList()

tensor_name_str: Pattern = "tensor"

# TODO: Matches "tensor" and "foo.tensor"
# TODO: Do we need to specifically match just torch? What if there is an alias?

# Recognizes tensor(1)
constant_tensor_1: Pattern = call_to(id=tensor_name_str, args=[number_constant])

# Recognizes tensor(1), tensor([]), tensor([1, 2]), tensor([[1, 2], [3, 4]]) and so on
constant_tensor_any: Pattern = call_to(
    id=tensor_name_str, args=[match_any(number_constant, constant_list)]
)

# int, float, bool or tensor
constant_numeric: Pattern = match_any(
    number_constant, bool_constant, constant_tensor_any
)


def ast_to_constant_value(x: ast.AST) -> Any:
    if match(number_constant, x).is_success():
        assert isinstance(x, ast.Num)
        return x.n
    if match(bool_constant, x).is_success():
        assert isinstance(x, ast.NameConstant)
        return x.value
    if match(constant_tensor_any, x).is_success():
        assert isinstance(x, ast.Call)
        return torch.tensor(ast_to_constant_value(x.args[0]))
    if match(any_list, x).is_success():
        assert isinstance(x, ast.List)
        return [ast_to_constant_value(e) for e in x.elts]
    raise TypeError()


_make_nan = ast.Call(
    func=ast.Name(id="float", ctx=ast.Load()), args=[ast.Str(s="nan")], keywords=[]
)


def constant_value_to_ast(x: Any) -> ast.AST:
    # Note that the check for bool must go first, because for unknown reasons
    # isinstance(True, int) is True.
    if isinstance(x, bool):
        return ast.NameConstant(value=x)
    if isinstance(x, int):
        return ast.Num(n=x)
    if isinstance(x, float):
        return _make_nan if math.isnan(x) else ast.Num(n=x)
    if isinstance(x, torch.Tensor):
        return ast.Call(
            func=ast.Attribute(
                value=ast.Name(id="torch", ctx=ast.Load()),
                attr="tensor",
                ctx=ast.Load(),
            ),
            args=[constant_value_to_ast(x.tolist())],
            keywords=[],
        )
    if isinstance(x, list):
        return ast.List(elts=[constant_value_to_ast(e) for e in x])
    raise TypeError(f"Unexpected constant of type {str(type(x))}")