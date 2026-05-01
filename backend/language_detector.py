# backend/language_detector.py
# Detects the programming language of a code snippet entirely locally —
# no API call, no network, instant results.
#
# Strategy (three layers, first confident match wins):
#   1. Heuristic rules  — fast regex patterns for unmistakable signatures
#   2. Pygments lexer   — battle-tested library covering 500+ languages
#   3. Frequency scorer — character/token statistics as final tiebreaker

import re
import logging
from typing import NamedTuple

log = logging.getLogger("pastewise.detector")


# ──────────────────────────────────────────────────────────────────────────────
# RESULT TYPE
# ──────────────────────────────────────────────────────────────────────────────

class DetectionResult(NamedTuple):
    language:   str    # canonical name  e.g. "Python"
    confidence: float  # 0.0 – 1.0
    method:     str    # "heuristic" | "pygments" | "frequency" | "unknown"


# ──────────────────────────────────────────────────────────────────────────────
# LAYER 1 — HEURISTIC RULES
# ──────────────────────────────────────────────────────────────────────────────
# Each rule is (language_name, list_of_patterns, required_matches).
# A language wins if at least `required_matches` of its patterns fire.
# Patterns are checked against the full code string (re.MULTILINE | re.DOTALL).

_HEURISTIC_RULES: list[tuple[str, list[str], int]] = [

    ("Python", [
        r"^\s*def\s+\w+\s*\(",           # function definition
        r"^\s*class\s+\w+.*:",           # class definition
        r"^\s*import\s+\w+",             # import statement
        r"^\s*from\s+\w+\s+import",      # from-import
        r"^\s*@\w+",                     # decorator
        r":\s*$",                        # line ending with colon (if/for/while)
        r"^\s*print\s*\(",               # print()
        r"#.*$",                         # comment
        r'"""[\s\S]*?"""',               # docstring
        r"^\s*elif\s+",                  # elif (Python-only keyword)
        r"^\s*except\s+\w*.*:",          # except clause
        r"lambda\s+\w+.*:",              # lambda
        r"^\s*with\s+.*\s+as\s+",        # context manager
        r"\bNone\b",                     # None literal
        r"\bTrue\b|\bFalse\b",           # bool literals
        r"f['\"].*\{",                   # f-string
    ], 3),

    ("JavaScript", [
        r"^\s*const\s+\w+\s*=",          # const declaration
        r"^\s*let\s+\w+\s*=",            # let declaration
        r"^\s*var\s+\w+\s*=",            # var declaration
        r"=>\s*\{",                      # arrow function body
        r"=>\s*\w",                      # arrow function expression
        r"^\s*function\s+\w+\s*\(",      # function keyword
        r"console\.(log|error|warn)\s*\(", # console methods
        r"document\.\w+",                # DOM access
        r"require\s*\(['\"]",            # CommonJS require
        r"module\.exports",              # CommonJS exports
        r"^\s*import\s+.*\s+from\s+['\"]", # ES module import
        r"export\s+default\s+",          # ES module export
        r"===|!==",                      # strict equality
        r"Promise\.|\.then\s*\(|\.catch\s*\(", # Promise chain
        r"async\s+function|await\s+\w",  # async/await
        r"\.forEach\s*\(|\.map\s*\(|\.filter\s*\(", # array methods
    ], 3),

    ("TypeScript", [
        r":\s*(string|number|boolean|void|any|never|unknown)\b", # type annotation
        r"interface\s+\w+\s*\{",         # interface
        r"type\s+\w+\s*=",              # type alias
        r"<\w+>\s*\(",                   # generic call
        r"as\s+(string|number|boolean|any|\w+Type)\b", # type assertion
        r"readonly\s+\w+",               # readonly modifier
        r"(public|private|protected)\s+\w+\s*[:(]", # access modifiers
        r"implements\s+\w+",             # implements keyword
        r"enum\s+\w+\s*\{",             # enum
        r"namespace\s+\w+\s*\{",         # namespace
        r"!\s*$",                        # non-null assertion
        r"Partial<|Required<|Readonly<|Pick<|Omit<", # utility types
    ], 2),

    ("Java", [
        r"public\s+(static\s+)?class\s+\w+", # class declaration
        r"public\s+static\s+void\s+main\s*\(", # main method
        r"System\.out\.print(ln)?\s*\(", # System.out
        r"^\s*import\s+java\.",           # java imports
        r"@Override|@Deprecated|@SuppressWarnings", # annotations
        r"(public|private|protected)\s+(static\s+)?\w+\s+\w+\s*\(", # method
        r"new\s+\w+\s*\(",               # object instantiation
        r"throws\s+\w+Exception",        # throws clause
        r"try\s*\{.*\}\s*catch\s*\(",    # try/catch
        r"\bfinal\s+\w+\b",              # final keyword
        r"ArrayList|HashMap|HashSet|LinkedList", # common collections
    ], 3),

    ("C#", [
        r"using\s+System",               # using directive
        r"namespace\s+\w+",             # namespace
        r"(public|private|protected)\s+(static\s+)?class\s+\w+", # class
        r"Console\.(Write|WriteLine)\s*\(", # Console output
        r"^\s*\[(\w+)\]",               # attribute
        r"\bvar\b.*=.*new\s+\w+",        # var with new
        r"async\s+Task|await\s+\w",      # async Task
        r"string\s+\w+\s*=",            # string type (lowercase)
        r"LINQ|\.Where\s*\(|\.Select\s*\(|\.FirstOrDefault", # LINQ
        r"get\s*;\s*set\s*;",            # auto-property
        r"=>.*\bthrow\b",               # expression body
    ], 3),

    ("C++", [
        r"#include\s*<\w+>",             # include directive
        r"#include\s*[\"<].*\.h[>\"]",   # header include
        r"std::",                        # std namespace
        r"cout\s*<<|cin\s*>>",           # stream operators
        r"int\s+main\s*\(",              # main function
        r"template\s*<",                 # template
        r"::\s*\w+",                     # scope resolution
        r"nullptr|NULL\b",               # null pointer
        r"delete\s+\w+|new\s+\w+\s*\(", # dynamic memory
        r"virtual\s+\w+",               # virtual method
        r"public:|private:|protected:",  # access specifiers (colon)
    ], 3),

    ("C", [
        r"#include\s*<stdio\.h>",        # stdio include
        r"#include\s*<stdlib\.h>",       # stdlib include
        r"int\s+main\s*\(\s*(void|int\s+argc)", # main signature
        r"printf\s*\(",                  # printf
        r"scanf\s*\(",                   # scanf
        r"malloc\s*\(|free\s*\(",        # memory management
        r"struct\s+\w+\s*\{",           # struct definition
        r"typedef\s+\w+",               # typedef
        r"->\s*\w+",                     # pointer member access
        r"#define\s+\w+",               # macro
    ], 3),

    ("Go", [
        r"^package\s+\w+",              # package declaration
        r"^import\s+\(",                # grouped imports
        r"func\s+\w+\s*\(",             # function definition
        r":=\s*",                       # short variable declaration
        r"fmt\.(Print|Println|Sprintf)", # fmt package
        r"goroutine|go\s+func\s*\(",    # goroutine
        r"chan\s+\w+",                  # channel type
        r"defer\s+\w+",                 # defer
        r"interface\s*\{",              # interface{}
        r"make\s*\(|append\s*\(",       # built-in functions
        r"\.go\b",                      # .go file reference
    ], 3),

    ("Rust", [
        r"fn\s+\w+\s*\(",               # function definition
        r"let\s+(mut\s+)?\w+\s*[=:]",  # let binding
        r"^\s*use\s+\w+::",             # use statement
        r"impl\s+\w+",                  # impl block
        r"#\[derive\(",                 # derive attribute
        r"println!\s*\(",               # println macro
        r"Vec<|HashMap<|Option<|Result<", # generic types
        r"match\s+\w+\s*\{",           # match expression
        r"->\s*\w+\s*\{",              # return type arrow
        r"&mut\s+\w+|&\w+",            # references
        r"unwrap\(\)|expect\(",         # unwrap/expect
        r"'static\b|'a\b",             # lifetime annotations
    ], 3),

    ("Swift", [
        r"^\s*import\s+(UIKit|Foundation|SwiftUI|Combine)\b", # Swift frameworks
        r"func\s+\w+\s*\(",             # function
        r"var\s+\w+\s*:\s*\w+",        # typed var
        r"let\s+\w+\s*:\s*\w+",        # typed let
        r"guard\s+let|if\s+let\s+",    # optional binding
        r"@IBOutlet|@IBAction",         # Interface Builder
        r"struct\s+\w+\s*:\s*\w+",     # struct conformance
        r"protocol\s+\w+\s*\{",        # protocol
        r"\?\?|!\s*$",                  # nil coalescing / force unwrap
        r"print\s*\(",                  # print
    ], 3),

    ("Kotlin", [
        r"fun\s+\w+\s*\(",              # function
        r"val\s+\w+\s*[=:]",           # val declaration
        r"var\s+\w+\s*[=:]",           # var declaration
        r"^\s*import\s+kotlin\.",       # kotlin imports
        r"data\s+class\s+\w+",         # data class
        r"object\s+\w+\s*\{",          # object declaration
        r"companion\s+object",          # companion object
        r"println\s*\(",                # println
        r"when\s*\(",                   # when expression
        r"\?\.\w+|\?:",                 # safe call / elvis
        r"suspend\s+fun|coroutineScope", # coroutines
    ], 3),

    ("PHP", [
        r"<\?php",                      # PHP open tag
        r"\$\w+\s*=",                   # variable assignment
        r"echo\s+",                     # echo
        r"function\s+\w+\s*\(\$",      # function with $ param
        r"array\s*\(|=>\s*",           # array syntax
        r"namespace\s+\w+\\",          # PHP namespace
        r"use\s+\w+\\",                # use statement
        r"->|\$this->",                # object operator
        r"public\s+function\s+\w+",    # method
        r"require_once|include_once",   # file inclusion
    ], 3),

    ("Ruby", [
        r"^\s*def\s+\w+",              # method definition
        r"^\s*class\s+\w+\s*<?\s*\w*", # class (with optional parent)
        r"^\s*require\s+['\"]",         # require
        r"puts\s+|p\s+",               # output
        r"do\s*\|.*\|",                # block with params
        r"\bnil\b|\btrue\b|\bfalse\b", # Ruby literals
        r"attr_accessor|attr_reader",   # attribute helpers
        r"\.each\s*\{|\.map\s*\{",     # enumerable
        r"@\w+\s*=",                   # instance variable
        r"^\s*end\s*$",                # end keyword
        r":\w+",                       # symbol
    ], 3),

    ("SQL", [
        r"\bSELECT\b.*\bFROM\b",       # SELECT statement
        r"\bINSERT\s+INTO\b",           # INSERT
        r"\bUPDATE\b.*\bSET\b",        # UPDATE
        r"\bDELETE\s+FROM\b",          # DELETE
        r"\bCREATE\s+TABLE\b",         # CREATE TABLE
        r"\bALTER\s+TABLE\b",          # ALTER TABLE
        r"\bDROP\s+TABLE\b",           # DROP TABLE
        r"\bJOIN\b.*\bON\b",           # JOIN
        r"\bWHERE\b\s+\w+",            # WHERE clause
        r"\bGROUP\s+BY\b|\bORDER\s+BY\b", # aggregation
        r"\bINNER|OUTER|LEFT|RIGHT\s+JOIN\b", # join types
    ], 2),

    ("HTML", [
        r"<!DOCTYPE\s+html",            # doctype
        r"<html[\s>]",                  # html tag
        r"<head[\s>]|<body[\s>]",       # head/body
        r"<div[\s>]|<span[\s>]|<p[\s>]", # common tags
        r"<a\s+href=|<img\s+src=",      # anchor/img
        r"<script[\s>]|<style[\s>]",    # script/style
        r"class=['\"]|id=['\"]",        # attributes
    ], 2),

    ("CSS", [
        r"[a-z-]+\s*:\s*[\w#\(\)%,\s]+;", # property: value;
        r"\{[^}]*\}",                   # rule block
        r"@media\s+",                   # media query
        r"@keyframes\s+\w+",            # keyframe
        r"@import\s+['\"]",             # import
        r":\s*(hover|focus|active|nth-child|before|after)", # pseudo
        r"--[\w-]+\s*:",                # CSS variable
        r"\.([\w-]+)\s*\{",            # class selector
        r"#([\w-]+)\s*\{",             # id selector
    ], 3),

    ("Shell", [
        r"#!/(bin|usr/bin)/(bash|sh|zsh)", # shebang
        r"^\s*echo\s+",                 # echo
        r"\$\{?\w+\}?",                 # variable expansion
        r"^\s*if\s+\[",                 # if test
        r"^\s*for\s+\w+\s+in\s+",      # for loop
        r"^\s*while\s+\[",             # while loop
        r"\bfi\b|\bdone\b|\besac\b",   # control keywords
        r"\|\s*\w+",                   # pipe
        r">\s*/\w+|>>\s*/\w+",         # redirect
        r"chmod|chown|grep|awk|sed",   # common commands
    ], 3),

    ("R", [
        r"<-\s*\w+",                   # assignment operator
        r"^\s*library\s*\(",            # library()
        r"c\s*\([\d,\s]+\)",           # c() vector
        r"data\.frame\s*\(",            # data.frame
        r"ggplot\s*\(",                 # ggplot
        r"print\s*\(",                  # print
        r"function\s*\(",              # function keyword
        r"\$\w+",                      # list element access
        r"NA\b|NULL\b|TRUE\b|FALSE\b", # R literals
        r"mean\s*\(|sd\s*\(|lm\s*\(", # statistical functions
    ], 3),

    ("YAML", [
        r"^\s*---\s*$",                 # document start
        r"^\s*\w[\w\s]*:\s*$",         # mapping key (no value)
        r"^\s*-\s+\w+",               # list item
        r"^\s*\w+:\s+['\"]",          # key: "value"
        r"^\s*#\s+\w+",               # comment
    ], 2),

    ("JSON", [
        r'^\s*\{',                     # starts with {
        r'"[\w\s]+"\s*:\s*["\d\[\{]',  # "key": value
        r'"\s*:\s*(true|false|null)\b', # boolean/null values
        r'\[\s*\{',                    # array of objects
    ], 2),

]


