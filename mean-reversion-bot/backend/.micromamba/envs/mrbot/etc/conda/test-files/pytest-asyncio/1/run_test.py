import sys
from subprocess import call

FAIL_UNDER = "91"
COV = ["coverage"]
RUN = ["run", "--source=pytest_asyncio", "--branch", "-m"]
PYTEST = ["pytest", "-vv", "--color=yes", "--tb=long"]
REPORT = ["report", "--show-missing", "--skip-covered", f"--fail-under={FAIL_UNDER}"]

SKIPS = [
    "unused_port_fixture",
    "unused_port_factory_fixture",
    "auto_mode_cmdline",
    "no_event_loop",
    "event_loop_after_fixture",
    "event_loop_before_fixture",
    # added on https://github.com/conda-forge/pytest-asyncio-feedstock/pull/57
    "async_fixture",
    "async_gen_fixture",
    "returns_false_for_unmarked_coroutine_item_in_strict_mode",
]

SKIP_OR = " or ".join(SKIPS)
K = ["-k", f"not ({SKIP_OR})"]


if __name__ == "__main__":
    sys.exit(
        # run the tests...
        call([*COV, *RUN, *PYTEST, *K])
        # ... maybe report coverage
        or call([*COV, *REPORT])
    )
