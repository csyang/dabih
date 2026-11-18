"""
dabih.core.symbolic
~~~~~~~~~~~~~~~~~~~
Symbolic orbit engine: analytic orbit counting and canonical-form computation
without enumerating the full cross-coverage bin space.

Three methods, applied in priority order
-----------------------------------------

1. Pólya closed-form  (method tag: "polya")
   Applies when the group is the full symmetric group Sₙ, either acting
   directly on n coverpoints or acting as Sₙ on n *blocks* of s signals.

   Orbit count = C(n + K − 1, n)

   where K = number of distinct per-block value combos = Π k_j over all
   signals j.  Requires only integer arithmetic — O(1), no enumeration.

   For Sₙ, canonical form is the lexicographically sorted block-value tuple,
   and representatives are all non-decreasing sequences of K values of length n
   (enumerable via combinations_with_replacement, count = C(n+K−1,n)).

2. Burnside's lemma  (method tag: "burnside")
   Applies when the group order is ≤ BURNSIDE_LIMIT and the group is not Sₙ
   (e.g. partial symmetry groups, cyclic groups Zₙ, dihedral groups).

   Orbit count = (1/|G|) Σ_{g∈G} K^{c_block(g)}

   where c_block(g) = number of cycles of g acting on block positions
   (for block groups) or on individual coverpoint positions (for direct groups).
   Requires full group enumeration — O(|G| × n).

3. Möbius inversion  (method tag: "mobius")
   Applies when |G| > BURNSIDE_LIMIT.  Uses the Möbius function on the
   subgroup lattice to compute orbit counts without full enumeration.
   Currently implemented as a documented boundary condition — the cases
   encountered in hardware verification (generate-for arrays producing Sₙ
   or small partial-symmetry subgroups) are covered by methods 1 and 2.
   Raises SymbolicLimitError if reached.

Key enablers vs the BFS engine (Ideas A–C)
-------------------------------------------
- orbit_count()     : O(1) for Pólya, O(|G|) for Burnside — no bin enumeration
- representatives() : C(n+K−1,n) entries via combinations_with_replacement —
                      manageable even for n=8, K=8 (6,435 entries)
- canonical(bt)     : sorted block-tuple — O(n log n)
- orbit_of(bt)      : permutations of block-values — O(orbit_size)

This unlocks the 8-lane × 2-signal case (16M bins → 6,435 orbits) that
exhausted BFS enumeration memory in the Ideas A–C prototype.
"""

from __future__ import annotations

import math
from fractions import Fraction
from functools import reduce
from itertools import combinations_with_replacement, permutations, product as iproduct
from typing import Sequence

from .bin_space import BinSpace, BinTuple
from .coverpoint import Coverpoint
from .symmetry import Permutation, SymmetryGroup


# ── Constants ─────────────────────────────────────────────────────────────────

BURNSIDE_LIMIT = 500_000   # max |G| for Burnside enumeration


# ── Exceptions ────────────────────────────────────────────────────────────────

class SymbolicLimitError(Exception):
    """
    Raised when the group order exceeds the Burnside limit and Möbius
    inversion has not yet been implemented for this group type.
    """


# ── SymmetryProfile ───────────────────────────────────────────────────────────

class SymmetryProfile:
    """
    Describes the structure of the symmetry acting on a BinSpace,
    including whether it is Sₙ (full symmetric) and the block layout.

    Populated by BinSpaceBuilder via `_symbolic_hint` on the BinSpace,
    or derived automatically from group properties.

    Attributes
    ----------
    n_blocks      : Number of symmetric instances (lanes, stages, etc.)
    block_size    : Coverpoints per instance (number of signals)
    k_per_position: Bin count for each coverpoint.  Length = n_blocks × block_size.
    k_per_signal  : Bin count per signal (length = block_size).
                    All instances must have identical per-signal bin counts.
    K             : Per-block combo count = Π k_per_signal.
    is_full_sn    : True if the group is exactly Sₙ on the n_blocks positions.
    """

    def __init__(
        self,
        n_blocks   : int,
        block_size : int,
        k_per_signal: list[int],
        is_full_sn : bool,
    ):
        self.n_blocks     = n_blocks
        self.block_size   = block_size
        self.k_per_signal = k_per_signal
        self.K            = math.prod(k_per_signal) if k_per_signal else 1
        self.is_full_sn   = is_full_sn

    @property
    def degree(self) -> int:
        return self.n_blocks * self.block_size

    def total_bins(self) -> int:
        return self.K ** self.n_blocks

    def __repr__(self) -> str:
        tag = "Sₙ" if self.is_full_sn else "subgroup"
        return (
            f"SymmetryProfile({tag}, n={self.n_blocks}, "
            f"block_size={self.block_size}, K={self.K})"
        )