# ──────────────────────────────────────────────────────────────────────────────
# LAYER 2 — PYGMENTS
# ──────────────────────────────────────────────────────────────────────────────

# Map Pygments lexer names → our canonical names
_PYGMENTS_NAME_MAP: dict[str, str] = {
    "python":       "Python",
    "python3":      "Python",
    "javascript":   "JavaScript",
    "js":           "JavaScript",
    "typescript":   "TypeScript",
    "ts":           "TypeScript",
    "java":         "Java",
    "csharp":       "C#",
    "c#":           "C#",
    "c++":          "C++",
    "cpp":          "C++",
    "c":            "C",
    "go":           "Go",
    "golang":       "Go",
    "rust":         "Rust",
    "swift":        "Swift",
    "kotlin":       "Kotlin",
    "php":          "PHP",
    "ruby":         "Ruby",
    "rb":           "Ruby",
    "sql":          "SQL",
    "html":         "HTML",
    "css":          "CSS",
    "bash":         "Shell",
    "sh":           "Shell",
    "shell":        "Shell",
    "zsh":          "Shell",
    "r":            "R",
    "yaml":         "YAML",
    "json":         "JSON",
    "text":         "unknown",
    "plain":        "unknown",
}


def _detect_with_pygments(code: str) -> DetectionResult:
    """
    Use Pygments' guess_lexer to detect the language.
    Returns confidence=0.0 if Pygments falls back to TextLexer.
    """
    try:
        from pygments.lexers import guess_lexer
        from pygments.util import ClassNotFound

        lexer    = guess_lexer(code)
        raw_name = lexer.name.lower().split()[0]   # "Python 3" → "python"
        language = _PYGMENTS_NAME_MAP.get(raw_name, lexer.name)

        if language == "unknown" or raw_name in ("text", "plain"):
            return DetectionResult("unknown", 0.0, "pygments")

        # Pygments doesn't provide a numeric confidence.
        # We assign 0.7 as a baseline — enough to beat "unknown"
        # but below a heuristic match (which gets ≥ 0.8).
        return DetectionResult(language, 0.70, "pygments")

    except Exception as exc:
        log.debug(f"Pygments detection error: {exc}")
        return DetectionResult("unknown", 0.0, "pygments")


