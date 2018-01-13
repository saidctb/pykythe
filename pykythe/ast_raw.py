"""Initial processing of lib2to3's AST into an easier form.

The AST that lib2to3 produces is messy to process, so we convert it
into an easier format. While doing this, we also mark all bindings
(Python requires two passes to resolve local variables, so this does
the first pass).
"""

# pylint: disable=too-many-lines
# pylint: disable=too-many-public-methods

import codecs
import collections
import io
import logging
from lib2to3 import pygram
from lib2to3 import pytree
from lib2to3.pygram import python_symbols as syms
from lib2to3.pgen2 import driver, token, tokenize
from typing import cast, Dict, FrozenSet, List, Text

from . import ast_cooked, pod


def cvt_tree(parse_tree) -> ast_cooked.AstNode:
    """Convert a lib2to3.pytree to ast_cooked.AstNode."""
    return cvt(parse_tree, new_ctx())


def new_ctx() -> 'Ctx':
    return Ctx(
        lhs_binds=False,
        bindings=collections.OrderedDict(),
        global_vars=collections.OrderedDict(),
        nonlocal_vars=collections.OrderedDict())


# pylint: disable=too-few-public-methods
# pylint: disable=no-else-return


class Ctx(pod.PlainOldData):
    """Context for traversing the lib2to3 AST.

    Note that bindings, global_vars, nonlocal_vars are dicts, so they
    can be updated and therefore Ctx behaves somewhat like a mutable
    object (lhs_binds should not be updated; instead a new Ctx object
    should be created using _replace). For those who like functional
    programming, this is cheating; but Python doesn't make it easy to
    have "accumulators" in the Prolog DCG or Haskell sense.

    Attributes:
        lhs_binds: Used to mark ast_cooked.NameNode items as being in
            a binding context or not. It is the responsibility of the
            parent of a node to set this appropriately -- e.g., for an
            assignment statement, the parent would set lhs_binds=True
            for the node(s) to the left of the "=" and would leave it
            as lhs_binds=False for node(s) on the right. For something
            like a dotted name on the left, the lhs_binds would be
            changed from True to False for all except the last dotted
            name. The normal value for this is False; it only becomes
            True on the left-hand side of assignments, for parameters
            in a function definition, and a few other similar
            situations (e.g., a with_item or an except_clause).
        bindings: A set of names that are bindings within this
            "scope". This attribute is set to empty when entering a
            new scope. To ensure consistent results, an OrderedDict
            is used, with the value ignored.
        global_vars: A set of names that appear in "global" statements
            within the current scope.
        nonlocal_vars: A set of names that appear in "nonlocal"
            statements within the current scope.
    """

    __slots__ = ('lhs_binds', 'bindings', 'global_vars', 'nonlocal_vars')

    def __init__(self, lhs_binds: bool, bindings: Dict[Text, None],
                 global_vars: Dict[Text, None],
                 nonlocal_vars: Dict[Text, None]) -> None:
        # bindings should be collections.OrderedDicts if you want
        # deterministic results.
        # pylint: disable=super-init-not-called
        self.lhs_binds = lhs_binds
        self.bindings = bindings
        self.global_vars = global_vars
        self.nonlocal_vars = nonlocal_vars


def cvt_unary_op(node: pytree.Base, ctx: Ctx) -> ast_cooked.AstNode:
    """Handles the following rules (as modified by _convert):
       factor: ('+'|'-'|'~') factor | power
       not_test: 'not' not_test | comparison
    """
    if len(node.children) == 1:
        # Can appear on LHS if it's a single item
        return cvt(node.children[0], ctx)
    assert not ctx.lhs_binds, [node]
    return ast_cooked.OpNode(
        op_astn=node.children[0], args=[cvt(node.children[1], ctx)])


def cvt_binary_op(node: pytree.Base, ctx: Ctx) -> ast_cooked.AstNode:
    """Handles the following rules (as modified by _convert):
       and_expr: shift_expr ('&' shift_expr)*
       and_test: not_test ('and' not_test)*
       arith_expr: term (('+'|'-') term)*
       expr: xor_expr ('|' xor_expr)*
       or_test: and_test ('or' and_test)*
       shift_expr: arith_expr (('<<'|'>>') arith_expr)*
       term: factor (('*'|'@'|'/'|'%'|'//') factor)*
       xor_expr: and_expr ('^' and_expr)*
    """
    result = cvt(node.children[0], ctx)
    if len(node.children) == 1:
        # Can appear on LHS if it's a single item
        return result
    assert not ctx.lhs_binds, [node]
    for i in range(1, len(node.children), 2):
        result = ast_cooked.OpNode(
            op_astn=node.children[i],
            args=[result, cvt(node.children[i + 1], ctx)])
    return result


def cvt_comparison(node: pytree.Base, ctx: Ctx) -> ast_cooked.AstNode:
    """comparison: expr (comp_op expr)*"""
    result = cvt(node.children[0], ctx)
    if len(node.children) == 1:
        # Can appear on LHS if it's a single item
        return result
    assert not ctx.lhs_binds, [node]
    for i in range(1, len(node.children), 2):
        result = ast_cooked.ComparisonOpNode(
            op=cvt(node.children[i], ctx),
            args=[result, cvt(node.children[i + 1], ctx)])
    return result


def cvt_file_input(node: pytree.Base, ctx: Ctx) -> ast_cooked.AstNode:
    """file_input: (NEWLINE | stmt)* ENDMARKER"""
    assert not ctx.lhs_binds, [node]
    assert all(
        ch.type in (SYMS_STMT, token.NEWLINE, token.ENDMARKER)
        for ch in node.children)
    return ast_cooked.make_generic_node(
        'file_input',
        [cvt(ch, ctx) for ch in node.children if ch.type == SYMS_STMT])


def cvt_annassign(node: pytree.Base, ctx: Ctx) -> ast_cooked.AstNode:
    """annassign: ':' test ['=' test]"""
    assert not ctx.lhs_binds, [node]
    if len(node.children) == 1:
        return cvt(node.children[1], ctx)
    return ast_cooked.AnnAssignNode(
        expr=cvt(node.children[1], ctx), expr_type=cvt(node.children[3], ctx))


def cvt_arglist(node: pytree.Base, ctx: Ctx) -> ast_cooked.AstNode:
    """arglist: argument (',' argument)* [',']"""
    assert not ctx.lhs_binds, [node]
    return ast_cooked.ArgListNode(
        arguments=cvt_children_skip_commas(node, ctx))


def cvt_argument(node: pytree.Base, ctx: Ctx) -> ast_cooked.AstNode:
    """
    argument: ( test [comp_for] |
                test '=' test |
                '**' expr |
                star_expr )
    """
    assert not ctx.lhs_binds, [node]
    name = ast_cooked.OMITTED_NODE  # type: ast_cooked.AstNode
    comp_for = ast_cooked.OMITTED_NODE  # type: ast_cooked.AstNode
    if node.children[0].type == SYMS_TEST:
        if len(node.children) == 1:
            arg = cvt(node.children[0], ctx)
        else:
            if node.children[1].type == token.EQUAL:
                name = cvt(node.children[0], ctx)
                arg = cvt(node.children[2], ctx)
            else:
                assert node.children[1].type == SYMS_COMP_FOR
                comp_for = cvt(node.children[1], ctx)
                # arg is evaluated in the context of comp_for:
                arg = cvt(node.children[0], ctx)
    elif node.children[0].type == token.DOUBLESTAR:
        arg = ast_cooked.StarStarExprNode(expr=cvt(node.children[1], ctx))
    else:
        assert node.children[0].type == SYMS_STAR_EXPR
        arg = cvt(node.children[0], ctx)
    return ast_cooked.ArgNode(name=name, arg=arg, comp_for=comp_for)


