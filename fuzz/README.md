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

Seed inputs come only from the synthetic test builders in `tests/`, and every run adds
them. A crash is saved as a `crash-*` file, which git ignores. To replay one:

```sh
uv run --with atheris python fuzz/fuzz_container.py crash-<id>
```

`tests/test_fuzz_harness.py` runs the same per-input function on the seeds and on seeded
random bytes without atheris, so the harness is checked on every platform.

## FM27 inputs

Normal fuzzing includes a fictional FM27 seed that reaches the raw span parser. FM27 reads
stay strict, and the harness retains its 16 MiB total declared output cap and 4 MiB per-frame
cap. The raw span result exposes fixture and rules collections; it is not a table.