# ──────────────────────────────────────────────────────────────────────────────
# LAYER 3 — FREQUENCY SCORER (final tiebreaker)
# ──────────────────────────────────────────────────────────────────────────────

def _frequency_score(code: str) -> DetectionResult:
    """
    Looks at character-level and token-level statistics to make a
    last-resort guess when heuristics and Pygments both fail.

    Not highly accurate on short snippets — returns low confidence
    (≤ 0.4) so the caller knows to treat this as a weak signal.
    """
    code_lower = code.lower()
    scores: dict[str, float] = {}

    # Indentation style — Python/YAML love 4-space indentation
    four_space = len(re.findall(r"^    \S", code, re.MULTILINE))
    if four_space > 2:
        scores["Python"] = scores.get("Python", 0) + 0.15

    # Curly brace density — C-family / JS / Java
    brace_ratio = (code.count("{") + code.count("}")) / max(len(code), 1)
    if brace_ratio > 0.02:
        for lang in ("JavaScript", "Java", "C++", "C#", "Go", "Rust"):
            scores[lang] = scores.get(lang, 0) + 0.1

    # Semicolon line endings — JS, Java, C, C++, C#, PHP
    semi_lines = len(re.findall(r";\s*$", code, re.MULTILINE))
    if semi_lines > 2:
        for lang in ("JavaScript", "Java", "C", "C++", "C#", "PHP"):
            scores[lang] = scores.get(lang, 0) + 0.12

    # Colon line endings (without braces) — Python
    colon_lines = len(re.findall(r":\s*$", code, re.MULTILINE))
    if colon_lines > 1 and brace_ratio < 0.01:
        scores["Python"] = scores.get("Python", 0) + 0.2

    # $ sign — PHP or Shell
    dollar_count = code.count("$")
    if dollar_count > 2:
        scores["PHP"]   = scores.get("PHP",   0) + 0.1
        scores["Shell"] = scores.get("Shell", 0) + 0.1

    # Arrow functions / fat arrow → JS/TS
    if "=>" in code:
        scores["JavaScript"] = scores.get("JavaScript", 0) + 0.15
        scores["TypeScript"] = scores.get("TypeScript", 0) + 0.15

    # print( — Python or many others
    if "print(" in code_lower:
        scores["Python"] = scores.get("Python", 0) + 0.1

    # Angle brackets with types → TypeScript / Java / C++
    generic_count = len(re.findall(r"<[A-Z]\w*>", code))
    if generic_count > 0:
        for lang in ("TypeScript", "Java", "C++", "C#"):
            scores[lang] = scores.get(lang, 0) + 0.1

    if not scores:
        return DetectionResult("unknown", 0.0, "frequency")

    best_lang  = max(scores, key=lambda k: scores[k])
    confidence = min(scores[best_lang], 0.4)    # cap at 0.4 for this layer
    return DetectionResult(best_lang, confidence, "frequency")