def cvt_assert_stmt(node: pytree.Base, ctx: Ctx) -> ast_cooked.AstNode:
    """assert_stmt: 'assert' test [',' test]"""
    assert not ctx.lhs_binds, [node]
    test = cvt(node.children[1], ctx)
    if len(node.children) == 2:
        display = ast_cooked.OMITTED_NODE  # type: ast_cooked.AstNode
    else:
        display = cvt(node.children[3], ctx)
    return ast_cooked.make_generic_node('assert', [test, display])


def cvt_async_funcdef(node: pytree.Base, ctx: Ctx) -> ast_cooked.AstNode:
    """async_funcdef: ASYNC funcdef"""
    assert not ctx.lhs_binds, [node]
    # Don't care about ASYNC
    return cvt(node.children[1], ctx)


def cvt_async_stmt(node: pytree.Base, ctx: Ctx) -> ast_cooked.AstNode:
    """async_stmt: ASYNC (funcdef | with_stmt | for_stmt)"""
    assert not ctx.lhs_binds, [node]
    # Don't care about ASYNC
    return cvt(node.children[1], ctx)


def cvt_atom(node: pytree.Base, ctx: Ctx) -> ast_cooked.AstNode:
    """
    atom: ('(' [yield_expr|testlist_gexp] ')' |
           '[' [listmaker] ']' |
           '{' [dictsetmaker] '}' |
           '`' testlist1 '`' |
           NAME | NUMBER | STRING+ | '.' '.' '.')
    """
    # Can appear on LHS
    ch0 = node.children[0]
    if ch0.type in _EMPTY_PAIR:
        if len(node.children) == 2:
            result = ast_cooked.make_generic_node(_EMPTY_PAIR[ch0.type], [])
        else:
            result = cvt(node.children[1], ctx)
    elif ch0.type in (token.NAME, token.NUMBER, token.STRING):
        result = cvt(ch0, ctx)
    elif (len(node.children) == 3 and
          all(ch.type == token.DOT for ch in node.children)):
        assert not ctx.lhs_binds, [node]
        result = ast_cooked.make_generic_node('...', [])
    else:
        raise ValueError('Invalid atom: {!r}'.format(node))
    return result


_EMPTY_PAIR = {
    token.LPAR: '()',
    token.LSQB: '[]',
    token.LBRACE: '{}',
    token.BACKQUOTE: '``'
}


def cvt_augassign(node: pytree.Base, ctx: Ctx) -> ast_cooked.AstNode:
    """
    augassign: ('+=' | '-=' | '*=' | '@=' | '/=' | '%=' | '&=' | '|=' | '^=' |
                '<<=' | '>>=' | '**=' | '//=')
    """
    assert not ctx.lhs_binds, [node]
    assert len(node.children) == 1, [node]
    return ast_cooked.AugAssignNode(op_astn=node.children[0])


def cvt_break_stmt(node: pytree.Base, ctx: Ctx) -> ast_cooked.AstNode:
    """break_stmt: 'break'"""
    assert not ctx.lhs_binds, [node]
    return ast_cooked.make_generic_node('break_stmt', [])


def cvt_classdef(node: pytree.Base, ctx: Ctx) -> ast_cooked.AstNode:
    """classdef: 'class' NAME ['(' [arglist] ')'] ':' suite"""
    assert not ctx.lhs_binds, [node]
    # The bindings for ClassDefStmt are built up in the calls to
    # parameters and suite.
    # TODO: what happens with `def foo(): global Bar; class Bar: ...` ?
    name = cvt_lhs_binds(True, node.children[1], ctx)
    ctx_class = new_ctx()  # start new bindings for the parameters, suite
    if node.children[2].type == token.LPAR:
        if node.children[3].type == token.RPAR:
            bases = ast_cooked.OMITTED_NODE  # type: ast_cooked.AstNode
        else:
            bases = cvt(node.children[3], ctx_class)
    else:
        bases = ast_cooked.OMITTED_NODE
    suite = cvt(node.children[-1], ctx_class)
    return ast_cooked.ClassDefStmt(
        name=name, bases=bases, suite=suite, bindings=ctx_class.bindings)


def cvt_comp_for(node: pytree.Base, ctx: Ctx) -> ast_cooked.AstNode:
    """comp_for: [ASYNC] 'for' exprlist 'in' testlist_safe [comp_iter]"""
    assert not ctx.lhs_binds, [node]
    ch0 = cast(pytree.Leaf, node.children[0])
    if ch0.value == 'async':
        children = node.children[1:]  # Don't care about ASYNC
    else:
        children = node.children
    for_exprlist = cvt_lhs_binds(True, children[1], ctx)
    in_testlist = cvt(children[3], ctx)
    if len(children) == 5:
        comp_iter = cvt(children[4], ctx)
    else:
        comp_iter = ast_cooked.OMITTED_NODE
    return ast_cooked.CompForNode(
        for_exprlist=for_exprlist,
        in_testlist=in_testlist,
        comp_iter=comp_iter)


def cvt_comp_if(node: pytree.Base, ctx: Ctx) -> ast_cooked.AstNode:
    """comp_if: 'if' old_test [comp_iter]"""
    assert not ctx.lhs_binds, [node]
    return ast_cooked.make_generic_node(
        'comp_if', [cvt(ch, ctx) for ch in node.children[1:]])


def cvt_comp_iter(node: pytree.Base, ctx: Ctx) -> ast_cooked.AstNode:
    """comp_iter: comp_for | comp_if"""
    assert not ctx.lhs_binds, [node]
    return cvt(node.children[0], ctx)


def cvt_comp_op(node: pytree.Base, ctx: Ctx) -> ast_cooked.AstNode:
    """comp_op: '<'|'>'|'=='|'>='|'<='|'<>'|'!='|'in'|'not' 'in'|'is'|'is' 'not'"""
    assert not ctx.lhs_binds, [node]
    return ast_cooked.CompOpNode(op_astns=node.children)


def cvt_compound_stmt(node: pytree.Base, ctx: Ctx) -> ast_cooked.AstNode:
    """
    compound_stmt: if_stmt |
                   while_stmt |
                   for_stmt |
                   try_stmt |
                   with_stmt |
                   funcdef |
                   classdef |
                   decorated |
                   async_stmt
    """
    assert not ctx.lhs_binds, [node]
    return cvt(node.children[0], ctx)


def cvt_continue_stmt(node: pytree.Base, ctx: Ctx) -> ast_cooked.AstNode:
    """continue_stmt: 'continue'"""
    assert not ctx.lhs_binds, [node]
    return ast_cooked.make_generic_node('continue_stmt', [])


def cvt_decorated(node: pytree.Base, ctx: Ctx) -> ast_cooked.AstNode:
    """decorated: decorators (classdef | funcdef | async_funcdef)"""
    assert not ctx.lhs_binds, [node]
    return ast_cooked.make_generic_node('decorated', cvt_children(node, ctx))


def cvt_decorator(node: pytree.Base, ctx: Ctx) -> ast_cooked.AstNode:
    """decorator: '@' dotted_name [ '(' [arglist] ')' ] NEWLINE"""
    assert not ctx.lhs_binds, [node]
    name = cvt(node.children[1], ctx)
    if node.children[2].type == token.LPAR:
        if node.children[3].type == token.RPAR:
            arglist = ast_cooked.OMITTED_NODE  # type: ast_cooked.AstNode
        else:
            arglist = cvt(node.children[3], ctx)
    else:
        arglist = ast_cooked.OMITTED_NODE
    return ast_cooked.DecoratorNode(name=name, arglist=arglist)


