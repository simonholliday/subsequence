import typing

import subsequence.chord_graphs
import subsequence.chords
import subsequence.weighted_graph


WEIGHT_SYMMETRY = 5
WEIGHT_ESCAPE = 4
WEIGHT_RESOLVE = 4
WEIGHT_COMMON = subsequence.chord_graphs.WEIGHT_COMMON


class Diminished(subsequence.chord_graphs.ChordGraph):
    """Diminished chord graph with minor-third symmetry and chromatic escapes.

    Two chord types interlock:

    - 4 diminished triads at roots 0, 3, 6, 9 (the symmetry backbone — the
      minor-third cycle that also underpins the half-whole diminished scale)
    - 4 dominant 7th chords at roots 1, 4, 7, 10 (escape chords)

    Diminished chords connect to each other by minor thirds (the defining
    rotation). Each dominant 7th sits a half step ABOVE its diminished
    chord as a chromatic tension point — deliberately outside the
    half-whole scale on the key root, which is what gives the escape its
    lift before the half-step-down resolve. The result is angular,
    disorienting, and cyclical - useful for dark techno, industrial, and
    experimental electronic music.
    """

    def build(
        self, key_name: str
    ) -> typing.Tuple[
        subsequence.weighted_graph.WeightedGraph[subsequence.chords.Chord],
        subsequence.chords.Chord,
    ]:
        """Build an octatonic graph with diminished and dominant 7th chords."""

        key_pc = subsequence.chord_graphs.validate_key_name(key_name)

        # Four diminished triads, each a minor third apart.
        dim_roots = [(key_pc + i) % 12 for i in [0, 3, 6, 9]]
        dim_chords = [
            subsequence.chords.Chord(root_pc=r, quality="diminished") for r in dim_roots
        ]

        # Four dominant 7th chords, each a half step above a diminished chord.
        dom_roots = [(key_pc + i) % 12 for i in [1, 4, 7, 10]]
        dom_chords = [
            subsequence.chords.Chord(root_pc=r, quality="dominant_7th")
            for r in dom_roots
        ]

        graph: subsequence.weighted_graph.WeightedGraph[subsequence.chords.Chord] = (
            subsequence.weighted_graph.WeightedGraph()
        )

        # --- Diminished ↔ diminished (minor third rotation) ---
        for i, source in enumerate(dim_chords):
            for j, target in enumerate(dim_chords):
                if i != j:
                    graph.add_transition(source, target, WEIGHT_SYMMETRY)

        # --- Diminished → dominant 7th (half step up = escape) ---
        for i in range(4):
            graph.add_transition(dim_chords[i], dom_chords[i], WEIGHT_ESCAPE)

        # --- Dominant 7th → diminished (half step down = resolve) ---
        for i in range(4):
            graph.add_transition(dom_chords[i], dim_chords[i], WEIGHT_RESOLVE)

        # --- Dominant 7th ↔ dominant 7th (minor third rotation) ---
        for i, source in enumerate(dom_chords):
            for j, target in enumerate(dom_chords):
                if i != j:
                    graph.add_transition(source, target, WEIGHT_COMMON)

        tonic = dim_chords[0]

        return graph, tonic

    def gravity_sets(
        self, key_name: str
    ) -> typing.Tuple[
        typing.Set[subsequence.chords.Chord], typing.Set[subsequence.chords.Chord]
    ]:
        """Return octatonic diatonic and functional chord sets."""

        key_pc = subsequence.chord_graphs.validate_key_name(key_name)

        diatonic: typing.Set[subsequence.chords.Chord] = set()

        # Gravity treats the full 8-chord palette as "home": the dominant
        # escapes are included by design even though they sit outside the
        # half-whole scale on the key root (they are the graph's tension
        # vocabulary, not foreign territory to be damped).
        for i in [0, 3, 6, 9]:
            diatonic.add(
                subsequence.chords.Chord(
                    root_pc=(key_pc + i) % 12, quality="diminished"
                )
            )

        for i in [1, 4, 7, 10]:
            diatonic.add(
                subsequence.chords.Chord(
                    root_pc=(key_pc + i) % 12, quality="dominant_7th"
                )
            )

        # Functional: the 4 diminished chords (symmetry backbone).
        functional: typing.Set[subsequence.chords.Chord] = set()

        for i in [0, 3, 6, 9]:
            functional.add(
                subsequence.chords.Chord(
                    root_pc=(key_pc + i) % 12, quality="diminished"
                )
            )

        return diatonic, functional