# ──────────────────────────────────────────────────────────────────────────────
# HEURISTIC ENGINE
# ──────────────────────────────────────────────────────────────────────────────

def _detect_with_heuristics(code: str) -> DetectionResult:
    """
    Run all heuristic rules against the code and return the best match.
    Confidence scales with the fraction of patterns that matched:
        all patterns matched  → 1.0
        minimum patterns met  → 0.8
        in between            → 0.8 – 1.0 linear
    """
    flags   = re.MULTILINE | re.IGNORECASE
    results: list[tuple[str, float]] = []

    for (language, patterns, required) in _HEURISTIC_RULES:
        matched = sum(1 for p in patterns if re.search(p, code, flags))
        if matched >= required:
            confidence = 0.8 + 0.2 * (
                (matched - required) / max(len(patterns) - required, 1)
            )
            results.append((language, min(confidence, 1.0)))

    if not results:
        return DetectionResult("unknown", 0.0, "heuristic")

    # Sort by confidence descending and take the winner
    results.sort(key=lambda x: x[1], reverse=True)
    best_lang, best_conf = results[0]
    return DetectionResult(best_lang, best_conf, "heuristic")


# ──────────────────────────────────────────────────────────────────────────────
# PUBLIC API
# ──────────────────────────────────────────────────────────────────────────────