# ── Block-permutation validity check ─────────────────────────────────────────

def _is_block_permutation(perm: Permutation, block_size: int) -> bool:
    """
    Return True iff `perm` is a genuine block permutation with the given
    block_size — i.e. every block of `block_size` consecutive positions maps
    entirely into another block of the same size.

    Used to avoid false-positive Sₙ detection: a Z2 group of order 2 has
    the same order as S2 (= 2!), but its generators may not permute
    whole blocks.
    """
    n_blocks = perm.n // block_size
    if perm.n % block_size != 0:
        return False
    perm_list = perm.as_tuple()
    for i in range(n_blocks):
        # Which block do the positions of block i land in?
        target_blocks = {
            perm_list[i * block_size + k] // block_size
            for k in range(block_size)
        }
        if len(target_blocks) != 1:
            return False   # positions of this block scatter across blocks
    return True

def _cycle_count_direct(perm: Permutation) -> int:
    """Number of cycles in a permutation acting on individual positions."""
    n = perm.n
    perm_list = perm.as_tuple()
    visited = [False] * n
    count = 0
    for start in range(n):
        if not visited[start]:
            count += 1
            i = start
            while not visited[i]:
                visited[i] = True
                i = perm_list[i]
    return count


def _cycle_count_blocks(perm: Permutation, block_size: int) -> int:
    """
    Number of cycles of a block permutation acting on BLOCK positions.

    For a permutation of degree n×s that acts by permuting whole blocks
    of size s, the cycle count on blocks is derived from the induced
    permutation on {0, 1, ..., n−1}.

    Assumes the permutation actually has block structure (each block of s
    consecutive coverpoints moves together as a unit).
    """
    n = perm.n // block_size
    # Extract the induced permutation on block indices
    perm_list = perm.as_tuple()
    block_perm = [perm_list[i * block_size] // block_size for i in range(n)]
    # Count cycles of this n-element permutation
    visited = [False] * n
    count = 0
    for start in range(n):
        if not visited[start]:
            count += 1
            i = start
            while not visited[i]:
                visited[i] = True
                i = block_perm[i]
    return count


# ── SymbolicOrbitEngine ───────────────────────────────────────────────────────

class SymbolicOrbitEngine:
    """
    Analytic orbit computation for a BinSpace.

    Works without enumerating the full cross-coverage bin space — enabling
    spaces previously infeasible for BFS (e.g. 8 lanes × 2 signals × 4 bins
    = 16M bins compresses to 6,435 orbits, computable in microseconds).

    Usage
    -----
        engine = SymbolicOrbitEngine(bin_space)
        print(engine.count_orbits())        # → int, analytic
        print(engine.method_used())         # → "polya" | "burnside" | ...
        print(engine.compression_ratio())   # → float
        reps = engine.representatives()     # → list[BinTuple] (enumerable)
        rep = engine.canonical(some_bin)    # → BinTuple

    Large-space workflow (replaces BFS ExpansionEngine)
    -------------------------------------------------------
        engine = SymbolicOrbitEngine(bin_space)
        covered = set()
        for hit_label in simulation_hits:
            bt = label_to_bin_tuple(hit_label)
            covered.add(engine.canonical(bt))
        pct = 100 * len(covered) / engine.count_orbits()
        holes = [r for r in engine.representatives() if r not in covered]
    """

    def __init__(self, bin_space: BinSpace):
        self.bin_space = bin_space
        self._profile  = self._build_profile()
        self._method   : str | None = None
        self._cached_count: int | None = None

    # ── Profile construction ──────────────────────────────────────────────────

    def _build_profile(self) -> SymmetryProfile:
        """
        Determine the symmetry profile from the BinSpace.

        Priority order:
        1. _symmetry_declarations set by the ergonomic API (OQ-05) — exact
        2. _symbolic_hint set by BinSpaceBuilder bridge — exact
        3. Heuristic detection from group order — approximate
        """
        bs = self.bin_space

        # ── Priority 1: structured declarations (most reliable) ───────────────
        decls = getattr(bs, "_symmetry_declarations", [])
        if decls:
            return self._profile_from_declarations(decls, bs)

        # ── Priority 2: bridge hint ───────────────────────────────────────────
        hint: dict = getattr(bs, "_symbolic_hint", {})
        if hint.get("type") == "block_symmetric":
            n         = hint["n_blocks"]
            s         = hint["block_size"]
            k_signals = hint["k_per_signal"]
            is_sn     = hint.get("is_full_sn", True)
            return SymmetryProfile(n, s, k_signals, is_sn)

        # ── Priority 3: heuristic from group order ────────────────────────────
        return self._profile_from_heuristic(bs)

    def _profile_from_declarations(
        self, decls: list[dict], bs
    ) -> SymmetryProfile:
        """
        Build SymmetryProfile from structured _symmetry_declarations.

        When multiple declarations exist (e.g. pairwise + instance), we use
        the first instance or cyclic declaration that covers the full coverpoint
        set.  For mixed declarations (partial symmetry), we fall back to the
        heuristic so Burnside handles it correctly.
        """
        cps = bs._coverpoints
        n_cps = len(cps)

        # Find the first full-symmetric declaration
        for decl in decls:
            dtype = decl.get("type")
            s     = decl.get("block_size", 1)
            if dtype == "instance":
                indices = decl["instance_indices"]
                n       = len(indices)
                # Full coverage: all instances declared symmetric
                if n * s == n_cps:
                    k_signals = [cps[j].bin_count() for j in range(s)]
                    return SymmetryProfile(n, s, k_signals, is_full_sn=True)
                # Partial: some instances not covered → Burnside handles it
                k_uniform = cps[0].bin_count() if cps else 1
                return SymmetryProfile(
                    n_blocks     = n_cps,
                    block_size   = 1,
                    k_per_signal = [k_uniform],
                    is_full_sn   = False,
                )
            elif dtype == "cyclic":
                # Zₙ is not Sₙ → Burnside
                k_uniform = cps[0].bin_count() if cps else 1
                return SymmetryProfile(
                    n_blocks     = n_cps,
                    block_size   = 1,
                    k_per_signal = [k_uniform],
                    is_full_sn   = False,
                )
            elif dtype == "pairwise":
                # Z2×Z2×... is not Sₙ → Burnside
                k_uniform = cps[0].bin_count() if cps else 1
                return SymmetryProfile(
                    n_blocks     = n_cps,
                    block_size   = 1,
                    k_per_signal = [k_uniform],
                    is_full_sn   = False,
                )

        # No usable declaration found — fall back to heuristic
        return self._profile_from_heuristic(bs)

    def _profile_from_heuristic(self, bs) -> SymmetryProfile:
        """Original heuristic: infer profile from group order and structure."""
        group  = bs._get_group()
        degree = group.degree
        cps    = bs._coverpoints

        if not cps:
            return SymmetryProfile(0, 1, [], False)

        k_uniform = cps[0].bin_count() if cps else 1
        all_same_k = all(cp.bin_count() == k_uniform for cp in cps)

        if group.is_trivial():
            return SymmetryProfile(
                n_blocks     = degree,
                block_size   = 1,
                k_per_signal = [k_uniform],
                is_full_sn   = False,
            )

        if all_same_k and group.order() == math.factorial(degree):
            return SymmetryProfile(
                n_blocks     = degree,
                block_size   = 1,
                k_per_signal = [k_uniform],
                is_full_sn   = True,
            )

        for s in range(1, degree + 1):
            if degree % s == 0:
                n = degree // s
                if n >= 2 and group.order() == math.factorial(n):
                    all_block = all(
                        _is_block_permutation(g, s)
                        for g in group.generators
                    )
                    if all_block:
                        k_signals = [cps[j].bin_count() for j in range(s)]
                        return SymmetryProfile(
                            n_blocks     = n,
                            block_size   = s,
                            k_per_signal = k_signals,
                            is_full_sn   = True,
                        )

        k_uniform = cps[0].bin_count() if cps else 1
        return SymmetryProfile(
            n_blocks     = degree,
            block_size   = 1,
            k_per_signal = [k_uniform],
            is_full_sn   = False,
        )

    # ── Method selection ──────────────────────────────────────────────────────

    def _select_method(self) -> str:
        p = self._profile
        group = self.bin_space._get_group()
        if p.is_full_sn:
            return "polya"
        if group.order() <= BURNSIDE_LIMIT:
            return "burnside"
        return "mobius"

    def method_used(self) -> str:
        """Return the method tag that will be (or was) used for this BinSpace."""
        if self._method is None:
            self._method = self._select_method()
        return self._method

    # ── Orbit count ───────────────────────────────────────────────────────────

    def count_orbits(self) -> int:
        """
        Analytically compute the number of orbits (equivalence classes).

        Does not enumerate the bin space.  For Sₙ this is O(1); for
        Burnside it is O(|G|).

        Returns
        -------
        int — exact orbit count.

        Raises
        ------
        SymbolicLimitError
            If the group order exceeds BURNSIDE_LIMIT and the Möbius
            fallback is required but not yet implemented.
        """
        if self._cached_count is not None:
            return self._cached_count

        method = self.method_used()

        if method == "polya":
            count = self._polya()
        elif method == "burnside":
            count = self._burnside()
        else:
            count = self._mobius()

        self._cached_count = count
        return count

    def _polya(self) -> int:
        """
        Pólya closed-form for Sₙ: C(n + K − 1, n).

        Correctness proof: orbits of Sₙ on K^n correspond bijectively to
        multisets of size n drawn from K elements.  The multiset coefficient
        C(n+K−1, n) counts exactly these.
        """
        p = self._profile
        return math.comb(p.n_blocks + p.K - 1, p.n_blocks)

    def _burnside(self) -> int:
        """
        Burnside's lemma: |orbits| = (1/|G|) Σ_{g∈G} K^{c_block(g)}.

        c_block(g) = number of cycles of g on BLOCK positions.
        """
        p     = self._profile
        group = self.bin_space._get_group()
        s     = p.block_size
        K     = p.K

        total = 0
        for g in group.elements():
            if s == 1:
                c = _cycle_count_direct(g)
            else:
                c = _cycle_count_blocks(g, s)
            total += K ** c

        # total is divisible by |G| exactly (Burnside guarantees this)
        return total // group.order()

    def _mobius(self) -> int:
        """
        Möbius inversion on the subgroup lattice.

        Currently a documented boundary condition.  In practice, hardware
        verification designs produce either Sₙ groups (Pólya) or small
        partial-symmetry subgroups (Burnside).  If you reach this method,
        the group has order > {limit:,} — please file an issue describing
        the design structure so this case can be prioritised.
        """.format(limit=BURNSIDE_LIMIT)
        raise SymbolicLimitError(
            f"Group order {self.bin_space._get_group().order():,} exceeds "
            f"the Burnside limit ({BURNSIDE_LIMIT:,}).  "
            f"Möbius inversion is not yet implemented.  "
            f"Workaround: use BFS ExpansionEngine for Idea C (which does not "
            f"need the orbit count), or decompose the group into smaller subgroups."
        )

    # ── Compression metrics ───────────────────────────────────────────────────

    def compression_ratio(self) -> float:
        """total_bins / orbit_count — analytic, no enumeration."""
        p = self._profile
        total = p.total_bins()
        n_orbits = self.count_orbits()
        return total / n_orbits if n_orbits else 1.0

    def compression_pct(self) -> float:
        p = self._profile
        total = p.total_bins()
        orbits = self.count_orbits()
        return 100 * (1 - orbits / total) if total else 0.0

    # ── Canonical form ────────────────────────────────────────────────────────

    def canonical(self, bt: BinTuple) -> BinTuple:
        """
        Return the canonical representative of bt's orbit.

        For Sₙ (direct or block): the lexicographically sorted tuple of
        block-value tuples, then flattened.

        For other groups: the lexicographic minimum of {g(bt) : g ∈ G}.
        Requires full group enumeration for non-Sₙ groups.
        """
        p = self._profile
        s = p.block_size

        if p.is_full_sn:
            # Extract block-value tuples, sort them, flatten
            blocks = [bt[i * s : (i + 1) * s] for i in range(p.n_blocks)]
            blocks_sorted = sorted(blocks)
            return tuple(v for block in blocks_sorted for v in block)

        # General: lex-min under group action
        group = self.bin_space._get_group()
        best = bt
        for g in group.elements():
            candidate = g.apply(bt)
            if candidate < best:
                best = candidate
        return best

    # ── Orbit membership ──────────────────────────────────────────────────────

    def orbit_of(self, bt: BinTuple) -> frozenset[BinTuple]:
        """
        Return all bins in the orbit of bt.

        For Sₙ: all distinct permutations of the block-value tuples.
        For other groups: {g(bt) : g ∈ G}.

        Note: for large Sₙ orbits (n! / repetition-factors), this can be
        large.  For coverage expansion purposes, the canonical form is
        usually sufficient.
        """
        p = self._profile
        s = p.block_size

        if p.is_full_sn:
            blocks = [bt[i * s : (i + 1) * s] for i in range(p.n_blocks)]
            result = set()
            for perm_of_blocks in permutations(blocks):
                flat = tuple(v for block in perm_of_blocks for v in block)
                result.add(flat)
            return frozenset(result)

        # General: apply all group elements
        group = self.bin_space._get_group()
        return frozenset(g.apply(bt) for g in group.elements())

    def is_same_orbit(self, bt1: BinTuple, bt2: BinTuple) -> bool:
        """Check whether two bins are in the same equivalence class."""
        return self.canonical(bt1) == self.canonical(bt2)

    # ── Representative enumeration ────────────────────────────────────────────

    def representatives(self) -> list[BinTuple]:
        """
        Enumerate the minimal representative set — one per orbit.

        For Sₙ (direct):
            All non-decreasing sequences of length n over range(K).
            Count = C(n+K−1, n).  Uses combinations_with_replacement.

        For block Sₙ:
            All non-decreasing sequences of per-block value tuples of
            length n.  Count = C(n+K−1, n) where K = # per-block combos.

        For general groups:
            The canonical form of each distinct orbit, obtained by
            iterating the full bin space and collecting canonical forms.
            May be slow for large spaces; prefer Pólya/Burnside groups.

        Returns
        -------
        Sorted list of BinTuples, one per orbit.
        """
        p = self._profile
        s = p.block_size

        if p.is_full_sn:
            return self._sn_representatives()

        # General: iterate full bin space, collect unique canonicals
        # Only feasible for small spaces
        total = p.total_bins()
        if total > 2_000_000:
            raise SymbolicLimitError(
                f"Cannot enumerate {total:,} bins for non-Sₙ group.  "
                f"Use BFS orbit engine for member enumeration, or restrict "
                f"to Sₙ symmetry for symbolic representative listing."
            )

        bs = self.bin_space
        seen: set[BinTuple] = set()
        result: list[BinTuple] = []
        ranges = [range(cp.bin_count()) for cp in bs._coverpoints]
        from itertools import product as cart_product
        for bt in cart_product(*ranges):
            c = self.canonical(bt)
            if c not in seen:
                seen.add(c)
                result.append(c)
        return sorted(result)

    def _sn_representatives(self) -> list[BinTuple]:
        """
        For Sₙ (direct or block): representative = lex-sorted block-value sequence.

        Enumerate via combinations_with_replacement on the per-block value space.
        """
        p = self._profile
        s = p.block_size

        if s == 1:
            # Direct Sₙ: single-signal coverpoints
            k = p.k_per_signal[0] if p.k_per_signal else 1
            reps = []
            for combo in combinations_with_replacement(range(k), p.n_blocks):
                reps.append(combo)
            return reps

        # Block Sₙ: enumerate all per-block value combos, then
        # combinations_with_replacement on those combos
        block_values: list[BinTuple] = list(
            iproduct(*[range(k) for k in p.k_per_signal])
        )
        # block_values are sorted lexicographically by iproduct construction

        reps = []
        for block_combo in combinations_with_replacement(
            range(len(block_values)), p.n_blocks
        ):
            flat = tuple(
                v
                for idx in block_combo
                for v in block_values[idx]
            )
            reps.append(flat)
        return reps

    # ── Report ────────────────────────────────────────────────────────────────

    def report(self) -> str:
        """Formatted summary of the symbolic analysis."""
        p      = self._profile
        method = self.method_used()
        total  = p.total_bins()
        n_orb  = self.count_orbits()
        ratio  = self.compression_ratio()
        W = 64

        method_label = {
            "polya"   : "Pólya closed-form  C(n+K−1, n)",
            "burnside": f"Burnside's lemma   |G|={self.bin_space._get_group().order():,}",
            "mobius"  : "Möbius inversion",
        }.get(method, method)

        lines = [
            "═" * W,
            "  Dabih — Symbolic Orbit Engine  (Idea E)",
            "═" * W,
            f"  BinSpace           : {self.bin_space.name or '(unnamed)'}",
            f"  Profile            : {p}",
            "─" * W,
            f"  Method             : {method_label}",
            f"  Instances (n)      : {p.n_blocks:>10,}",
            f"  Signals / instance : {p.block_size:>10,}",
            f"  Bins / signal      : {', '.join(str(k) for k in p.k_per_signal)}",
            f"  Per-block combos K : {p.K:>10,}",
            "─" * W,
            f"  Total bin space    : {total:>10,}",
            f"  Orbit count        : {n_orb:>10,}",
            f"  Bins eliminated    : {total - n_orb:>10,}  ({self.compression_pct():.1f}%)",
            f"  Compression ratio  : {ratio:>9.2f}×",
            "═" * W,
        ]
        return "\n".join(lines)
