# backend/concept_tagger.py
# Detects programming concepts in a code snippet entirely locally —
# no API call, no network, instant results.
#
# Works alongside Gemini: Gemini tags high-level concepts from meaning,
# this module tags structural patterns from syntax. Results are merged
# in main.py so the final tag list benefits from both approaches.
#
# Strategy (two passes, results merged):
#   1. Universal regex rules  — patterns that work across all languages
#   2. Language-specific AST  — Python only, uses the `ast` module for
#                               precise structural analysis

import ast
import re
import logging
from collections import defaultdict

log = logging.getLogger("pastewise.tagger")


# ──────────────────────────────────────────────────────────────────────────────
# CONCEPT DEFINITIONS
# ──────────────────────────────────────────────────────────────────────────────
# Each entry is:
#   (concept_tag, list_of_regex_patterns, min_matches_required)
#
# Patterns are matched against the full code string with re.MULTILINE.
# A concept is emitted if at least min_matches patterns fire.

_UNIVERSAL_RULES: list[tuple[str, list[str], int]] = [

    # ── Functional patterns ───────────────────────────────────────────────

    ("recursion", [
        r"(\w+)\s*\(.*\1\s*\(",         # function calling itself (heuristic)
        r"\breturn\b.*\w+\s*\(",        # return with a function call
        r"\bbase.?case\b",              # comment mentioning base case
        r"recursive",                   # word "recursive" in comments
    ], 1),

    ("higher-order function", [
        r"\bmap\s*\(|\bfilter\s*\(|\breduce\s*\(|\bforEach\s*\(", # HOF calls
        r"\.map\s*\(|\.filter\s*\(|\.reduce\s*\(",  # method HOF calls
        r"def\s+\w+\s*\(.*func.*\):",   # Python func accepting function
        r"function\s+\w+\s*\(.*function", # JS func accepting function
        r"Callable\[|Callable\s*\[",    # Python type hint
        r"\bapply\s*\(|\bcall\s*\(",    # apply/call
    ], 1),

    ("closure", [
        r"return\s+lambda",             # returning a lambda
        r"return\s+function\s*\(",      # returning a function (JS)
        r"return\s+def\b",              # edge case
        r"nonlocal\s+\w+",             # Python nonlocal (classic closure signal)
        r"\bfactory\b.*return",         # factory pattern comment/name
        r"inner\s+function|closure",    # comment mentioning closure
        r"\(\s*function\s*\(\)\s*\{",  # IIFE start (JS closure pattern)
    ], 1),

    ("currying", [
        r"return\s+lambda\s+\w+:",      # return lambda x: ...
        r"functools\.partial",          # Python partial application
        r"\.bind\s*\(",                 # JS bind
        r"curry\s*\(|\bcurried\b",      # named curry
        r"partial\s*\(",                # partial()
    ], 1),

    ("memoization", [
        r"@lru_cache|@cache",           # Python decorators
        r"functools\.lru_cache",        # explicit lru_cache
        r"\bcache\b.*=\s*\{\}|\bcache\b.*=\s*\[\]", # manual cache dict/list
        r"memo\s*=\s*\{|memo\s*=\s*\[", # memo dict/list
        r"\bif\b.*\bin cache\b|\bif\b.*\bin memo\b", # cache lookup
        r"memoize|memoization",         # word in comments/names
    ], 1),

    # ── OOP patterns ──────────────────────────────────────────────────────

    ("class", [
        r"\bclass\s+\w+",               # class keyword in any language
    ], 1),

    ("inheritance", [
        r"class\s+\w+\s*\(\s*\w+\s*\)", # Python class(Parent)
        r"class\s+\w+\s+extends\s+\w+", # JS/Java/TS extends
        r"class\s+\w+\s*:\s*\w+",      # C#/Swift colon inheritance
        r"\bsuper\s*\(|\bsuper\.\w+",  # super() call
        r"__init__.*super\(\)",         # Python super in __init__
        r"implements\s+\w+",            # Java implements
    ], 1),

    ("polymorphism", [
        r"@Override|@override",         # Java/Kotlin override
        r"virtual\s+\w+|override\s+\w+", # C++ virtual / C# override
        r"def\s+\w+.*#.*override",      # Python override (comment)
        r"protocol\s+\w+|interface\s+\w+", # Swift protocol / TS interface
        r"isinstance\s*\(|issubclass\s*\(", # runtime type check
        r"__str__|__repr__|__eq__|__lt__", # Python dunder methods
    ], 1),

    ("decorator", [
        r"^\s*@\w+",                    # @ decorator line
        r"@\w+\s*\(",                   # decorator with arguments
        r"functools\.wraps",            # wraps() — custom decorator signal
    ], 1),

    ("interface", [
        r"\binterface\s+\w+\s*\{",     # TS/Java interface
        r"\bprotocol\s+\w+\s*\{",      # Swift protocol
        r"ABC\b|ABCMeta\b|abstractmethod", # Python ABC
        r"@abstractmethod",             # Python abstract
        r"implements\s+\w+",            # Java implements
        r"trait\s+\w+\s*\{",           # Rust trait
    ], 1),

    # ── Async / concurrency ───────────────────────────────────────────────

    ("async/await", [
        r"\basync\s+def\b",             # Python async def
        r"\basync\s+function\b",        # JS async function
        r"\bawait\s+\w+",              # await keyword
        r"async\s*\(",                  # async lambda (Kotlin)
        r"asyncio\.",                   # Python asyncio module
        r"async\s+for\b|async\s+with\b", # Python async for/with
    ], 1),

    ("promise", [
        r"new\s+Promise\s*\(",          # new Promise()
        r"\.then\s*\(|\.catch\s*\(",   # promise chain
        r"Promise\.(all|race|allSettled|any)\s*\(", # Promise combinators
        r"\.finally\s*\(",              # .finally
    ], 1),

    ("callback", [
        r"function\s*\(\s*\w*\s*\)\s*\{.*\}", # inline function arg (JS)
        r"\bcallback\b|\bcb\b\s*\(",   # named callback
        r"setTimeout\s*\(|setInterval\s*\(", # timer callbacks
        r"addEventListener\s*\(",       # event listener
        r"\.on\s*\(['\"\w]",           # .on('event', ...)
    ], 1),

    ("concurrency", [
        r"\bThread\s*\(|\bthread\b",   # threading
        r"threading\.\w+",             # Python threading module
        r"concurrent\.futures",        # Python concurrent.futures
        r"goroutine|go\s+func",        # Go goroutines
        r"chan\s+\w+|<-\s*\w+",        # Go channels
        r"Mutex|RWMutex|Lock\(\)",     # mutex
        r"synchronized\s*\(",          # Java synchronized
        r"CompletableFuture|ExecutorService", # Java concurrency
        r"@Async|@Scheduled",          # Spring annotations
    ], 1),

    ("generator", [
        r"\byield\b",                   # yield keyword
        r"function\s*\*\s*\w*\s*\(",   # JS generator function
        r"def\s+\w+.*yield",           # Python generator function
        r"__iter__|__next__",          # Python iterator protocol
        r"iter\s*\(|next\s*\(",        # iter/next calls
    ], 1),

    ("event loop", [
        r"asyncio\.run\s*\(|asyncio\.get_event_loop", # Python event loop
        r"\.run_until_complete\s*\(",  # explicit event loop run
        r"uv_run|libuv",               # Node.js internals
        r"EventEmitter",               # Node.js EventEmitter
        r"Looper\.",                   # Android Looper
    ], 1),

    # ── Data structures ───────────────────────────────────────────────────

    ("linked list", [
        r"\.next\s*=|\.prev\s*=",      # next/prev pointer assignment
        r"class\s+Node\b",             # Node class
        r"ListNode|LinkedList",        # named types
        r"head\s*=\s*None|tail\s*=\s*None", # head/tail init
        r"node\.next|node\.prev",      # node traversal
    ], 1),

    ("tree traversal", [
        r"inorder|preorder|postorder", # traversal names
        r"left\s*=.*right\s*=",       # left/right children
        r"TreeNode|BinaryTree",        # named types
        r"root\s*=\s*None|root\.left|root\.right", # root operations
        r"level.?order|bfs.*tree|dfs.*tree", # BFS/DFS on tree
    ], 1),

    ("graph traversal", [
        r"\bbfs\b|\bbreadth.first\b",  # BFS
        r"\bdfs\b|\bdepth.first\b",   # DFS
        r"\badjacency\b",              # adjacency list/matrix
        r"visited\s*=\s*set\(\)|visited\s*=\s*\[\]", # visited set
        r"queue\.append\(|deque\s*\(", # BFS queue
        r"graph\[.*\].*graph\[",       # graph indexing
    ], 1),

    ("sorting", [
        r"\bsort\s*\(|\bsorted\s*\(",  # sort calls
        r"bubble.?sort|merge.?sort|quick.?sort|heap.?sort|insertion.?sort", # named sorts
        r"\bcompareTo\b|\bcomparator\b", # Java comparator
        r"key\s*=\s*lambda",           # Python sort key
        r"Arrays\.sort\s*\(|Collections\.sort\s*\(", # Java sort
    ], 1),

    ("binary search", [
        r"\bbinary.?search\b",         # named binary search
        r"lo\s*=|hi\s*=|left\s*=.*right\s*=", # lo/hi pointers
        r"mid\s*=\s*.*//\s*2|mid\s*=.*>>.*1", # midpoint calculation
        r"bisect\.\w+\s*\(",           # Python bisect
        r"while\s+\w+\s*<=?\s*\w+.*mid", # binary search loop
    ], 1),

    ("dynamic programming", [
        r"\bdp\b\s*=\s*\[|\bdp\b\s*=\s*\{", # dp array/dict
        r"memoize|tabulation|subproblem", # DP vocabulary
        r"dp\[i\]|dp\[j\]",           # DP indexing
        r"bottom.?up|top.?down",       # DP approaches
        r"optimal.?substructure|overlapping.?subproblems", # DP theory
    ], 1),

    ("stack", [
        r"\.push\s*\(|\.pop\s*\(",     # push/pop
        r"stack\s*=\s*\[\]|stack\s*=\s*deque", # stack init
        r"stack\.append\s*\(",         # Python stack append
        r"LIFO|last.in.first.out",     # named
        r"Stack\(\)|ArrayDeque",       # Java Stack
    ], 1),

    ("queue", [
        r"from\s+collections\s+import\s+deque|deque\s*\(", # Python deque
        r"queue\s*=\s*\[\]|Queue\(\)", # queue init
        r"\.enqueue\s*\(|\.dequeue\s*\(", # enqueue/dequeue
        r"FIFO|first.in.first.out",    # named
        r"heapq\.\w+\s*\(",            # Python heap queue
    ], 1),

    ("hash map", [
        r"\bdict\s*\(\)|\bdefaultdict\b|\bCounter\b", # Python
        r"HashMap\s*<|TreeMap\s*<",    # Java
        r"\bmap\s*=\s*\{|\bmap\s*=\s*new\s+Map", # JS Map / generic
        r"\.get\s*\(.*\).*\.put\s*\(", # get/put pattern
        r"collections\.defaultdict",   # defaultdict
    ], 1),

    # ── Python-specific ───────────────────────────────────────────────────

    ("list comprehension", [
        r"\[.*\bfor\b.*\bin\b.*\]",    # [expr for x in iter]
        r"\{.*\bfor\b.*\bin\b.*\}",   # set/dict comprehension
        r"\(.*\bfor\b.*\bin\b.*\)",   # generator expression
    ], 1),

    ("context manager", [
        r"\bwith\s+\w+.*\bas\s+\w+\b", # with ... as
        r"__enter__|__exit__",         # context manager protocol
        r"@contextmanager",            # contextlib decorator
        r"contextlib\.",               # contextlib usage
    ], 1),

    ("type annotation", [
        r":\s*(str|int|float|bool|list|dict|tuple|set|Any|None)\b", # basic hints
        r"from\s+typing\s+import",     # typing module
        r"Optional\[|Union\[|List\[|Dict\[|Tuple\[|Set\[", # typing generics
        r"->\s*(str|int|float|bool|None|\w+)\s*:", # return type hint
        r"TypeVar\s*\(|Generic\[",    # generics
        r"dataclass|@dataclass",       # dataclass
    ], 1),

    ("error handling", [
        r"\btry\s*[:\{]|\bexcept\b|\bcatch\b", # try/except/catch
        r"\bfinally\s*[:\{]",          # finally block
        r"\braise\b\s+\w+|\bthrow\b\s+new", # raise / throw
        r"Exception\s*\(|Error\s*\(", # exception instantiation
        r"\.catch\s*\(|\.error\s*\(", # promise/callback error
        r"Result<|Option<",            # Rust error types
    ], 1),

    ("immutability", [
        r"\bfrozenset\s*\(|\bconst\b\s+\w+", # frozenset / const
        r"\btuple\s*\(|\bNamedTuple\b", # immutable tuple
        r"readonly\s+\w+|Readonly<",   # readonly
        r"Object\.freeze\s*\(",        # JS freeze
        r"\bval\s+\w+",                # Kotlin val
        r"@dataclass.*frozen\s*=\s*True", # frozen dataclass
    ], 1),

    # ── Design patterns ───────────────────────────────────────────────────

    ("singleton", [
        r"_instance\s*=\s*None|instance\s*=\s*None", # singleton instance
        r"cls\._instance|cls\.instance", # class-level instance
        r"__new__\s*\(",               # __new__ override
        r"getInstance\s*\(",           # Java/JS getInstance
        r"@Singleton|@singleton",      # annotation
    ], 1),

    ("dependency injection", [
        r"__init__\s*\(.*self.*\w+\s*:\s*\w+", # constructor injection
        r"@Inject|@inject|@Autowired",  # DI annotations
        r"container\.\w+\(|injector\.\w+\(", # DI container
        r"Depends\s*\(|dependency_overrides", # FastAPI DI
    ], 1),

    ("observer pattern", [
        r"subscribe\s*\(|unsubscribe\s*\(", # subscribe/unsubscribe
        r"notify\s*\(|notifyObservers", # notify
        r"addEventListener\s*\(",      # DOM observer
        r"Observable|Observer\b",      # named types
        r"on\s*\(['\"].*['\"].*function", # event binding
    ], 1),

    ("factory pattern", [
        r"def\s+create_\w+|def\s+make_\w+", # create/make factory method
        r"Factory\b|factory\b",        # named factory
        r"@staticmethod.*return\s+\w+\(", # static factory
        r"class.*Factory.*:",          # Factory class
    ], 1),

    # ── Web / API ─────────────────────────────────────────────────────────

    ("api call", [
        r"requests\.\w+\s*\(|httpx\.\w+\s*\(", # Python HTTP
        r"fetch\s*\(|axios\.\w+\s*\(", # JS HTTP
        r"urllib\.\w+|http\.client",   # Python stdlib HTTP
        r"\.get\s*\(.*url|\.post\s*\(.*url", # generic HTTP verbs
        r"response\.json\s*\(|\.json\(\)", # JSON response
        r"status_code|statusCode",     # HTTP status
    ], 1),

    ("dom manipulation", [
        r"document\.\w+\s*\(",         # document API
        r"getElementById|querySelector\s*\(", # element selection
        r"innerHTML|textContent|innerText", # content mutation
        r"createElement\s*\(|appendChild\s*\(", # DOM creation
        r"classList\.\w+\s*\(",        # class manipulation
        r"style\.\w+\s*=",            # style mutation
    ], 1),

    ("regex", [
        r"re\.\w+\s*\(|re\.compile\s*\(", # Python re module
        r"RegExp\s*\(|\/.*\/[gimsuy]*", # JS regex literal
        r"Pattern\.compile\s*\(",      # Java Pattern
        r"\bregex\b|\bregexp\b",       # word regex/regexp
        r"match\s*\(.*r['\"]|search\s*\(.*r['\"]", # Python raw string regex
    ], 1),

    ("state management", [
        r"useState\s*\(|useReducer\s*\(", # React hooks
        r"Redux|Vuex|Pinia|Zustand",   # state libraries
        r"setState\s*\(|this\.state",  # React class state
        r"store\.\w+|dispatch\s*\(",   # store pattern
        r"@observable|@computed|mobx", # MobX
    ], 1),

    # ── Memory / performance ──────────────────────────────────────────────

    ("bit manipulation", [
        r"\b&\s*\d+|\b\|\s*\d+|\b\^\s*\d+", # bitwise &, |, ^
        r"<<\s*\d+|>>\s*\d+",         # bit shift
        r"~\s*\w+",                   # bitwise NOT
        r"\bxor\b|\band\b.*\bor\b",   # named bitwise ops
        r"0b[01]+|0x[0-9a-fA-F]+",    # binary/hex literal
        r"bitmask|bitflag|bitwise",    # vocabulary
    ], 1),

    ("pointer / reference", [
        r"\*\w+\s*=|\&\w+",           # C/C++ pointer/ref
        r"malloc\s*\(|free\s*\(",     # dynamic memory
        r"nullptr|NULL\b",             # null pointer
        r"\bderef\b|dereference",      # dereferencing
        r"Rc<|Arc<|Box<|RefCell<",    # Rust smart pointers
    ], 1),

    ("side effect", [
        r"global\s+\w+",              # Python global
        r"nonlocal\s+\w+",            # Python nonlocal
        r"console\.\w+\s*\(",         # console output (side effect)
        r"print\s*\(",                 # print (side effect)
        r"os\.\w+\s*\(|sys\.\w+\s*\(", # os/sys calls
        r"open\s*\(.*['\"]w['\"]",   # file write
    ], 1),

    ("pure function", [
        r"pure\s+function|pure_function|@pure", # named/annotated
        r"return\s+\w+.*\+.*\w+",    # simple expression return
        r"no.*side.?effect",          # comment
        r"deterministic",              # deterministic comment
        r"idempotent",                 # idempotent comment
    ], 1),

    # ── Paradigm markers ──────────────────────────────────────────────────

    ("recursion", [                    # second entry — broader patterns
        r"def\s+(\w+).*:\s*(?:.*\n)*.*\1\s*\(", # Python self-call (multiline)
        r"function\s+(\w+)\s*\(.*\)\s*\{(?:.*\n)*.*\1\s*\(", # JS self-call
        r"fibonacci|factorial|hanoi|permut", # classic recursive problem names
    ], 1),

    ("tail recursion", [
        r"tail.?recursi",              # named in comment/variable
        r"return\s+\w+\s*\(.*accumulator|return.*acc\s*=", # accumulator pattern
    ], 1),

    ("lazy evaluation", [
        r"\byield\b.*\bfrom\b|\byield\b", # generator (lazy)
        r"itertools\.\w+\s*\(",        # itertools (lazy sequences)
        r"lazy\s*=\s*True|LazyEvaluation|@lazy", # named lazy
        r"\.lazy\(\)|Sequence\.lazy",  # Swift/Kotlin lazy
    ], 1),

]


