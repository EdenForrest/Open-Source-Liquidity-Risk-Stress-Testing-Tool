"""
Build the native reverse-stress search core into an importable extension module.

Usage (from the repo root or anywhere)::

    python native/reverse_stress/build.py

It locates pybind11's CMake package, configures + builds with CMake, and copies
the resulting ``reverse_stress_core.*`` extension next to the Python shim
(``liquidity_risk_tool/engines/``) so ``import reverse_stress_core`` works without
any install step or PYTHONPATH change.

This is intentionally a plain script, not a packaging integration: the native
core is a *pure optimisation* — the engine falls back to the existing Python
search whenever the module is absent — so it must never be a hard build/install
dependency of the project. CI / fresh clones without a C++ toolchain just run the
Python path.

On Windows the MSVC environment must be active. The script auto-detects VS 2022
Build Tools via ``vcvars64.bat`` and re-invokes itself inside that shell if cl.exe
is not already on PATH, so a plain ``python build.py`` from any prompt works.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BUILD_DIR = HERE / "build"
# Install target: alongside the engines so the shim's plain `import` finds it.
DEST_DIR = HERE.parent.parent / "liquidity_risk_tool" / "engines"

VCVARS_CANDIDATES = [
    r"C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat",
    r"C:\Program Files\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat",
    r"C:\Program Files (x86)\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat",
    r"C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat",
]


def _have_msvc() -> bool:
    return shutil.which("cl") is not None


def _find_vcvars() -> str | None:
    for c in VCVARS_CANDIDATES:
        if Path(c).exists():
            return c
    return None


def _reexec_in_vcvars() -> int:
    """On Windows without cl.exe on PATH, re-run this script inside a vcvars64
    shell so MSVC is available. Returns the child's exit code."""
    vcvars = _find_vcvars()
    if not vcvars:
        print(
            "ERROR: cl.exe not on PATH and no vcvars64.bat found. Install VS 2022 "
            "Build Tools (MSVC) or run this from an 'x64 Native Tools' prompt.",
            file=sys.stderr,
        )
        return 1
    # call vcvars, then re-run python on this script with a sentinel so we don't loop.
    cmd = f'call "{vcvars}" >nul && "{sys.executable}" "{__file__}" --in-vcvars'
    return subprocess.call(["cmd", "/c", cmd])


def _pybind11_cmakedir() -> str:
    out = subprocess.check_output(
        [sys.executable, "-m", "pybind11", "--cmakedir"], text=True
    ).strip()
    # Newer pybind11 wraps the path in double quotes; strip them so the value we
    # hand CMake is a bare path (literal quotes break find_package on Windows).
    return out.strip('"')


def build() -> int:
    BUILD_DIR.mkdir(exist_ok=True)
    cmake = shutil.which("cmake")
    if not cmake:
        print("ERROR: cmake not found on PATH.", file=sys.stderr)
        return 1

    pybind_dir = _pybind11_cmakedir()
    configure = [
        cmake, "-S", str(HERE), "-B", str(BUILD_DIR),
        f"-Dpybind11_DIR={pybind_dir}",
        f"-DPYTHON_EXECUTABLE={sys.executable}",
    ]
    if os.name == "nt":
        # Ninja is simplest under an active MSVC env; fall back to NMake if absent.
        gen = "Ninja" if shutil.which("ninja") else "NMake Makefiles"
        configure += ["-G", gen, "-DCMAKE_BUILD_TYPE=Release"]
    else:
        configure += ["-DCMAKE_BUILD_TYPE=Release"]

    print("·", " ".join(configure))
    rc = subprocess.call(configure)
    if rc != 0:
        return rc

    rc = subprocess.call([cmake, "--build", str(BUILD_DIR), "--config", "Release"])
    if rc != 0:
        return rc

    # Copy the built extension (.pyd / .so) next to the engines.
    built = list(BUILD_DIR.rglob("reverse_stress_core*.pyd")) + list(
        BUILD_DIR.rglob("reverse_stress_core*.so")
    )
    if not built:
        print("ERROR: build succeeded but no extension module was produced.", file=sys.stderr)
        return 1
    DEST_DIR.mkdir(parents=True, exist_ok=True)
    for f in built:
        dest = DEST_DIR / f.name
        shutil.copy2(f, dest)
        print(f"· installed {dest}")
    return 0


def main() -> int:
    args = set(sys.argv[1:])
    if os.name == "nt" and not _have_msvc() and "--in-vcvars" not in args:
        return _reexec_in_vcvars()
    return build()


if __name__ == "__main__":
    raise SystemExit(main())
