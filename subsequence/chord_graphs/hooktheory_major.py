import typing

import subsequence.chord_graphs
import subsequence.chords
import subsequence.intervals
import subsequence.weighted_graph


# Corpus-tendency transition table for a major key — relative frequencies in
# the spirit of Hooktheory's Theorytab statistics (pop/rock songwriting), a
# baked table, NOT a textbook functional-flow rulebook.  Each row is a
# per-source distribution: the weights compare targets of ONE chord.  Diatonic
# triads only (I ii iii IV V vi vii°), indexed 1–7 by scale degree.
#
# The well-known empirical tendencies it encodes: I leans to V/IV/vi; V resolves
# strongly to I and deceptively to vi; IV→I and IV→V; vi→IV/V/ii; ii→V; iii is
# rare and usually heads to vi or IV; vii°→I.
_DEGREE_TRANSITIONS: typing.Dict[int, typing.List[typing.Tuple[int, int]]] = {
    1: [(5, 8), (4, 8), (6, 7), (2, 4), (3, 2), (7, 1)],
    2: [(5, 9), (4, 4), (1, 3), (6, 2), (7, 1), (3, 1)],
    3: [(6, 7), (4, 7), (1, 3), (2, 2), (5, 2)],
    4: [(1, 8), (5, 7), (6, 4), (2, 4), (3, 1)],
    5: [(1, 9), (6, 7), (4, 6), (2, 2), (3, 1)],
    6: [(4, 7), (5, 6), (2, 5), (1, 4), (3, 2)],
    7: [(1, 9), (6, 3), (5, 2), (3, 1)],
}


class HooktheoryMajor(subsequence.chord_graphs.ChordGraph):
    """Major-key graph weighted by pop/rock corpus tendencies.

    The same seven diatonic triads as :class:`DiatonicMajor`, but the
    transition weights follow real songwriting frequencies (Hooktheory-informed)
    rather than textbook function — so the walk gravitates to the four-chord
    loops that dominate popular music (I–V–vi–IV and its rotations) and uses
    iii sparingly.  Optionally colours the dominant with a seventh.
    """

    def __init__(self, include_dominant_7th: bool = True) -> None:
        """Configure whether to add a dominant-seventh colour on V."""

        self.include_dominant_7th = include_dominant_7th

    def build(
        self, key_name: str
    ) -> typing.Tuple[
        subsequence.weighted_graph.WeightedGraph[subsequence.chords.Chord],
        subsequence.chords.Chord,
    ]:
        """Build the corpus-weighted graph for a given major key."""

        key_pc = subsequence.chord_graphs.validate_key_name(key_name)

        chords = subsequence.chord_graphs.build_diatonic_chords(
            subsequence.intervals.scale_pitch_classes(key_pc, "ionian"),
            subsequence.intervals.IONIAN_QUALITIES,
        )

        graph: subsequence.weighted_graph.WeightedGraph[subsequence.chords.Chord] = (
            subsequence.weighted_graph.WeightedGraph()
        )

        for source_degree, targets in _DEGREE_TRANSITIONS.items():
            source = chords[source_degree - 1]
            for target_degree, weight in targets:
                graph.add_transition(source, chords[target_degree - 1], weight)

        if self.include_dominant_7th:
            # A V7 colour the corpus reaches from V and that resolves home or
            # deceptively, mirroring the V row's strongest moves.
            dominant = chords[4]
            dominant_7th = subsequence.chords.Chord(
                root_pc=dominant.root_pc, quality="dominant_7th"
            )

            graph.add_transition(
                dominant, dominant_7th, subsequence.chord_graphs.WEIGHT_MEDIUM
            )
            graph.add_transition(dominant_7th, chords[0], 9)  # V7 → I
            graph.add_transition(dominant_7th, chords[5], 7)  # V7 → vi (deceptive)
            graph.add_transition(dominant_7th, chords[3], 6)  # V7 → IV

        return graph, chords[0]

    def gravity_sets(
        self, key_name: str
    ) -> typing.Tuple[
        typing.Set[subsequence.chords.Chord], typing.Set[subsequence.chords.Chord]
    ]:
        """Return major-key diatonic and functional chord sets."""

        return subsequence.chord_graphs._major_key_gravity_sets(key_name)


def build_graph(
    key_name: str, include_dominant_7th: bool = True
) -> typing.Tuple[
    subsequence.weighted_graph.WeightedGraph[subsequence.chords.Chord],
    subsequence.chords.Chord,
]:
    """Build a corpus-weighted major-key graph and return it with the tonic chord."""

    return HooktheoryMajor(include_dominant_7th=include_dominant_7th).build(key_name)