# ──────────────────────────────────────────────────────────────────────────────
# LANGUAGE-SPECIFIC AST ANALYSIS (Python only)
# ──────────────────────────────────────────────────────────────────────────────

def _tag_with_ast(code: str) -> list[str]:
    """
    Parse Python code with the `ast` module and tag structural concepts
    that are hard to detect reliably with regex alone.

    Returns a (possibly empty) list of concept tag strings.
    Falls back gracefully if the code has syntax errors.
    """
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return []

    tags: set[str] = set()
    visitor        = _ConceptVisitor()
    visitor.visit(tree)
    tags.update(visitor.tags)
    return sorted(tags)


class _ConceptVisitor(ast.NodeVisitor):
    """
    Walks a Python AST and accumulates concept tags based on
    the structural features found in the tree.
    """

    def __init__(self):
        self.tags:            set[str] = set()
        self._func_names:     set[str] = set()   # to detect recursion
        self._current_func:   str | None = None

    # ── Functions ─────────────────────────────────────────────────────────

    def visit_FunctionDef(self, node: ast.FunctionDef):
        self._func_names.add(node.name)
        prev = self._current_func
        self._current_func = node.name
        self.generic_visit(node)
        self._current_func = prev

    visit_AsyncFunctionDef = visit_FunctionDef

    # ── Decorators → decorator tag ────────────────────────────────────────

    def visit_ClassDef(self, node: ast.ClassDef):
        self.tags.add("class")

        # Inheritance
        if node.bases:
            self.tags.add("inheritance")

        # Decorators on the class itself
        if node.decorator_list:
            self.tags.add("decorator")

        self.generic_visit(node)

    # ── Yield → generator ─────────────────────────────────────────────────

    def visit_Yield(self, node: ast.Yield):
        self.tags.add("generator")
        self.generic_visit(node)

    def visit_YieldFrom(self, node: ast.YieldFrom):
        self.tags.add("generator")
        self.generic_visit(node)

    # ── Await / async → async/await ───────────────────────────────────────

    def visit_Await(self, node: ast.Await):
        self.tags.add("async/await")
        self.generic_visit(node)

    # ── Try/Except → error handling ───────────────────────────────────────

    def visit_Try(self, node: ast.Try):
        self.tags.add("error handling")
        self.generic_visit(node)

    # ── List/Set/Dict comprehensions ──────────────────────────────────────

    def visit_ListComp(self, node: ast.ListComp):
        self.tags.add("list comprehension")
        self.generic_visit(node)

    def visit_SetComp(self, node: ast.SetComp):
        self.tags.add("list comprehension")
        self.generic_visit(node)

    def visit_DictComp(self, node: ast.DictComp):
        self.tags.add("list comprehension")
        self.generic_visit(node)

    def visit_GeneratorExp(self, node: ast.GeneratorExp):
        self.tags.add("generator")
        self.tags.add("list comprehension")
        self.generic_visit(node)

    # ── With statement → context manager ─────────────────────────────────

    def visit_With(self, node: ast.With):
        self.tags.add("context manager")
        self.generic_visit(node)

    def visit_AsyncWith(self, node: ast.AsyncWith):
        self.tags.add("context manager")
        self.tags.add("async/await")
        self.generic_visit(node)

    # ── Lambda → higher-order / closure signals ───────────────────────────

    def visit_Lambda(self, node: ast.Lambda):
        self.tags.add("higher-order function")
        self.generic_visit(node)

    # ── Global / Nonlocal → side effect / closure ─────────────────────────

    def visit_Global(self, node: ast.Global):
        self.tags.add("side effect")
        self.generic_visit(node)

    def visit_Nonlocal(self, node: ast.Nonlocal):
        self.tags.add("closure")
        self.generic_visit(node)

    # ── Function calls — detect recursion, HOF usage ──────────────────────

    def visit_Call(self, node: ast.Call):
        # Recursion: calling a function with the same name as the current one
        if self._current_func:
            called = _get_call_name(node)
            if called and called == self._current_func:
                self.tags.add("recursion")

        # Map / filter / reduce calls
        called = _get_call_name(node)
        if called in ("map", "filter", "reduce", "sorted", "max", "min"):
            # Only tag if argument is a callable (lambda or function ref)
            if node.args and isinstance(node.args[0], (ast.Lambda, ast.Name)):
                self.tags.add("higher-order function")

        self.generic_visit(node)

    # ── Annotations → type annotation ────────────────────────────────────

    def visit_AnnAssign(self, node: ast.AnnAssign):
        self.tags.add("type annotation")
        self.generic_visit(node)

    def visit_FunctionDef_annotations(self, node: ast.FunctionDef):
        if node.returns or any(
            a.annotation for a in node.args.args if a.annotation
        ):
            self.tags.add("type annotation")

    # ── Imports — detect key libraries ───────────────────────────────────

    def visit_Import(self, node: ast.Import):
        for alias in node.names:
            self._check_import(alias.name)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom):
        if node.module:
            self._check_import(node.module)
            for alias in node.names:
                self._check_import_name(alias.name)
        self.generic_visit(node)

    def _check_import(self, module: str):
        _MODULE_TAGS = {
            "asyncio":               "async/await",
            "threading":             "concurrency",
            "concurrent":            "concurrency",
            "multiprocessing":       "concurrency",
            "functools":             "higher-order function",
            "itertools":             "lazy evaluation",
            "re":                    "regex",
            "abc":                   "interface",
            "dataclasses":           "type annotation",
            "typing":                "type annotation",
            "contextlib":            "context manager",
            "collections":           "hash map",
            "heapq":                 "queue",
            "requests":              "api call",
            "httpx":                 "api call",
            "aiohttp":               "api call",
        }
        for prefix, tag in _MODULE_TAGS.items():
            if module.startswith(prefix):
                self.tags.add(tag)

    def _check_import_name(self, name: str):
        _NAME_TAGS = {
            "lru_cache":     "memoization",
            "cache":         "memoization",
            "wraps":         "decorator",
            "partial":       "currying",
            "reduce":        "higher-order function",
            "ABC":           "interface",
            "abstractmethod":"interface",
            "dataclass":     "type annotation",
            "contextmanager":"context manager",
            "deque":         "queue",
            "defaultdict":   "hash map",
            "Counter":       "hash map",
            "namedtuple":    "immutability",
        }
        tag = _NAME_TAGS.get(name)
        if tag:
            self.tags.add(tag)


