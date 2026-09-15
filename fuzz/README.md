# Fuzzing

`fuzz_container.py` feeds random bytes to fmsave's container, metadata and record readers
with [atheris](https://github.com/google/atheris). fmsave errors are expected on damaged
input; any other exception is a crash.

atheris runs on Linux x86_64 only: its wheels are manylinux builds for CPython 3.12 to 3.14.

From the repository root:

```sh
uv run --with atheris python fuzz/fuzz_container.py
```

libFuzzer options and corpus folders go after the script name. New inputs are written to
the first corpus folder, so keep one outside the repository:

```sh
mkdir -p ~/fmsave-fuzz-corpus
uv run --with atheris python fuzz/fuzz_container.py ~/fmsave-fuzz-corpus -max_total_time=600
```

Seed inputs come only from the test fixture builders in `tests/fixtures/`, and every run adds
them. A crash is saved as a `crash-*` file, which git ignores. To replay one:

```sh
uv run --with atheris python fuzz/fuzz_container.py crash-<id>
```

`tests/test_fuzz_harness.py` runs the same per-input function on the seeds and on seeded
random bytes without atheris, so the harness is checked on every platform.
