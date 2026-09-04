#!/usr/bin/env python3
"""W5: short lightweight job, no network and no package install.

Tests claim X1 from the Confluence page: "lightweight jobs may see little
improvement or become slower". The job uses only the Python that every runner
image ships. It therefore measures runner overhead plus light CPU and file I/O.
Target duration is 60 to 90 seconds on a 4 vCPU GitHub-hosted runner.
"""
import compileall
import hashlib
import os
import pathlib
import shutil
import sys
import time

FILES = 2500
HASH_ROUNDS = 220_000
TREE = pathlib.Path(os.environ.get("RUNNER_TEMP", "/tmp")) / "w5tree"


def generate() -> float:
    t0 = time.monotonic()
    shutil.rmtree(TREE, ignore_errors=True)

    for i in range(FILES):
        d = TREE / f"pkg{i // 100:03d}"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"mod{i:05d}.py").write_text(
            f"CONST_{i} = {i}\n\n\ndef f{i}(x: int) -> int:\n"
            f"    return x * CONST_{i} + {i % 7}\n"
        )

    return time.monotonic() - t0


def compile_tree() -> float:
    t0 = time.monotonic()

    if not compileall.compile_dir(str(TREE), quiet=2, workers=0):
        sys.exit("compileall reported a failure")

    return time.monotonic() - t0


def cpu_loop() -> float:
    t0 = time.monotonic()

    h = hashlib.sha256(b"seed")
    for _ in range(HASH_ROUNDS):
        h = hashlib.sha256(h.digest())

    if len(h.hexdigest()) != 64:
        sys.exit("hash loop produced an unexpected digest")

    return time.monotonic() - t0


if __name__ == "__main__":
    gen = generate()
    comp = compile_tree()
    cpu = cpu_loop()
    shutil.rmtree(TREE, ignore_errors=True)

    print(f"w5_generate_s={gen:.3f}")
    print(f"w5_compile_s={comp:.3f}")
    print(f"w5_cpu_s={cpu:.3f}")
    print(f"w5_total_s={gen + comp + cpu:.3f}")
    print(f"w5_files={FILES}")