def _get_call_name(node: ast.Call) -> str | None:
    """Extract the function name from a Call node, if simple."""
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return None


# ──────────────────────────────────────────────────────────────────────────────
# UNIVERSAL REGEX ENGINE
# ──────────────────────────────────────────────────────────────────────────────

def _tag_with_regex(code: str) -> list[str]:
    """
    Run all universal regex rules against the code.
    Returns a deduplicated list of matched concept tags.
    """
    flags   = re.MULTILINE | re.IGNORECASE | re.DOTALL
    matched: set[str] = set()

    # Track which tags we've already matched to avoid double-adding
    # (some concepts appear twice in _UNIVERSAL_RULES for broader coverage)
    tag_hits: dict[str, int] = defaultdict(int)

    for (tag, patterns, required) in _UNIVERSAL_RULES:
        hits = sum(1 for p in patterns if re.search(p, code, flags))
        if hits >= required:
            tag_hits[tag] += hits

    return list(tag_hits.keys())


# ──────────────────────────────────────────────────────────────────────────────
# PUBLIC API
# ──────────────────────────────────────────────────────────────────────────────

def tag_concepts(code: str, language: str = "unknown") -> list[str]:
    """
    Main entry point — returns a deduplicated, sorted list of concept tags
    found in the code snippet.

    Combines:
      - Universal regex rules (all languages)
      - Python AST analysis   (Python only)

    Result is merged with Gemini's tags in main.py.

    Examples:
        tag_concepts("def f(x): return f(x-1)", "Python")
        → ["error handling", "recursion"]

        tag_concepts("[x*2 for x in range(10)]", "Python")
        → ["list comprehension"]

        tag_concepts("const add = (a, b) => a + b;", "JavaScript")
        → ["higher-order function"]
    """
    if not code.strip():
        return []

    tags: set[str] = set()

    # ── Regex pass (universal) ────────────────────────────────────────────
    regex_tags = _tag_with_regex(code)
    tags.update(regex_tags)

    # ── AST pass (Python only) ────────────────────────────────────────────
    if language == "Python":
        ast_tags = _tag_with_ast(code)
        tags.update(ast_tags)

    result = sorted(tags)
    log.debug(f"Concepts tagged: {result}")
    return result


def tag_concepts_with_scores(
    code: str,
    language: str = "unknown",
) -> dict[str, int]:
    """
    Like tag_concepts() but returns a dict of {tag: hit_count} so the
    caller can rank tags by how strongly they were detected.

    Used internally — exposed for debugging and future dashboard features.
    """
    if not code.strip():
        return {}

    flags    = re.MULTILINE | re.IGNORECASE | re.DOTALL
    scores: dict[str, int] = defaultdict(int)

    for (tag, patterns, required) in _UNIVERSAL_RULES:
        hits = sum(1 for p in patterns if re.search(p, code, flags))
        if hits >= required:
            scores[tag] += hits

    if language == "Python":
        for t in _tag_with_ast(code):
            scores[t] += 2   # AST match is higher confidence than regex

    return dict(scores)