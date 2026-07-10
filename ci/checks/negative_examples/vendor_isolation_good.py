"""Positive-example fixture for check (a) (ci/checks/vendor_isolation.py) — no vendor SDK name
anywhere, so `check_a` reports nothing regardless of which path this content is attributed to.
"""


class Retriever:
    def __init__(self, index) -> None:
        self.index = index