def cvt_decorators(node: pytree.Base, ctx: Ctx) -> ast_cooked.AstNode:
    """decorators: decorator+"""
    assert not ctx.lhs_binds, [node]
    return ast_cooked.make_generic_node('decorators', cvt_children(node, ctx))


def cvt_del_stmt(node: pytree.Base, ctx: Ctx) -> ast_cooked.AstNode:
    """del_stmt: 'del' exprlist"""
    assert not ctx.lhs_binds, [node]
    return ast_cooked.DelStmt(exprs=cvt(node.children[1], ctx))


def cvt_dictsetmaker(node: pytree.Base, ctx: Ctx) -> ast_cooked.AstNode:
    """
    dictsetmaker: ( ((test ':' test | '**' expr)
                     (comp_for | (',' (test ':' test | '**' expr))* [','])) |
                    ((test | star_expr)
                     (comp_for | (',' (test | star_expr))* [','])) )
    """
    assert not ctx.lhs_binds, [node]
    if (len(node.children) == 4 and node.children[2].type == token.COLON and
            node.children[3].type == SYMS_COMP_FOR):
        return ast_cooked.DictSetMakerCompForNode(
            key_value_expr=ast_cooked.make_generic_node(
                ':', [cvt(node.children[0], ctx),
                      cvt(node.children[2], ctx)]),
            comp_for=cvt(node.children[3], ctx))
    if (len(node.children) == 3 and
            node.children[0].type == token.DOUBLESTAR and
            node.children[2].type == SYMS_COMP_FOR):
        return ast_cooked.DictSetMakerCompForNode(
            key_value_expr=ast_cooked.make_generic_node(
                '**', [cvt(node.children[1], ctx)]),
            comp_for=cvt(node.children[2], ctx))
    if len(node.children) == 2 and node.children[1] == SYMS_COMP_FOR:
        return ast_cooked.DictSetMakerCompForNode(
            key_value_expr=cvt(node.children[0], ctx),
            comp_for=cvt(node.children[1], ctx))
    return ast_cooked.make_generic_node('dicsetmaker', [
        cvt(ch, ctx)
        for ch in node.children
        if ch.type not in (token.COLON, token.DOUBLESTAR, token.COMMA)
    ])


def cvt_dotted_as_name(node: pytree.Base, ctx: Ctx) -> ast_cooked.AstNode:
    """dotted_as_name: dotted_name ['as' NAME]"""
    assert not ctx.lhs_binds, [node]
    dotted_name = cast(ast_cooked.DottedNameNode, cvt(node.children[0], ctx))
    if len(node.children) == 1:
        return ast_cooked.DottedAsNameNode(
            dotted_name=dotted_name,
            as_name=dotted_name.names[-1]._replace(binds=True))
    return ast_cooked.DottedAsNameNode(
        dotted_name=dotted_name,
        as_name=cvt_lhs_binds(True, node.children[2], ctx))


def cvt_dotted_as_names(node: pytree.Base, ctx: Ctx) -> ast_cooked.AstNode:
    """dotted_as_names: dotted_as_name (',' dotted_as_name)*"""
    assert not ctx.lhs_binds, [node]
    return ast_cooked.DottedAsNamesNode(
        names=cvt_children_skip_commas(node, ctx))


def cvt_dotted_name(node: pytree.Base, ctx: Ctx) -> ast_cooked.AstNode:
    """dotted_name: NAME ('.' NAME)*"""
    # Can appear on LHS
    # If this is on LHS, the last name is in a binding context
    return ast_cooked.DottedNameNode(names=[
        cvt_lhs_binds(False, ch, ctx)
        for ch in node.children[:-1]
        if ch.type != token.DOT
    ] + [cvt(node.children[-1], ctx)])


def cvt_encoding_decl(node: pytree.Base, ctx: Ctx) -> ast_cooked.AstNode:
    """encoding_decl: NAME"""
    assert not ctx.lhs_binds, [node]
    raise ValueError('encoding_decl is not used in grammar: {!r}'.format(node))


def cvt_eval_input(node: pytree.Base, ctx: Ctx) -> ast_cooked.AstNode:
    """eval_input: testlist NEWLINE* ENDMARKER"""
    assert not ctx.lhs_binds, [node]
    return cvt(node.children[0], ctx)


def cvt_except_clause(node: pytree.Base, ctx: Ctx) -> ast_cooked.AstNode:
    """except_clause: 'except' [test [(',' | 'as') test]]"""
    assert not ctx.lhs_binds, [node]
    if len(node.children) == 1:
        exc1 = ast_cooked.OMITTED_NODE  # type: ast_cooked.AstNode
        exc2 = ast_cooked.OMITTED_NODE  # type: ast_cooked.AstNode
    elif len(node.children) == 2:
        exc1 = cvt(node.children[1], ctx)
        exc2 = ast_cooked.OMITTED_NODE
    else:
        assert len(node.children) == 4, [node]
        exc1 = cvt(node.children[1], ctx)
        exc2 = cvt_lhs_binds(True, node.children[3], ctx)
    return ast_cooked.make_generic_node('except_clause', [exc1, exc2])


def cvt_exec_stmt(node: pytree.Base, ctx: Ctx) -> ast_cooked.AstNode:
    """exec_stmt: 'exec' expr ['in' test [',' test]]"""
    assert not ctx.lhs_binds, [node]
    if len(node.children) == 1:
        expr1 = cvt(node.children[1], ctx)
        expr2 = ast_cooked.OMITTED_NODE  # type: ast_cooked.AstNode
        expr3 = ast_cooked.OMITTED_NODE  # type: ast_cooked.AstNode
    elif len(node.children) == 4:
        expr1 = cvt(node.children[1], ctx)
        expr2 = cvt(node.children[3], ctx)
        expr3 = ast_cooked.OMITTED_NODE
    else:
        assert len(node.children) == 6
        expr1 = cvt(node.children[1], ctx)
        expr2 = cvt(node.children[3], ctx)
        expr3 = cvt(node.children[5], ctx)
    return ast_cooked.make_generic_node('exec', [expr1, expr2, expr3])


def cvt_expr_stmt(node: pytree.Base, ctx: Ctx) -> ast_cooked.AstNode:
    """
    expr_stmt: testlist_star_expr
               ( annassign |
                 augassign (yield_expr|testlist) |
                 ('=' (yield_expr|testlist_star_expr))* )
    """
    assert not ctx.lhs_binds, [node]
    if len(node.children) == 1:
        return cvt(node.children[0], ctx)
    if len(node.children) == 2:
        assert node.children[1].type == SYMS_ANNASSIGN
        # Treat as binding even if there's no `=`, because it's
        # sort of a binding (defines the type).
        return ast_cooked.ExprStmt(
            lhs=cvt_lhs_binds(True, node.children[0], ctx),
            augassign=ast_cooked.OMITTED_NODE,
            exprs=[cvt(node.children[1], ctx)])
    if node.children[1].type == token.EQUAL:
        return ast_cooked.ExprStmt(
            lhs=cvt_lhs_binds(True, node.children[0], ctx),
            augassign=ast_cooked.OMITTED_NODE,
            exprs=[
                cvt(ch, ctx) for ch in node.children if ch.type != token.EQUAL
            ])
    assert node.children[1].type == SYMS_AUGASSIGN
    return ast_cooked.ExprStmt(
        lhs=cvt(node.children[0], ctx),  # modifies is not binding
        augassign=cvt(node.children[1], ctx),
        exprs=[cvt(node.children[2], ctx)])


