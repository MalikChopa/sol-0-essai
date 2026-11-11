"""Names (SPEC 8.4, EF-97)."""
import re

from rover.narrative import make_name


def test_ten_thousand_names_without_collision():
    taken: set = set()
    for i in range(10_000):
        n = make_name(20261111, "category", i // 7, taken)
        assert n not in taken
        taken.add(n)
    assert len(taken) == 10_000


def test_shape_ascii_syllables():
    pat = re.compile(r"^[TKVRSMNDLZ][aeiou](?:[tkvrsmndlz][aeiou])?[tkvrsmndlz][aeiou][nrsl]?$")
    taken: set = set()
    for i in range(500):
        n = make_name(7, "substance", i, taken)
        taken.add(n)
        assert pat.match(n) or re.match(r"^[TKVRSMNDLZ][aeiou][tkvrsmndlz][aeiou][nrsl]?$", n), n
        assert n.isascii() and n[0].isupper() and 3 <= len(n) <= 7


def test_deterministic_and_seed_dependent():
    a = [make_name(1, "life", s, set()) for s in range(30)]
    assert a == [make_name(1, "life", s, set()) for s in range(30)]
    assert a != [make_name(2, "life", s, set()) for s in range(30)]
    assert a != [make_name(1, "substance", s, set()) for s in range(30)]


def test_taken_names_are_skipped():
    first = make_name(5, "life", 3, set())
    assert make_name(5, "life", 3, {first}) != first
