"""Sibling test for app/mcp_verify_client.py (CONVENTIONS.md §0.7/§12 check (g)). Covers only
`main()`'s CLI-argument parsing (query positional, `--k` override/default) -- `_run()` itself
spawns a real `python -m app.serve` child process over stdio, well outside what a unit test should
touch. `asyncio.run` is monkeypatched to a fake that inspects the not-yet-started `_run(...)`
coroutine's bound arguments (via `cr_frame.f_locals`) and closes it, instead of ever executing it.
"""

import sys

import app.mcp_verify_client as mvc


def test_main_parses_query_and_k(monkeypatch):
    captured: dict = {}

    def fake_run(coro):
        captured["query"] = coro.cr_frame.f_locals["query"]
        captured["k"] = coro.cr_frame.f_locals["k"]
        coro.close()

    monkeypatch.setattr(mvc.asyncio, "run", fake_run)
    monkeypatch.setattr(sys, "argv", ["mcp_verify_client", "what is DML", "--k", "3"])

    mvc.main()

    assert captured["query"] == "what is DML"
    assert captured["k"] == 3


def test_main_defaults_k_to_10_and_query_to_the_builtin_default(monkeypatch):
    captured: dict = {}

    def fake_run(coro):
        captured["query"] = coro.cr_frame.f_locals["query"]
        captured["k"] = coro.cr_frame.f_locals["k"]
        coro.close()

    monkeypatch.setattr(mvc.asyncio, "run", fake_run)
    monkeypatch.setattr(sys, "argv", ["mcp_verify_client"])

    mvc.main()

    assert captured["k"] == 10
    assert captured["query"] == (
        "how long does DML with dummies take to compute for one dataset"
    )