def cvt_exprlist(node: pytree.Base, ctx: Ctx) -> ast_cooked.AstNode:
    """exprlist: (expr|star_expr) (',' (expr|star_expr))* [',']"""
    # Can appear on LHS
    return ast_cooked.make_generic_node('exprlist',
                                        cvt_children_skip_commas(node, ctx))


def cvt_flow_stmt(node: pytree.Base, ctx: Ctx) -> ast_cooked.AstNode:
    """flow_stmt: break_stmt | continue_stmt | return_stmt | raise_stmt | yield_stmt"""
    assert not ctx.lhs_binds, [node]
    return cvt(node.children[0], ctx)


def cvt_for_stmt(node: pytree.Base, ctx: Ctx) -> ast_cooked.AstNode:
    """for_stmt: 'for' exprlist 'in' testlist ':' suite ['else' ':' suite]"""
    assert not ctx.lhs_binds, [node]
    exprlist = cvt_lhs_binds(True, node.children[1], ctx)
    testlist = cvt(node.children[3], ctx)
    suite = cvt(node.children[5], ctx)
    if len(node.children) == 9:
        else_suite = cvt(node.children[8], ctx)
    else:
        assert len(node.children) == 6
        else_suite = ast_cooked.OMITTED_NODE
    return ast_cooked.ForStmt(
        exprlist=exprlist,
        testlist=testlist,
        suite=suite,
        else_suite=else_suite)


def cvt_funcdef(node: pytree.Base, ctx: Ctx) -> ast_cooked.AstNode:
    """funcdef: 'def' NAME parameters ['->' test] ':' suite"""
    assert not ctx.lhs_binds, [node]
    # The bindings for FuncDefStmt are built up in the calls to
    # parameters and suite.
    name = cast(ast_cooked.NameNode, cvt_lhs_binds(True, node.children[1],
                                                   ctx))
    ctx.bindings[name.astn.value] = None
    # start a new set of bindings for the parameters, suite
    ctx_func = new_ctx()
    parameters = ast_cooked.make_generic_node(
        'parameters', [cvt(node.children[2], ctx_func)])
    if node.children[3].type == token.RARROW:
        return_type = cvt(node.children[4], ctx)
    else:
        return_type = ast_cooked.OMITTED_NODE
    suite = cvt(node.children[-1], ctx_func)
    return ast_cooked.FuncDefStmt(
        name=name,
        parameters=parameters,
        return_type=return_type,
        suite=suite,
        bindings=ctx_func.bindings)


def cvt_global_stmt(node: pytree.Base, ctx: Ctx) -> ast_cooked.AstNode:
    """global_stmt: ('global' | 'nonlocal') NAME (',' NAME)*"""
    assert not ctx.lhs_binds, [node]
    names = [
        cvt(ch, ctx) for ch in node.children[1:] if ch.type != token.COMMA
    ]
    ch0 = cast(pytree.Leaf, node.children[0])
    if ch0.value == 'global':
        return ast_cooked.GlobalStmt(names=names)
    else:
        assert ch0.value == 'nonlocal'
        return ast_cooked.NonLocalStmt(names=names)


def cvt_if_stmt(node: pytree.Base, ctx: Ctx) -> ast_cooked.AstNode:
    """if_stmt: 'if' test ':' suite ('elif' test ':' suite)* ['else' ':' suite]"""
    assert not ctx.lhs_binds, [node]
    ifthens = []
    else_suite = ast_cooked.OMITTED_NODE  # type: ast_cooked.AstNode
    for i in range(0, len(node.children), 4):
        ch0 = cast(pytree.Leaf, node.children[i])
        if ch0.value in ('if', 'elif'):
            ifthens.append(cvt(node.children[i + 1], ctx))
            ifthens.append(cvt(node.children[i + 3], ctx))
        elif ch0.value == 'else':
            else_suite = cvt(node.children[i + 2], ctx)
    return ast_cooked.make_generic_node('if_stmt', ifthens + [else_suite])


def cvt_import_as_name(node: pytree.Base, ctx: Ctx) -> ast_cooked.AstNode:
    """import_as_name: NAME ['as' NAME]"""
    assert not ctx.lhs_binds, [node]
    ch0 = node.children[0]
    if len(node.children) == 1:
        return ast_cooked.AsNameNode(
            name=cvt_lhs_binds(False, ch0, ctx),
            as_name=cvt_lhs_binds(True, ch0, ctx))
    return ast_cooked.AsNameNode(
        name=cvt_lhs_binds(False, ch0, ctx),
        as_name=cvt_lhs_binds(True, node.children[2], ctx))


def cvt_import_as_names(node: pytree.Base, ctx: Ctx) -> ast_cooked.AstNode:
    """import_as_names: import_as_name (',' import_as_name)* [',']"""
    assert not ctx.lhs_binds, [node]
    return ast_cooked.ImportAsNamesNode(
        names=cvt_children_skip_commas(node, ctx))


def cvt_import_from(node: pytree.Base, ctx: Ctx) -> ast_cooked.AstNode:
    """
    import_from: ('from' ('.'* dotted_name | '.'+)
                  'import' ('*' | '(' import_as_names ')' | import_as_names))
    """
    assert not ctx.lhs_binds, [node]
    from_name = []  # type: List[ast_cooked.AstNode]
    for i, child in enumerate(node.children):
        if child.type == token.NAME and child.value == 'from':  # type: ignore
            continue
        if child.type == token.NAME and child.value == 'import':  # type: ignore
            break
        if child.type == token.DOT:
            from_name.append(ast_cooked.DotNode())
        else:
            from_name.append(cvt(child, ctx))
    # pylint: disable=undefined-loop-variable
    assert (node.children[i].type == token.NAME and
            node.children[i].value == 'import')  # type: ignore
    i += 1
    # pylint: enable=undefined-loop-variable)
    if node.children[i].type == token.STAR:
        import_part = ast_cooked.StarNode()  # type: ast_cooked.AstNode
    elif node.children[i].type == token.LPAR:
        import_part = cvt(node.children[i + 1], ctx)
    else:
        import_part = cvt(node.children[i], ctx)
    return ast_cooked.ImportFromStmt(
        from_name=from_name, import_part=import_part)


def cvt_import_name(node: pytree.Base, ctx: Ctx) -> ast_cooked.AstNode:
    """import_name: 'import' dotted_as_names"""
    assert not ctx.lhs_binds, [node]
    return ast_cooked.ImportNameNode(
        dotted_as_names=cvt(node.children[1], ctx))


def cvt_import_stmt(node: pytree.Base, ctx: Ctx) -> ast_cooked.AstNode:
    """import_stmt: import_name | import_from"""
    assert not ctx.lhs_binds, [node]
    return cvt(node.children[0], ctx)


def cvt_lambdef(node: pytree.Base, ctx: Ctx) -> ast_cooked.AstNode:
    """lambdef: 'lambda' [varargslist] ':' test"""
    assert not ctx.lhs_binds, [node]
    name = cast(ast_cooked.NameNode, cvt_lhs_binds(True, node.children[0],
                                                   ctx))
    ctx_func = new_ctx()
    if len(node.children) == 4:
        parameters = cvt(node.children[1], ctx_func)
        suite = cvt(node.children[3], ctx_func)
    else:
        parameters = ast_cooked.make_generic_node('parameters', [])
        suite = cvt(node.children[2], ctx_func)
    return ast_cooked.FuncDefStmt(
        name=name,
        parameters=parameters,
        return_type=ast_cooked.OMITTED_NODE,
        suite=suite,
        bindings=ctx_func.bindings)


