"""
dabih.core.symmetry
~~~~~~~~~~~~~~~~~~~
Permutation group machinery for symmetry-based coverage compression.

A symmetry on a BinSpace is a permutation of coverpoint indices that
leaves the verification semantics invariant.  Applying a permutation g
to a cross-coverage bin tuple (v0, v1, ..., vn) yields a new tuple whose
component at position i is drawn from position g[i] of the original:

    g(v)[i] = v[g.perm[i]]

The SymmetryGroup is constructed by BFS closure from a set of generators.
Orbit computation uses only the generators (plus inverses) rather than
enumerating the full group — keeping the algorithm efficient even when
the group is large (e.g. S_n for large n).
"""

from __future__ import annotations

from collections import deque
from typing import Sequence


# ── Permutation ──────────────────────────────────────────────────────────────

class Permutation:
    """
    A bijection on {0, 1, ..., n-1} used to express design symmetries.

    Convention
    ----------
    perm[i] = j  means  "position i draws its value from original position j"

    So applying perm to tuple t gives:
        result[i] = t[perm[i]]
    """

    def __init__(self, perm: Sequence[int]):
        self._perm = tuple(perm)
        n = len(self._perm)
        if sorted(self._perm) != list(range(n)):
            raise ValueError(
                f"Not a valid permutation of {{0..{n - 1}}}: {list(perm)}"
            )

    # ── Factories ────────────────────────────────────────────────────────────

    @classmethod
    def identity(cls, n: int) -> Permutation:
        return cls(range(n))

    @classmethod
    def transposition(cls, n: int, i: int, j: int) -> Permutation:
        """Swap positions i and j, leave all others fixed."""
        perm = list(range(n))
        perm[i], perm[j] = perm[j], perm[i]
        return cls(perm)

    @classmethod
    def cycle(cls, n: int, indices: Sequence[int]) -> Permutation:
        """
        Cyclic permutation: indices[0] → indices[1] → ... → indices[-1] → indices[0].
        All positions not in `indices` are fixed.
        """
        perm = list(range(n))
        k = len(indices)
        for step in range(k):
            perm[indices[step]] = indices[(step + 1) % k]
        return cls(perm)

    @classmethod
    def full_cycle(cls, n: int) -> Permutation:
        """The n-cycle (0 → 1 → 2 → ... → n-1 → 0)."""
        return cls.cycle(n, list(range(n)))

    # ── Core operations ──────────────────────────────────────────────────────

    @property
    def n(self) -> int:
        return len(self._perm)

    def apply(self, t: tuple) -> tuple:
        """Apply this permutation to a bin tuple."""
        if len(t) != self.n:
            raise ValueError(
                f"Tuple length {len(t)} != permutation degree {self.n}"
            )
        return tuple(t[self._perm[i]] for i in range(self.n))

    def compose(self, other: Permutation) -> Permutation:
        """
        Return self ∘ other  (apply other first, then self).
        (self ∘ other)(t) = self(other(t))
        """
        if self.n != other.n:
            raise ValueError("Permutation degree mismatch in compose")
        return Permutation(
            [self._perm[other._perm[i]] for i in range(self.n)]
        )

    def inverse(self) -> Permutation:
        inv = [0] * self.n
        for i, j in enumerate(self._perm):
            inv[j] = i
        return Permutation(inv)

    # ── Inspection ───────────────────────────────────────────────────────────

    def as_tuple(self) -> tuple:
        return self._perm

    def order(self) -> int:
        """The smallest k such that self^k = identity."""
        current = self
        identity = Permutation.identity(self.n)
        for k in range(1, self.n + 1):
            if current == identity:
                return k
            current = current.compose(self)
        return -1  # should never reach here for a valid permutation

    def cycle_notation(self) -> str:
        """Express permutation in standard cycle notation."""
        visited = [False] * self.n
        cycles = []
        for start in range(self.n):
            if visited[start] or self._perm[start] == start:
                visited[start] = True
                continue
            cycle = []
            i = start
            while not visited[i]:
                visited[i] = True
                cycle.append(str(i))
                i = self._perm[i]
            cycles.append(f"({'→'.join(cycle)})")
        return " ".join(cycles) if cycles else "(identity)"

    def __eq__(self, other) -> bool:
        return isinstance(other, Permutation) and self._perm == other._perm

    def __hash__(self) -> int:
        return hash(self._perm)

    def __repr__(self) -> str:
        return f"Permutation({list(self._perm)})"


# ── SymmetryGroup ────────────────────────────────────────────────────────────

class SymmetryGroup:
    """
    A finite permutation group built by BFS closure over a generator set.

    Usage
    -----
        g = SymmetryGroup(degree=4)
        g.add_generator(Permutation.transposition(4, 0, 1))
        g.add_generator(Permutation.full_cycle(4))
        print(g.order())   # → 24  (S_4)
        elems = g.elements()
    """

    def __init__(self, degree: int):
        self.degree = degree
        self._generators: list[Permutation] = []
        self._elements: list[Permutation] | None = None

    # ── Construction ─────────────────────────────────────────────────────────

    def add_generator(self, perm: Permutation) -> SymmetryGroup:
        if perm.n != self.degree:
            raise ValueError(
                f"Generator degree {perm.n} != group degree {self.degree}"
            )
        self._generators.append(perm)
        self._elements = None  # invalidate cache
        return self

    @property
    def generators(self) -> list[Permutation]:
        return list(self._generators)

    # ── Group enumeration (BFS closure) ───────────────────────────────────────

    def elements(self) -> list[Permutation]:
        """
        Enumerate all group elements via BFS closure.

        For large groups (|G| > ~100k) consider using generators_and_inverses()
        directly in orbit computation instead of enumerating all elements.
        """
        if self._elements is not None:
            return self._elements

        identity = Permutation.identity(self.degree)
        seen: dict[tuple, Permutation] = {identity.as_tuple(): identity}
        queue: deque[Permutation] = deque([identity])

        for gen in self.generators_and_inverses():
            # Seed with generators first so the BFS frontier is primed
            key = gen.as_tuple()
            if key not in seen:
                seen[key] = gen
                queue.append(gen)

        while queue:
            current = queue.popleft()
            for gen in self.generators_and_inverses():
                product = current.compose(gen)
                key = product.as_tuple()
                if key not in seen:
                    seen[key] = product
                    queue.append(product)

        self._elements = list(seen.values())
        return self._elements

    def generators_and_inverses(self) -> list[Permutation]:
        """Generators union their inverses — sufficient for orbit BFS."""
        result = list(self._generators)
        for g in self._generators:
            inv = g.inverse()
            if inv not in result:
                result.append(inv)
        return result

    # ── Properties ────────────────────────────────────────────────────────────

    def order(self) -> int:
        return len(self.elements())

    def is_trivial(self) -> bool:
        return len(self._generators) == 0

    def __repr__(self) -> str:
        return (
            f"SymmetryGroup(degree={self.degree}, "
            f"generators={len(self._generators)}, "
            f"order={self.order()})"
        )
