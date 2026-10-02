"""Test bootstrap.

The shipped test classes use ``unittest`` assertion helpers
(``assertIsNotNone`` etc.) without inheriting from ``unittest.TestCase``.
The test files must not be modified, so expose those helpers on the
collected classes here.
"""

import unittest


def pytest_collection_modifyitems(items):
    patched = set()
    for item in items:
        cls = getattr(item, "cls", None)
        if cls is None or cls in patched:
            continue
        if not hasattr(cls, "assertIsNotNone"):
            for name in dir(unittest.TestCase):
                if name.startswith("assert") and not hasattr(cls, name):
                    setattr(cls, name, getattr(unittest.TestCase, name))
        patched.add(cls)