def cvt_listmaker(node: pytree.Base, ctx: Ctx) -> ast_cooked.AstNode:
    """listmaker: (test|star_expr) ( comp_for | (',' (test|star_expr))* [','] )"""
    assert not ctx.lhs_binds, [node]
    return ast_cooked.make_generic_node('listmaker',
                                        cvt_children_skip_commas(node, ctx))


def cvt_parameters(node: pytree.Base, ctx: Ctx) -> ast_cooked.AstNode:
    """parameters: '(' [typedargslist] ')'"""
    assert not ctx.lhs_binds, [node]
    if len(node.children) > 2:
        return ast_cooked.make_generic_node('parameters',
                                            [cvt(node.children[1], ctx)])
    return ast_cooked.make_generic_node('()', [])


def cvt_pass_stmt(node: pytree.Base, ctx: Ctx) -> ast_cooked.AstNode:
    """pass_stmt: 'pass'"""
    assert not ctx.lhs_binds, [node]
    return ast_cooked.make_generic_node('pass', [])


def cvt_power(node: pytree.Base, ctx: Ctx) -> ast_cooked.AstNode:
    """power: [AWAIT] atom trailer* ['**' factor]"""
    # Can appear on LHS
    if (node.children[0].type == token.NAME and
            node.children[0].value == 'await'):  # type: ignore
        # Don't care about AWAIT
        children = node.children[1:]
    else:
        children = node.children
    if len(children) == 1:
        return cvt(children[0], ctx)
    if children[-1].type == SYMS_FACTOR:
        assert children[-2].type == token.DOUBLESTAR
        doublestar_factor = cvt(children[-1], ctx)
        children = children[:-2]
    else:
        assert len(children) == 1 or children[-1].type == SYMS_TRAILER
        doublestar_factor = None
    # For the trailer, all but the last item are in a non-binding
    # context; the last item is in the current binds context.
    atom = cvt(children[0], ctx)
    trailer_ctx = ctx._replace(lhs_binds=False)
    trailers = [cvt(ch, trailer_ctx) for ch in children[1:-1]]
    if len(children) > 1:
        trailers.append(cvt(children[-1], ctx))
    trailer = ast_cooked.AtomTrailerNode(atom=atom, trailers=trailers)
    if doublestar_factor:
        return ast_cooked.OpNode(
            op_astn=node.children[-2], args=[trailer, doublestar_factor])
    return trailer


def cvt_print_stmt(node: pytree.Base, ctx: Ctx) -> ast_cooked.AstNode:
    """
    print_stmt: 'print' ( [ test (',' test)* [','] ] |
                          '>>' test [ (',' test)+ [','] ] )
    """
    assert not ctx.lhs_binds, [node]
    return ast_cooked.make_generic_node('print', [
        cvt(ch, ctx)
        for ch in node.children
        if ch.type not in (token.COMMA, token.RIGHTSHIFT)
    ])


def cvt_raise_stmt(node: pytree.Base, ctx: Ctx) -> ast_cooked.AstNode:
    """raise_stmt: 'raise' [test ['from' test | ',' test [',' test]]]"""
    assert not ctx.lhs_binds, [node]
    if len(node.children) == 1:
        return ast_cooked.make_generic_node('raise', [])
    exc = cvt(node.children[1], ctx)
    if len(node.children) > 2:
        if node.children[2].value == 'from':  # type: ignore
            raise_from = cvt(node.children[3], ctx)
            exc2 = ast_cooked.OMITTED_NODE  # type: ast_cooked.AstNode
            exc3 = ast_cooked.OMITTED_NODE  # type: ast_cooked.AstNode
        else:
            raise_from = ast_cooked.OMITTED_NODE
            exc2 = cvt(node.children[3], ctx)
            if len(node.children) > 3:
                exc2 = cvt(node.children[5], ctx)
            else:
                exc3 = ast_cooked.OMITTED_NODE
    else:
        raise_from = ast_cooked.OMITTED_NODE
        exc2 = ast_cooked.OMITTED_NODE
        exc3 = ast_cooked.OMITTED_NODE
    return ast_cooked.make_generic_node('raise', [exc, exc2, exc3, raise_from])


def cvt_return_stmt(node: pytree.Base, ctx: Ctx) -> ast_cooked.AstNode:
    """return_stmt: 'return' [testlist]"""
    assert not ctx.lhs_binds, [node]
    if len(node.children) == 2:
        return cvt(node.children[1], ctx)
    return ast_cooked.OMITTED_NODE


def cvt_simple_stmt(node: pytree.Base, ctx: Ctx) -> ast_cooked.AstNode:
    """simple_stmt: small_stmt (';' small_stmt)* [';'] NEWLINE"""
    # filter for ch.type == SYMS_SMALL_STMT
    assert not ctx.lhs_binds, [node]
    assert all(
        ch.type in (SYMS_SMALL_STMT, token.SEMI, token.NEWLINE)
        for ch in node.children)
    return ast_cooked.make_generic_node(
        'simple_stmt',
        [cvt(ch, ctx) for ch in node.children if ch.type == SYMS_SMALL_STMT])


def cvt_single_input(node: pytree.Base, ctx: Ctx) -> ast_cooked.AstNode:
    """single_input: NEWLINE | simple_stmt | compound_stmt NEWLINE"""
    assert not ctx.lhs_binds, [node]
    if node.children[0].type == token.NEWLINE:
        return ast_cooked.make_generic_node('pass', [])
    return cvt(node.children[0], ctx)


def cvt_sliceop(node: pytree.Base, ctx: Ctx) -> ast_cooked.AstNode:
    """sliceop: ':' [test]"""
    assert not ctx.lhs_binds, [node]
    return cvt(node.children[0], ctx)


def cvt_small_stmt(node: pytree.Base, ctx: Ctx) -> ast_cooked.AstNode:
    """
    small_stmt: (expr_stmt | print_stmt  | del_stmt | pass_stmt | flow_stmt |
                 import_stmt | global_stmt | exec_stmt | assert_stmt)
    """
    assert not ctx.lhs_binds, [node]
    assert len(node.children) == 1
    return cvt(node.children[0], ctx)


def cvt_stmt(node: pytree.Base, ctx: Ctx) -> ast_cooked.AstNode:
    """stmt: simple_stmt | compound_stmt"""
    assert not ctx.lhs_binds, [node]
    assert len(node.children) == 1
    return cvt(node.children[0], ctx)


def cvt_subscript(node: pytree.Base, ctx: Ctx) -> ast_cooked.AstNode:
    """subscript: test | [test] ':' [test] [sliceop]"""
    assert not ctx.lhs_binds, [node]
    if len(node.children) == 1:
        if node.children[0].type == token.COLON:
            expr1 = ast_cooked.OMITTED_NODE  # type: ast_cooked.AstNode
        else:
            expr1 = cvt(node.children[0], ctx)
        expr2 = ast_cooked.OMITTED_NODE  # type: ast_cooked.AstNode
        expr3 = ast_cooked.OMITTED_NODE  # type: ast_cooked.AstNode
    else:
        i = 0
        if node.children[i].type == token.COLON:
            expr1 = ast_cooked.OMITTED_NODE
            i += 1
        else:
            expr1 = cvt(node.children[0], ctx)
            i += 2  # skip ':'
        if i < len(node.children):
            if node.children[i].type == SYMS_SLICEOP:
                expr2 = ast_cooked.OMITTED_NODE
            else:
                expr2 = cvt(node.children[i], ctx)
                i += 1
            if i < len(node.children):
                expr3 = cvt(node.children[i], ctx)
            else:
                expr3 = ast_cooked.OMITTED_NODE
        else:
            expr1 = cvt(node.children[0], ctx)
            expr2 = ast_cooked.OMITTED_NODE
            expr3 = ast_cooked.OMITTED_NODE
    return ast_cooked.SubscriptNode(expr1=expr1, expr2=expr2, expr3=expr3)


