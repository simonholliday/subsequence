
import math
import typing


class Signal:
	
	"""
	Abstract base class for a time-varying signal.
	"""
	
	def value_at (self, beat: float) -> float:
		raise NotImplementedError


class LFO(Signal):

	"""
	A Low-Frequency Oscillator for generating periodic modulation signals.
	
	LFOs are used to create cyclical changes (like a 'swell' or 'vibrato') 
	over many bars.
	"""

	def __init__ (self, shape: str = "sine", cycle_beats: float = 16.0, min_val: float = 0.0, max_val: float = 1.0, phase: float = 0.0) -> None:
		
		"""
		Initialize an LFO.
		
		Parameters:
			shape: The waveform shape ("sine", "triangle", "saw", "square").
			cycle_beats: How many beats for one full cycle (e.g., 16.0 = 4 bars).
			min_val: The bottom of the LFO range (default 0.0).
			max_val: The top of the LFO range (default 1.0).
			phase: Phase offset (0.0 to 1.0).
		"""
		
		self.shape = shape
		self.cycle_beats = cycle_beats
		self.min_val = min_val
		self.max_val = max_val
		self.phase = phase

	def value_at (self, beat: float) -> float:
		
		"""
		Compute the signal value at a given beat time.
		"""
		
		progress = (beat / self.cycle_beats + self.phase) % 1.0
		val = 0.0
		
		if self.shape == "sine":
			# Map -1..1 to 0..1
			raw = math.sin(progress * 2 * math.pi)
			val = (raw + 1) / 2
			
		elif self.shape == "triangle":
			# 0 -> 0.5 -> 1 -> 0.5 -> 0
			if progress < 0.5:
				val = progress * 2
			else:
				val = 2 - (progress * 2)
				
		elif self.shape == "saw":
			val = progress
			
		elif self.shape == "square":
			val = 1.0 if progress < 0.5 else 0.0
			
		else:
			# Default to sine
			raw = math.sin(progress * 2 * math.pi)
			val = (raw + 1) / 2
			
		return self.min_val + (val * (self.max_val - self.min_val))


class Line(Signal):

	"""
	A linear 'ramp' signal that moves from one value to another over time.
	"""

	def __init__ (self, start_val: float, end_val: float, duration_beats: float, start_beat: float = 0.0, loop: bool = False) -> None:
		
		"""
		Initialize a linear ramp.
		
		Parameters:
			start_val: Initial value.
			end_val: Target value.
			duration_beats: How long it takes to reach the target (in beats).
			start_beat: Global beat time when the ramp should start (default 0).
			loop: Whether to jump back to start_val and repeat (default False).
		"""
		
		self.start_val = start_val
		self.end_val = end_val
		self.duration_beats = duration_beats
		self.start_beat = start_beat
		self.loop = loop

	def value_at (self, beat: float) -> float:
		
		"""
		Compute the ramp value at a given beat time.
		"""
		
		elapsed = beat - self.start_beat
		
		if elapsed < 0:
			return self.start_val
			
		if self.loop:
			elapsed %= self.duration_beats
		elif elapsed >= self.duration_beats:
			return self.end_val
			
		progress = elapsed / self.duration_beats
		return self.start_val + (progress * (self.end_val - self.start_val))


class Conductor:

	"""
	A registry for global automation signals.
	
	The `Conductor` allows you to define time-varying signals (like LFOs or 
	ramps) that are available to all pattern builders. This is ideal for 
	modulating parameters (like velocity or filter cutoff) over long 
	compositional timeframes.
	"""

	def __init__ (self) -> None:
		self._signals: typing.Dict[str, Signal] = {}

	def lfo (self, name: str, shape: str = "sine", cycle_beats: float = 16.0, min_val: float = 0.0, max_val: float = 1.0, phase: float = 0.0) -> None:
		
		"""
		Register a named LFO signal.
		
		Example:
			```python
			comp.conductor.lfo("swell", shape="sine", cycle_beats=32)
			```
		"""
		
		self._signals[name] = LFO(shape, cycle_beats, min_val, max_val, phase)

	def line (self, name: str, start_val: float, end_val: float, duration_beats: float, start_beat: float = 0.0, loop: bool = False) -> None:
		
		"""
		Register a named linear ramp signal.
		
		Example:
			```python
			comp.conductor.line("fadein", start_val=0, end_val=1, duration_beats=64)
			```
		"""
		
		self._signals[name] = Line(start_val, end_val, duration_beats, start_beat, loop)

	def get (self, name: str, beat: float) -> float:
		
		"""
		Retrieve the value of a signal at a specific beat time.
		
		Pattern builders usually call this using `p.c.get("name", p.bar * 4)`.
		"""
		
		if name not in self._signals:
			return 0.0
			
		return self._signals[name].value_at(beat)
