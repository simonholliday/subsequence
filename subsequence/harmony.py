import dataclasses
import random
import typing

import subsequence.constants
import subsequence.markov_chain
import subsequence.pattern


NOTE_NAME_TO_PC = {
	"C": 0,
	"C#": 1,
	"Db": 1,
	"D": 2,
	"D#": 3,
	"Eb": 3,
	"E": 4,
	"F": 5,
	"F#": 6,
	"Gb": 6,
	"G": 7,
	"G#": 8,
	"Ab": 8,
	"A": 9,
	"A#": 10,
	"Bb": 10,
	"B": 11,
}

PC_TO_NOTE_NAME = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


CHORD_INTERVALS = {
	"major": [0, 4, 7],
	"minor": [0, 3, 7],
	"diminished": [0, 3, 6],
	"augmented": [0, 4, 8],
	"dominant_7th": [0, 4, 7, 10],
	"major_7th": [0, 4, 7, 11],
	"minor_7th": [0, 3, 7, 10],
}

CHORD_SUFFIX = {
	"major": "",
	"minor": "m",
	"diminished": "dim",
	"augmented": "+",
	"dominant_7th": "7",
	"major_7th": "maj7",
	"minor_7th": "m7",
}


WEIGHT_STRONG = 6
WEIGHT_MEDIUM = 4
WEIGHT_COMMON = 3
WEIGHT_WEAK = 1
WEIGHT_DECEPTIVE = 2


@dataclasses.dataclass(frozen=True)
class Chord:

	"""
	Represents a chord as a root pitch class and quality.
	"""

	root_pc: int
	quality: str


	def intervals (self) -> typing.List[int]:

		"""
		Return the chord intervals for this chord quality.
		"""

		if self.quality not in CHORD_INTERVALS:
			raise ValueError(f"Unknown chord quality: {self.quality}")

		return CHORD_INTERVALS[self.quality]


	def name (self) -> str:

		"""
		Return a human-friendly chord name.
		"""

		root_name = PC_TO_NOTE_NAME[self.root_pc % 12]
		suffix = CHORD_SUFFIX.get(self.quality, "")

		return f"{root_name}{suffix}"


class ChordTransitionGraph:

	"""
	A weighted transition graph for chords.
	"""

	def __init__ (self) -> None:

		"""
		Initialize an empty chord transition graph.
		"""

		self.transitions: typing.Dict[Chord, typing.List[typing.Tuple[Chord, int]]] = {}


	def add_transition (self, source: Chord, target: Chord, weight: int) -> None:

		"""
		Add a weighted transition between two chords.
		"""

		if weight <= 0:
			raise ValueError("Transition weight must be positive")

		if source not in self.transitions:
			self.transitions[source] = []

		self.transitions[source].append((target, weight))


	def get_transitions (self, source: Chord) -> typing.List[typing.Tuple[Chord, int]]:

		"""
		Return the weighted transitions for a chord.
		"""

		return self.transitions.get(source, [])


	def choose_next (self, source: Chord, rng: random.Random) -> Chord:

		"""
		Choose the next chord based on weighted transitions.
		"""

		options = self.get_transitions(source)

		if not options:
			return source

		return subsequence.markov_chain.choose_weighted(options, rng)