def cvt_subscriptlist(node: pytree.Base, ctx: Ctx) -> ast_cooked.AstNode:
    """subscriptlist: subscript (',' subscript)* [',']"""
    # Can appear on LHS
    return ast_cooked.SubscriptListNode(
        subscripts=cvt_children_skip_commas(
            node, ctx._replace(lhs_binds=False)))


def cvt_suite(node: pytree.Base, ctx: Ctx) -> ast_cooked.AstNode:
    """suite: simple_stmt | NEWLINE INDENT stmt+ DEDENT"""
    assert not ctx.lhs_binds, [node]
    assert all(
        ch.type in (SYMS_SIMPLE_STMT, SYMS_STMT, token.NEWLINE, token.INDENT,
                    token.DEDENT) for ch in node.children)

    return ast_cooked.make_generic_node('suite', [
        cvt(ch, ctx)
        for ch in node.children
        if ch.type not in (token.NEWLINE, token.INDENT, token.DEDENT)
    ])


def cvt_star_expr(node: pytree.Base, ctx: Ctx) -> ast_cooked.AstNode:
    """star_expr: '*' expr"""
    assert not ctx.lhs_binds, [node]
    return ast_cooked.StarExprNode(expr=cvt(node.children[1], ctx))


def cvt_test(node: pytree.Base, ctx: Ctx) -> ast_cooked.AstNode:
    """
    test: or_test ['if' or_test 'else' test] | lambdef
    old_test: or_test | old_lambdef
    """
    # Can appear on LHS
    return cvt(node.children[0], ctx)


def cvt_testlist(node: pytree.Base, ctx: Ctx) -> ast_cooked.AstNode:
    """testlist: test (',' test)* [',']"""
    assert not ctx.lhs_binds, [node]
    return ast_cooked.make_generic_node('testlist',
                                        cvt_children_skip_commas(node, ctx))


def cvt_testlist1(node: pytree.Base, ctx: Ctx) -> ast_cooked.AstNode:
    """testlist1: test (',' test)*"""
    assert not ctx.lhs_binds, [node]
    return ast_cooked.make_generic_node('testlist1',
                                        cvt_children_skip_commas(node, ctx))


def cvt_testlist_gexp(node: pytree.Base, ctx: Ctx) -> ast_cooked.AstNode:
    """testlist_gexp: (test|star_expr) ( comp_for | (',' (test|star_expr))* [','] )"""
    # Can appear on LHS
    return ast_cooked.make_generic_node('testlist_gexp',
                                        cvt_children_skip_commas(node, ctx))


def cvt_testlist_safe(node: pytree.Base, ctx: Ctx) -> ast_cooked.AstNode:
    """testlist_safe: old_test [(',' old_test)+ [',']]"""
    assert not ctx.lhs_binds, [node]
    return ast_cooked.make_generic_node('testlist_safe',
                                        cvt_children_skip_commas(node, ctx))


def cvt_testlist_star_expr(node: pytree.Base, ctx: Ctx) -> ast_cooked.AstNode:
    """testlist_star_expr: (test|star_expr) (',' (test|star_expr))* [',']"""
    # Can appear on LHS, e.g.:
    #   x, *middle, y = (1, 2, 3, 4, 5)
    # or in some cases on the RHS:
    #   [x, *middle, y]
    return ast_cooked.make_generic_node('testlist_star_expr',
                                        cvt_children_skip_commas(node, ctx))


def cvt_tfpdef(node: pytree.Base, ctx: Ctx) -> ast_cooked.AstNode:
    """
    tfpdef: tname | '(' tfplist ')'
    vfpdef: vname | '(' vfplist ')'
    """
    # Can appear on LHS
    if len(node.children) == 1:
        return cvt(node.children[0], ctx)
    return cvt(node.children[1], ctx)


def cvt_tfplist(node: pytree.Base, ctx: Ctx) -> ast_cooked.AstNode:
    """
    tfplist: tfpdef (',' tfpdef)* [',']
    vfplist: vfpdef (',' vfpdef)* [',']
    """
    assert not ctx.lhs_binds, [node]
    return ast_cooked.TfpListNode(items=cvt_children_skip_commas(node, ctx))


def cvt_tname(node: pytree.Base, ctx: Ctx) -> ast_cooked.AstNode:
    """
    tname: NAME [':' test]
    vname: NAME
    """
    assert ctx.lhs_binds, [node]
    name = cvt(node.children[0], ctx)  # Mark as binds even if no RHS
    if len(node.children) == 1:
        type_expr = ast_cooked.OMITTED_NODE  # type: ast_cooked.AstNode
    else:
        type_expr = cvt_lhs_binds(False, node.children[2], ctx)
    return ast_cooked.TnameNode(name=name, type_expr=type_expr)


def cvt_trailer(node: pytree.Base, ctx: Ctx) -> ast_cooked.AstNode:
    """trailer: '(' [arglist] ')' | '[' subscriptlist ']' | '.' NAME"""
    # Can appear on LHS
    if node.children[0].type == token.LPAR:
        if node.children[1].type == token.RPAR:
            return ast_cooked.make_generic_node('()', [])
        else:
            return cvt(node.children[1], ctx)
    if node.children[0].type == token.LSQB:
        return cvt(node.children[1], ctx)
    assert node.children[0].type == token.DOT
    return ast_cooked.DotNameTrailerNode(name=cvt(node.children[1], ctx))


def cvt_try_stmt(node: pytree.Base, ctx: Ctx) -> ast_cooked.AstNode:
    """
    try_stmt: ('try' ':' suite
               ((except_clause ':' suite)+
                ['else' ':' suite]
                ['finally' ':' suite] |
               'finally' ':' suite))
    """
    assert not ctx.lhs_binds, [node]
    return ast_cooked.make_generic_node('try_stmt', [
        cvt(ch, ctx)
        for ch in node.children
        if ch.type not in (token.COLON, token.NAME)
    ])


def cvt_typedargslist(node: pytree.Base, ctx: Ctx) -> ast_cooked.AstNode:
    """
    typedargslist: ((tfpdef ['=' test] ',')*
                    ('*' [tname] (',' tname ['=' test])* [',' '**' tname] | '**' tname)
                    | tfpdef ['=' test] (',' tfpdef ['=' test])* [','])
    varargslist: ((vfpdef ['=' test] ',')*
                  ('*' [vname] (',' vname ['=' test])*  [',' '**' vname] | '**' vname)
                  | vfpdef ['=' test] (',' vfpdef ['=' test])* [','])
    """
    assert not ctx.lhs_binds, [node]
    i = 0
    args = []
    max_i = len(node.children) - 1
    while i <= max_i:
        ch0 = node.children[i]
        if ch0.type == token.COMMA:
            i += 1
            continue
        if ch0.type in SYMS_TNAMES:  # pylint: disable=no-member
            if i + 1 <= max_i and node.children[i + 1].type == token.EQUAL:
                args.append(
                    ast_cooked.TypedArgNode(
                        name=cvt_lhs_binds(True, ch0, ctx),
                        expr=cvt(node.children[i + 2], ctx)))
                i += 3
            else:
                args.append(
                    ast_cooked.TypedArgNode(
                        name=cvt_lhs_binds(True, ch0, ctx),
                        expr=ast_cooked.OMITTED_NODE))
                i += 1
        else:
            assert ch0.type in (token.STAR, token.DOUBLESTAR), [i, ch0, node]
            # Don't care about '*' or '**'
            i += 1
    return ast_cooked.TypedArgsListNode(args=args)


