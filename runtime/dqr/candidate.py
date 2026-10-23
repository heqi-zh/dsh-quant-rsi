"""A deliberately small Python subset, not a general-purpose Python sandbox."""
import ast
import builtins
import json
from pathlib import Path
import subprocess
import sys
import os
import select
import time

CALLS = {"abs", "min", "max", "sum", "len", "range", "sorted", "float", "int", "round"}
ALLOWED = {
    "Module", "FunctionDef", "arguments", "arg", "Return", "Assign", "AugAssign", "If", "For",
    "Break", "Continue", "Pass", "Expr", "Name", "Load", "Store", "Constant", "Subscript", "Slice",
    "List", "Tuple", "Dict", "ListComp", "DictComp", "GeneratorExp", "comprehension", "IfExp",
    "BinOp", "UnaryOp", "BoolOp", "Compare", "Call", "keyword",
    "Add", "Sub", "Mult", "Div", "FloorDiv", "Mod", "USub", "UAdd", "Not", "And", "Or",
    "Eq", "NotEq", "Lt", "LtE", "Gt", "GtE", "Is", "IsNot", "In", "NotIn"
}


def validate(code):
    if len(code.encode()) > 32000:
        raise ValueError("candidate exceeds 32 KB")
    tree = ast.parse(code)
    if len(tree.body) != 1 or not isinstance(tree.body[0], ast.FunctionDef) or tree.body[0].name != "strategy":
        raise ValueError("candidate must contain only def strategy(history, portfolio)")
    function = tree.body[0]
    if ([arg.arg for arg in function.args.args] != ["history", "portfolio"] or function.decorator_list
            or function.args.defaults or function.args.vararg or function.args.kwarg
            or function.args.kwonlyargs or function.args.posonlyargs):
        raise ValueError("unsupported strategy signature")
    for node in ast.walk(tree):
        if type(node).__name__ not in ALLOWED:
            raise ValueError("unsupported Python syntax: " + type(node).__name__)
        if isinstance(node, ast.Name) and node.id.startswith("_"):
            raise ValueError("private names are forbidden")
        if isinstance(node, ast.FunctionDef) and node is not function:
            raise ValueError("nested functions are forbidden")
        if isinstance(node, ast.Call) and (not isinstance(node.func, ast.Name) or node.func.id not in CALLS):
            raise ValueError("only pure builtin calls are supported")
    return tree


class Candidate:
    def __init__(self, code, timeout=10):
        validate(code)
        self.process = subprocess.Popen([sys.executable, "-I", "-S", str(Path(__file__).resolve()), "worker"],
                                        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.deadline = time.monotonic() + timeout
        self.process.stdin.write(json.dumps({"code": code}) + "\n")
        self.process.stdin.flush()

    def decide(self, history, portfolio):
        self.process.stdin.write(json.dumps({"history": history, "portfolio": portfolio}) + "\n")
        self.process.stdin.flush()
        buffer = b""
        while not buffer.endswith(b"\n"):
            remaining = self.deadline - time.monotonic()
            if remaining <= 0 or not select.select([self.process.stdout], [], [], max(0, remaining))[0]:
                raise ValueError("candidate timeout")
            chunk = os.read(self.process.stdout.fileno(), 4096)
            if not chunk:
                self.process.wait(timeout=1)
                raise ValueError("candidate exited without a result: " + self.process.stderr.read()[-1500:])
            buffer += chunk
            if len(buffer) > 32768:
                raise ValueError("candidate output exceeds 32 KB")
        return json.loads(buffer)

    def close(self):
        if self.process.poll() is None:
            self.process.kill()
        self.process.communicate()


def worker():
    # Limit runaway memory/CPU on Unix. This does not claim OS-level sandboxing.
    import resource
    # Darwin does not reliably support lowering RLIMIT_AS for Python processes.
    # Linux gets an address-space cap; macOS uses the CPU/wall-clock caps only.
    if sys.platform == "linux":
        resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_CPU, (10, 10))
    payload = json.loads(sys.stdin.readline())
    tree = validate(payload["code"])
    scope = {"__builtins__": {name: getattr(builtins, name) for name in CALLS}}
    exec(compile(tree, "candidate.py", "exec"), scope)
    for line in sys.stdin:
        item = json.loads(line)
        result = scope["strategy"](item["history"], item["portfolio"])
        print(json.dumps(result, allow_nan=False), flush=True)


if __name__ == "__main__":
    worker()