def build_major_key_graph (key_name: str, include_dominant_7th: bool = True) -> typing.Tuple[ChordTransitionGraph, Chord]:

	"""
	Build a transition graph for a major key and return it with the tonic chord.
	"""

	if key_name not in NOTE_NAME_TO_PC:
		raise ValueError(f"Unknown key name: {key_name}")

	key_pc = NOTE_NAME_TO_PC[key_name]
	scale_intervals = [0, 2, 4, 5, 7, 9, 11]
	degree_qualities = ["major", "minor", "minor", "major", "major", "minor", "diminished"]

	chords: typing.List[Chord] = []

	for degree, quality in enumerate(degree_qualities):
		root_pc = (key_pc + scale_intervals[degree]) % 12
		chords.append(Chord(root_pc=root_pc, quality=quality))

	tonic = chords[0]
	supertonic = chords[1]
	mediant = chords[2]
	subdominant = chords[3]
	dominant = chords[4]
	submediant = chords[5]
	leading = chords[6]

	graph = ChordTransitionGraph()

	graph.add_transition(tonic, subdominant, WEIGHT_COMMON)
	graph.add_transition(tonic, dominant, WEIGHT_COMMON)
	graph.add_transition(tonic, submediant, WEIGHT_COMMON)
	graph.add_transition(tonic, supertonic, WEIGHT_WEAK)

	graph.add_transition(supertonic, dominant, WEIGHT_STRONG)

	graph.add_transition(mediant, submediant, WEIGHT_COMMON)
	graph.add_transition(mediant, subdominant, WEIGHT_WEAK)

	graph.add_transition(subdominant, dominant, WEIGHT_STRONG)
	graph.add_transition(subdominant, supertonic, WEIGHT_COMMON)

	graph.add_transition(dominant, tonic, WEIGHT_STRONG)
	graph.add_transition(dominant, submediant, WEIGHT_DECEPTIVE)

	graph.add_transition(submediant, supertonic, WEIGHT_COMMON)
	graph.add_transition(submediant, subdominant, WEIGHT_COMMON)
	graph.add_transition(submediant, dominant, WEIGHT_WEAK)

	graph.add_transition(leading, tonic, WEIGHT_STRONG)

	if include_dominant_7th:
		dominant_7th = Chord(root_pc=dominant.root_pc, quality="dominant_7th")

		graph.add_transition(dominant, dominant_7th, WEIGHT_WEAK)
		graph.add_transition(dominant_7th, tonic, WEIGHT_STRONG)
		graph.add_transition(dominant_7th, submediant, WEIGHT_DECEPTIVE)

	return graph, tonic


class ChordMarkov:

	"""
	Holds the current chord and advances through a transition graph.
	"""

	def __init__ (self, graph: ChordTransitionGraph, start: Chord, rng: typing.Optional[random.Random] = None) -> None:

		"""
		Initialize the Markov chord state.
		"""

		self.graph = graph
		self.chain = subsequence.markov_chain.MarkovChain(
			transitions = graph.transitions,
			initial_state = start,
			rng = rng
		)


	def step (self) -> Chord:

		"""
		Advance to the next chord and return it.
		"""

		return self.chain.step()


	def get_state (self) -> Chord:

		"""
		Return the current chord.
		"""

		return self.chain.get_state()


class ChordPattern (subsequence.pattern.Pattern):

	"""
	A repeating chord pattern that evolves with a Markov progression.
	"""

	def __init__ (
		self,
		key_name: str,
		length: int = 4,
		root_midi: int = 52,
		velocity: int = 90,
		reschedule_lookahead: int = 1,
		include_dominant_7th: bool = True,
		rng: typing.Optional[random.Random] = None,
		channel: int = subsequence.constants.MIDI_CHANNEL_VOCE_EP
	) -> None:

		"""
		Initialize a chord pattern for a major key.
		"""

		super().__init__(
			channel = channel,
			length = length,
			reschedule_lookahead = reschedule_lookahead
		)

		self.key_name = key_name
		self.key_root_pc = NOTE_NAME_TO_PC[key_name]
		self.key_root_midi = root_midi
		self.velocity = velocity

		graph, tonic = build_major_key_graph(key_name, include_dominant_7th=include_dominant_7th)

		self.markov = ChordMarkov(graph, tonic, rng=rng)
		self.current_chord = tonic

		self._build_current_chord()


	def _get_chord_root_midi (self, chord: Chord) -> int:

		"""
		Calculate the MIDI root for a chord relative to the key root.
		"""

		offset = (chord.root_pc - self.key_root_pc) % 12

		return self.key_root_midi + offset


	def _build_current_chord (self) -> None:

		"""
		Build the current chord as a sustained voicing.
		"""

		self.steps = {}

		chord_root_midi = self._get_chord_root_midi(self.current_chord)
		chord_intervals = self.current_chord.intervals()

		# Root-position voicing: chord notes ascend from the root.
		# To add inversions later, rotate chord_intervals or adjust chord_root_midi
		# to keep voices closer between transitions.
		for interval in chord_intervals:
			self.add_note_beats(
				beat_position = 0.0,
				pitch = chord_root_midi + interval,
				velocity = self.velocity,
				duration_beats = float(self.length)
			)


	def on_reschedule (self) -> None:

		"""
		Advance the chord and rebuild the pattern.
		"""

		self.current_chord = self.markov.step()

		self._build_current_chord()