def cvt_while_stmt(node: pytree.Base, ctx: Ctx) -> ast_cooked.AstNode:
    """while_stmt: 'while' test ':' suite ['else' ':' suite]"""
    assert not ctx.lhs_binds, [node]
    if len(node.children) == 7:
        return ast_cooked.make_generic_node('while_stmt', [
            cvt(node.children[1], ctx),
            cvt(node.children[3], ctx),
            cvt(node.children[6], ctx)
        ])
    return ast_cooked.make_generic_node(
        'while_stmt', [cvt(node.children[1], ctx),
                       cvt(node.children[3], ctx)])


def cvt_with_item(node: pytree.Base, ctx: Ctx) -> ast_cooked.AstNode:
    """with_item: test ['as' expr]"""
    assert not ctx.lhs_binds, [node]
    item = cvt(node.children[0], ctx)
    if len(node.children) == 1:
        as_item = ast_cooked.OMITTED_NODE  # type: ast_cooked.AstNode
    else:
        as_item = cvt(node.children[2], ctx)
    return ast_cooked.WithItemNode(item=item, as_item=as_item)


def cvt_with_stmt(node: pytree.Base, ctx: Ctx) -> ast_cooked.AstNode:
    """with_stmt: 'with' with_item (',' with_item)*  ':' suite"""
    assert not ctx.lhs_binds, [node]
    return ast_cooked.WithStmt(
        items=[
            cvt(ch, ctx)
            for ch in node.children[1:-2]
            if ch.type != token.COMMA
        ],
        suite=cvt(node.children[-1], ctx))


def cvt_with_var(node: pytree.Base, ctx: Ctx) -> ast_cooked.AstNode:
    """with_var: 'as' expr"""
    assert not ctx.lhs_binds, [node]
    return cvt(node.children[1], ctx)


def cvt_yield_arg(node: pytree.Base, ctx: Ctx) -> ast_cooked.AstNode:
    """yield_arg: 'from' test | testlist"""
    assert not ctx.lhs_binds, [node]
    # Don't care about FROM
    if len(node.children) == 2:
        return cvt(node.children[1], ctx)
    return cvt(node.children[0], ctx)


def cvt_yield_expr(node: pytree.Base, ctx: Ctx) -> ast_cooked.AstNode:
    """yield_expr: 'yield' [yield_arg]"""
    assert not ctx.lhs_binds, [node]
    # Don't care about YIELD
    if len(node.children) > 1:
        return ast_cooked.make_generic_node('yield',
                                            [cvt(node.children[1], ctx)])
    return ast_cooked.make_generic_node('yield', [])


def cvt_yield_stmt(node: pytree.Base, ctx: Ctx) -> ast_cooked.AstNode:
    """yield_stmt: yield_expr"""
    assert not ctx.lhs_binds, [node]
    return cvt(node.children[0], ctx)


def cvt_token_name(node: pytree.Base, ctx: Ctx) -> ast_cooked.AstNode:
    """Handle token.NAME."""
    assert isinstance(node, pytree.Leaf)
    if (ctx.lhs_binds and node.value not in ctx.global_vars and
            node.value not in ctx.nonlocal_vars):
        ctx.bindings[node.value] = None
        this_binds = True
    else:
        this_binds = False
    return ast_cooked.NameNode(binds=this_binds, astn=node, fqn=None)


def cvt_token_number(node: pytree.Base, ctx: Ctx) -> ast_cooked.AstNode:
    """Handle token.NUMBER."""
    assert not ctx.lhs_binds, [node]
    return ast_cooked.NumberNode(astn=cast(pytree.Leaf, node))


def cvt_token_string(node: pytree.Base, ctx: Ctx) -> ast_cooked.AstNode:
    """Handle token.NAME."""
    assert not ctx.lhs_binds, [node]
    astns = node if isinstance(node, list) else [node]
    return ast_cooked.StringNode(astns=cast(List[pytree.Leaf], astns))


# The following dispatch table is derived from
# lib2to3.pygram.python_symbols (using lib2to3.pytree._type_reprs). In
# addition, NAME, NUMBER, STRING are added. This is because some
# productions have "test" or similar, which is expected to collapse to
# a name.

# pylint: disable=no-member
_DISPATCH = {
    token.NAME: cvt_token_name,
    token.NUMBER: cvt_token_number,
    token.STRING: cvt_token_string,
    syms.file_input: cvt_file_input,
    syms.and_expr: cvt_binary_op,
    syms.and_test: cvt_binary_op,
    syms.annassign: cvt_annassign,
    syms.arglist: cvt_arglist,
    syms.argument: cvt_argument,
    syms.arith_expr: cvt_binary_op,
    syms.assert_stmt: cvt_assert_stmt,
    syms.async_funcdef: cvt_async_funcdef,
    syms.async_stmt: cvt_async_stmt,
    syms.atom: cvt_atom,
    syms.augassign: cvt_augassign,
    syms.break_stmt: cvt_break_stmt,
    syms.classdef: cvt_classdef,
    syms.comp_for: cvt_comp_for,
    syms.comp_if: cvt_comp_if,
    syms.comp_iter: cvt_comp_iter,
    syms.comp_op: cvt_comp_op,
    syms.comparison: cvt_comparison,
    syms.compound_stmt: cvt_compound_stmt,
    syms.continue_stmt: cvt_continue_stmt,
    syms.decorated: cvt_decorated,
    syms.decorator: cvt_decorator,
    syms.decorators: cvt_decorators,
    syms.del_stmt: cvt_del_stmt,
    syms.dictsetmaker: cvt_dictsetmaker,
    syms.dotted_as_name: cvt_dotted_as_name,
    syms.dotted_as_names: cvt_dotted_as_names,
    syms.dotted_name: cvt_dotted_name,
    syms.encoding_decl: cvt_encoding_decl,
    syms.eval_input: cvt_eval_input,
    syms.except_clause: cvt_except_clause,
    syms.exec_stmt: cvt_exec_stmt,
    syms.expr: cvt_binary_op,
    syms.expr_stmt: cvt_expr_stmt,
    syms.exprlist: cvt_exprlist,
    syms.factor: cvt_unary_op,
    syms.flow_stmt: cvt_flow_stmt,
    syms.for_stmt: cvt_for_stmt,
    syms.funcdef: cvt_funcdef,
    syms.global_stmt: cvt_global_stmt,
    syms.if_stmt: cvt_if_stmt,
    syms.import_as_name: cvt_import_as_name,
    syms.import_as_names: cvt_import_as_names,
    syms.import_from: cvt_import_from,
    syms.import_name: cvt_import_name,
    syms.import_stmt: cvt_import_stmt,
    syms.lambdef: cvt_lambdef,
    syms.listmaker: cvt_listmaker,
    syms.not_test: cvt_unary_op,
    syms.old_lambdef: cvt_lambdef,  # not cvt_old_lambdef
    syms.old_test: cvt_test,  # not cvt_old_test
    syms.or_test: cvt_binary_op,
    syms.parameters: cvt_parameters,
    syms.pass_stmt: cvt_pass_stmt,
    syms.power: cvt_power,
    syms.print_stmt: cvt_print_stmt,
    syms.raise_stmt: cvt_raise_stmt,
    syms.return_stmt: cvt_return_stmt,
    syms.shift_expr: cvt_binary_op,
    syms.simple_stmt: cvt_simple_stmt,
    syms.single_input: cvt_single_input,
    syms.sliceop: cvt_sliceop,
    syms.small_stmt: cvt_small_stmt,
    syms.star_expr: cvt_star_expr,
    syms.stmt: cvt_stmt,
    syms.subscript: cvt_subscript,
    syms.subscriptlist: cvt_subscriptlist,
    syms.suite: cvt_suite,
    syms.term: cvt_binary_op,
    syms.test: cvt_test,
    syms.testlist: cvt_testlist,
    syms.testlist1: cvt_testlist1,
    syms.testlist_gexp: cvt_testlist_gexp,
    syms.testlist_safe: cvt_testlist_safe,
    syms.testlist_star_expr: cvt_testlist_star_expr,
    syms.tfpdef: cvt_tfpdef,
    syms.tfplist: cvt_tfplist,
    syms.tname: cvt_tname,
    syms.trailer: cvt_trailer,
    syms.try_stmt: cvt_try_stmt,
    syms.typedargslist: cvt_typedargslist,
    syms.varargslist: cvt_typedargslist,  # not varargslist
    syms.vfpdef: cvt_tfpdef,  # not vfpdef
    syms.vfplist: cvt_tfplist,  # not vfplist
    syms.vname: cvt_tname,  # not vname
    syms.while_stmt: cvt_while_stmt,
    syms.with_item: cvt_with_item,
    syms.with_stmt: cvt_with_stmt,
    syms.with_var: cvt_with_var,
    syms.xor_expr: cvt_binary_op,
    syms.yield_arg: cvt_yield_arg,
    syms.yield_expr: cvt_yield_expr,
    syms.yield_stmt: cvt_yield_stmt
}

