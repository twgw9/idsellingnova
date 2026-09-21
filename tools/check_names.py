"""Dev tool: package me koi undefined name to nahi reh gaya? (linker ke baad sab modules
ek-dusre ke names dekh paate hain, isliye check GLOBAL defined-set ke khilaaf hota hai.)"""
import ast, builtins, os, sys

PKG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bot")
BUILTINS = set(dir(builtins)) | {"__file__", "__name__", "__package__", "__dict__", "self", "cls"}

defined, used = set(), []


def bound_names(tree):
    out = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.arg):
            out.add(n.arg)
        elif isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del)):
            out.add(n.id)
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out.add(n.name)
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            for a in n.names:
                out.add((a.asname or a.name).split(".")[0])
        elif isinstance(n, ast.ExceptHandler) and n.name:
            out.add(n.name)
        elif isinstance(n, ast.Global):
            out.update(n.names)
        elif isinstance(n, (ast.comprehension,)):
            pass
    return out


files = sorted(f for f in os.listdir(PKG) if f.endswith(".py") and not f.startswith("_"))
for fn in files + ["__init__.py", "_link.py"]:
    path = os.path.join(PKG, fn)
    tree = ast.parse(open(path, encoding="utf-8").read())
    for node in tree.body:                      # top-level definitions
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            defined.add(node.name)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            for t in (node.targets if isinstance(node, ast.Assign) else [node.target]):
                for n in ast.walk(t):
                    if isinstance(n, ast.Name):
                        defined.add(n.id)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for a in node.names:
                defined.add((a.asname or a.name).split(".")[0])
    defined |= bound_names(tree)
    if fn == "_link.py":
        continue
    for node in ast.walk(tree):                 # names actually used
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            used.append((fn, node.lineno, node.id))

missing = [(f, l, n) for f, l, n in used if n not in defined and n not in BUILTINS]
if missing:
    print(f"❌ {len(missing)} name(s) defined nowhere in the package:")
    for f, l, n in missing[:50]:
        print(f"   {f}:{l}  {n}")
    sys.exit(1)
print(f"✅ {len(used)} name references, {len(defined)} definitions — sab theek hai")
