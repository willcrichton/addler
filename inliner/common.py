import astor
from astor.code_gen import SourceGenerator
import textwrap
import itertools
import ast
import re
from iterextras import unzip
import typing
import math
import copy
import inspect
import pickle, base64
import asttokens

SEP = '___'
COMMENT_MARKER = '__inliner: '


class Comment:
    def to_stmt(self):
        comment = COMMENT_MARKER + base64.b64encode(
            pickle.dumps(self)).decode('utf-8')
        return ast.Expr(ast.Str(comment))

    @staticmethod
    def from_str(expr):
        if expr.s.startswith(COMMENT_MARKER):
            s = expr.s[len(COMMENT_MARKER):]
            obj = pickle.loads(base64.b64decode(s))
            return obj
        return None


class FunctionComment(Comment):
    def __init__(self, code, header):
        self.code = code
        self.header = header

    def to_string(self):
        return '\n' + self.code

        # if self.header:
        #     return f'\nbegin | {self.code}'
        # else:
        #     return f'end | {self.code}\n'


def dedent(s):
    no_backtick = re.sub(r'\\\n', '', s)

    # If a program has lines that don't match the top-level indent, e.g.
    # because of a multiline string, then indent the string to match top-level
    lines = no_backtick.strip('\n').split('\n')
    indent = textwrap._leading_whitespace_re.search(lines[0])
    assert indent is not None, no_backtick
    indent = indent.group(1)
    for i, line in enumerate(lines):
        if not line.startswith(indent):
            lines[i] = indent + line

    return textwrap.dedent('\n'.join(lines))


def parse_module(s):
    t = asttokens.ASTTokens(dedent(s), parse=True)
    t.tree.tokens = t.tokens
    return t.tree


def parse_stmt(s):
    return parse_module(s).body[0]


def parse_expr(s):
    return parse_stmt(s).value


class SourceGeneratorWithComments(SourceGenerator):
    COMMENTS = False

    def visit_Str(self, node):
        if self.__class__.COMMENTS:
            comment = Comment.from_str(node)
            if comment is not None:
                s = comment.to_string()
                indent = self.indent_with * self.indentation
                comment = '\n'.join(
                    [f'{indent}# {part}' for part in s.split('\n')])
                self.write(comment)
                return

        super().visit_Str(node)


def a2s(a, comments=False):
    SourceGeneratorWithComments.COMMENTS = comments
    outp = astor.to_source(a,
                           source_generator_class=SourceGeneratorWithComments)
    return re.sub(r'^\s*#\s*\n', '\n', outp, flags=re.MULTILINE).rstrip()


# https://stackoverflow.com/questions/3312989/elegant-way-to-test-python-asts-for-equality-not-reference-or-object-identity
def compare_ast(node1, node2):
    if type(node1) is not type(node2):
        return False
    if isinstance(node1, ast.AST):
        for k, v in vars(node1).items():
            if k in ('lineno', 'col_offset', 'ctx', '_pp', 'first_token',
                     'last_token', 'tokens'):
                continue
            if not compare_ast(v, getattr(node2, k)):
                return False
        return True
    elif isinstance(node1, list):
        return all(itertools.starmap(compare_ast, zip(node1, node2)))
    else:
        return node1 == node2


class ObjConversionException(Exception):
    pass


def obj_to_ast(obj):
    if isinstance(obj, tuple):
        return ast.Tuple(elts=tuple(map(obj_to_ast, obj)))
    elif isinstance(obj, dict):
        k, v = unzip([(obj_to_ast(k), obj_to_ast(v)) for k, v in obj.items()])
        return ast.Dict(k, v)
    elif isinstance(obj, list):
        return ast.List(list(map(obj_to_ast, obj)))
    elif isinstance(obj, type):
        return ast.Name(id=obj.__name__)
    elif isinstance(obj, int):
        return ast.Num(obj)
    elif isinstance(obj, str):
        return ast.Str(obj)
    elif obj is None:
        return ast.NameConstant(None)
    elif isinstance(obj, (typing._GenericAlias, typing._SpecialForm)):
        # TODO: types
        # issue was in pandas, where importing pandas._typing.Axis would
        # resolve module to typing, attempt to do "from typing import Axis"
        return ast.NameConstant(None)
    elif isinstance(obj, float) and math.isinf(obj):
        return parse_expr('float("inf")')
    elif isinstance(obj, bytes):
        return ast.Bytes(s=obj)
    else:
        raise ObjConversionException(f"No converter for {obj}")


def can_convert_obj_to_ast(obj):
    try:
        obj_to_ast(obj)
        return True
    except ObjConversionException:
        return False


def robust_eq(obj1, obj2):
    if type(obj1) != type(obj2):
        return False
    # elif isinstance(obj1, pd.DataFrame) or isinstance(obj1, pd.Series):
    #     return obj1.equals(obj2)
    # elif isinstance(obj1, np.ndarray):
    #     return np.array_equal(obj1, obj2)
    elif isinstance(obj1, tuple) or isinstance(obj1, list):
        return len(obj1) == len(obj2) and all(
            map(lambda t: robust_eq(*t), zip(obj1, obj2)))
    elif isinstance(obj1, (int, float, str)) or \
         inspect.isfunction(obj1) or \
         inspect.isclass(obj1) or \
         obj1 is None:
        return obj1 == obj2
    return False


def make_name(s):
    return ast.Name(id=s, ctx=ast.Load())


def try_copy(v):
    try:
        return copy.deepcopy(v)
    except Exception:
        try:
            return copy.copy(v)
        except Exception:
            return v


def get_function_locals(f):
    if f.__closure__ is not None and len(f.__closure__) > 0:
        return {
            var: cell.cell_contents
            for var, cell in zip(f.__code__.co_freevars, f.__closure__)
        }

    return {}


class IsEffectFree(ast.NodeVisitor):
    def __init__(self):
        self.effect_free = True

        # HACK: how can we actually detect purity?
        func_whitelist = [
            'str', 'tuple', 'list', 'int', 'float', 'utils.to_utf8',
            'LooseVersion'
        ]
        self.func_whitelist = [parse_expr(s) for s in func_whitelist]

        self.ast_whitelist = (ast.Num, ast.Str, ast.Name, ast.NameConstant,
                              ast.Load, ast.List, ast.Bytes, ast.Tuple, ast.Set,
                              ast.Dict, ast.Attribute, ast.BinOp, ast.UnaryOp,
                              ast.Index, ast.Subscript, ast.Slice)

    def generic_visit(self, node):
        if isinstance(node, ast.FunctionDef):
            return

        if isinstance(node, ast.Call):
            if not any([compare_ast(node.func, f)
                        for f in self.func_whitelist]):
                self.effect_free = False
        else:
            if not isinstance(node, self.ast_whitelist):
                self.effect_free = False

        super().generic_visit(node)


def is_effect_free(node):
    visitor = IsEffectFree()
    visitor.visit(node)
    return visitor.effect_free


class TreeSize(ast.NodeVisitor):
    def __init__(self):
        self.size = 0

    def generic_visit(self, node):
        self.size += 1
        super().generic_visit(node)


def tree_size(node):
    visitor = TreeSize()
    visitor.visit(node)
    return visitor.size