# The following are to prevent pylint complaining about no-member:

SYMS_ANNASSIGN = syms.annassign
SYMS_AUGASSIGN = syms.augassign
SYMS_COMP_FOR = syms.comp_for
SYMS_FACTOR = syms.factor
SYMS_SIMPLE_stmt = syms.simple_stmt
SYMS_SLICEOP = syms.sliceop
SYMS_SMALL_STMT = syms.small_stmt
SYMS_SIMPLE_STMT = syms.simple_stmt
SYMS_STAR_EXPR = syms.star_expr
SYMS_STMT = syms.stmt
SYMS_TEST = syms.test
SYMS_TRAILER = syms.trailer
SYMS_TNAMES = frozenset([syms.tfpdef, syms.vfpdef, syms.tname, syms.vname])

# pylint: enable=no-member

# pylint: disable=dangerous-default-value,invalid-name


def cvt(node: pytree.Base, ctx: Ctx,
        _DISPATCH=_DISPATCH) -> ast_cooked.AstNode:
    """Call the appropriate cvt_XXX for node."""
    return _DISPATCH[node.type](node, ctx)


def cvt_debug(node: pytree.Base, ctx: Ctx,
              _DISPATCH=_DISPATCH) -> ast_cooked.AstNode:
    """Call the appropriate cvt_XXX for node."""
    # This can be used instead of cvt() for debugging.
    cvt_func = _DISPATCH[node.type]
    try:
        result = cvt_func(node, ctx)
    except Exception as exc:
        raise Exception('%s calling=%s node=%r' % (exc, cvt_func,
                                                   node)) from exc
    assert isinstance(result, ast_cooked.AstNode), [node, result]
    return result


def cvt_children(
        node: pytree.Base,  # pytree.Node
        ctx: Ctx,
        _DISPATCH=_DISPATCH) -> List[ast_cooked.AstNode]:
    """Call the appropriate cvt_XXX for all node.children."""
    return [cvt(ch, ctx) for ch in node.children]


def cvt_children_skip_commas(
        node: pytree.Base,  # pytree.Node
        ctx: Ctx,
        _DISPATCH=_DISPATCH) -> List[ast_cooked.AstNode]:
    """Call the appropriate cvt_XXX for all node.children that aren't a comma."""
    return [cvt(ch, ctx) for ch in node.children if ch.type != token.COMMA]


def cvt_lhs_binds(lhs_binds: bool,
                  node: pytree.Base,
                  ctx: Ctx,
                  _DISPATCH=_DISPATCH) -> ast_cooked.AstNode:
    """Dispatch in a new context that has lhs_binds set."""
    return cvt(node, ctx._replace(lhs_binds=lhs_binds))


# pylint: enable=dangerous-default-value,invalid-name


def parse(src_bytes: bytes) -> pytree.Base:
    """Parse a byte string."""
    # See lib2to3.refactor.RefactoringTool._read_python_source
    # TODO: add detect_encoding to typeshed: lib2to3/pgen2/tokenize.pyi
    with io.BytesIO(src_bytes) as src_f:
        encoding, _ = tokenize.detect_encoding(src_f.readline)  # type: ignore
    src_str = codecs.decode(src_bytes, encoding)
    lib2to3_logger = logging.getLogger('pykythe')
    # TODO: Use pygram.python_grammar for Python2 source
    parser_driver = driver.Driver(
        pygram.python_grammar_no_print_statement,
        convert=_convert,
        logger=lib2to3_logger)
    if not src_str.endswith('\n'):
        src_str += '\n'  # work around bug in lib2to3
    return parser_driver.parse_string(src_str)


# Node types that get removed if there's only one child. This does not
# include expr, test, yield_expr and a few others ... the intent is to
# reduce the number of AST nodes without increasing the complexity of
# analyzing the AST.
# pylint: disable=no-member
_EXPR_NODES = cast(
    FrozenSet[int],
    frozenset([
        # TODO: uncomment (for performance) -- needs more test cases first:
        # syms.and_expr,
        # syms.and_test,
        # syms.arith_expr,
        # # syms.atom,  # TODO: reinstate?
        # syms.comparison,
        # syms.factor,
        # syms.not_test,
        # syms.old_test,
        # syms.or_test,
        # # syms.power,  # TODO: reinstate?
        # syms.shift_expr,
        # # syms.star_expr,   # Always '*' expr; also needed for call arg
        # syms.term,
        # syms.xor_expr,
        # syms.comp_iter,  # Not an expr, but also not needed
        # syms.compound_stmt,  # Not an expr, but also not needed
    ]))

# pylint: enable=no-member


def _convert(grammar, raw_node):
    """Convert raw node information to a Node or Leaf instance.

    Derived from pytree.convert, by modifying the test for only a
    single child of a node (lib2to3.pytree.convert collapses this to
    the child). We could remove the test, but it reduces the number of
    nodes that are created.

    This is passed to the parser driver which calls it whenever a
    reduction of a grammar rule produces a new complete node, so that
    the tree is built strictly bottom-up.
    """
    node_type, value, context, children = raw_node
    if children or node_type in grammar.number2symbol:
        # If there's exactly one child, return that child instead of
        # creating a new node. This is done only for "expr"-type
        # nodes, to reduce the number of nodes that are created (and
        # subsequently processed):
        if len(children) == 1 and node_type in _EXPR_NODES:
            return children[0]
        return pytree.Node(node_type, children, context=context)
    else:
        return pytree.Leaf(node_type, value, context=context)