def detect_language(code: str) -> str:
    """
    Main entry point — returns a canonical language name string.

    Detection pipeline:
      1. Heuristics  (confidence ≥ 0.8 → return immediately)
      2. Pygments    (confidence = 0.7 → return if heuristics failed)
      3. Frequency   (confidence ≤ 0.4 → last resort)
      4. "unknown"   if everything fails

    Examples:
        detect_language("def foo(x): return x * 2")  → "Python"
        detect_language("const x = () => 42;")       → "JavaScript"
        detect_language("SELECT * FROM users;")       → "SQL"
    """
    code = code.strip()

    if not code:
        return "unknown"

    # ── Layer 1: Heuristics ───────────────────────────────────────────────
    heuristic = _detect_with_heuristics(code)
    if heuristic.confidence >= 0.8:
        log.debug(
            f"Language detected by heuristic: {heuristic.language} "
            f"(conf={heuristic.confidence:.2f})"
        )
        return heuristic.language

    # ── Layer 2: Pygments ─────────────────────────────────────────────────
    pygments_result = _detect_with_pygments(code)
    if pygments_result.confidence >= 0.7:
        log.debug(
            f"Language detected by Pygments: {pygments_result.language} "
            f"(conf={pygments_result.confidence:.2f})"
        )
        return pygments_result.language

    # ── Layer 3: Frequency scorer ─────────────────────────────────────────
    freq = _frequency_score(code)
    if freq.confidence > 0.0:
        log.debug(
            f"Language detected by frequency: {freq.language} "
            f"(conf={freq.confidence:.2f})"
        )
        return freq.language

    log.debug("Language detection failed — returning 'unknown'")
    return "unknown"


def detect_language_detailed(code: str) -> DetectionResult:
    """
    Same as detect_language() but returns the full DetectionResult
    (language, confidence, method) — useful for debugging or logging.
    """
    code = code.strip()
    if not code:
        return DetectionResult("unknown", 0.0, "empty")

    h = _detect_with_heuristics(code)
    if h.confidence >= 0.8:
        return h

    p = _detect_with_pygments(code)
    if p.confidence >= 0.7:
        return p

    f = _frequency_score(code)
    if f.confidence > 0.0:
        return f

    return DetectionResult("unknown", 0.0, "unknown")