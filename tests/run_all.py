"""Saare test suites ek saath chalao.

    cd tests && python3 run_all.py

Koi bhi suite fail hua to exit code 1 (CI me kaam aata hai).
Har suite apni alag temp DB use karta hai — live `id_store_db.json` safe rehta hai.
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SUITES = ["test_flow.py", "test_admin_cmds.py", "test_v5.py", "test_v6.py",
          "test_v61.py", "test_v63.py"]
ok = "\033[92mPASS\033[0m"
bad = "\033[91mFAIL\033[0m"


def main():
    results = []
    for suite in SUITES:
        print(f"\n{'=' * 72}\n▶ {suite}\n{'=' * 72}")
        p = subprocess.run([sys.executable, suite], cwd=HERE,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        out = p.stdout
        print(out.rstrip())
        passed = p.returncode == 0 and "PASSED" in out
        results.append((suite, passed))
        print(f"{ok if passed else bad}  {suite}")

    print(f"\n{'=' * 72}\nSUMMARY")
    for suite, passed in results:
        print(f"  {'✅' if passed else '❌'}  {suite}")
    good = sum(1 for _, p in results if p)
    print(f"\n{good}/{len(results)} suites passed")
    return 0 if good == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
