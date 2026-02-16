import dataclasses
import re
import typing


@dataclasses.dataclass
class ParsedEvent:

	"""
	Represents a single event parsed from mini-notation.
	"""

	time: float
	duration: float
	symbol: str


class MiniNotationError(Exception):
	pass


def parse (notation: str, total_duration: float = 4.0) -> typing.List[ParsedEvent]:

	"""
	Parse a mini-notation string into a list of timed events.

	Syntax:
		- Space-separated items are distributed evenly over the duration.
		- `[...]` groups items into a single step (subdivision).
		- `~` or `.` is a rest.
		- `_` extends the previous note (legato/sustain).
	
	Example:
		parse("k s [k k] s", 4.0)
		-> k (0.0), s (1.0), k (2.0), k (2.5), s (3.0)
	"""

	tokens = _tokenize(notation)
	
	events = _parse_recursive(tokens, 0.0, total_duration)
	
	return _post_process_sustains(events)


def _tokenize (text: str) -> typing.List[typing.Union[str, list]]:
	
	"""
	Convert string into nested lists of tokens.
	"a [b c]" -> ["a", ["b", "c"]]
	"""
	
	# Add spaces around brackets to make splitting easier
	text = text.replace("[", " [ ").replace("]", " ] ")
	raw_tokens = text.split()
	
	stack: typing.List[list] = [[]]
	
	for token in raw_tokens:
	
		if token == "[":
			new_group: typing.List[typing.Any] = []
			stack[-1].append(new_group)
			stack.append(new_group)
			
		elif token == "]":
			if len(stack) <= 1:
				raise MiniNotationError("Unexpected closing bracket")
			stack.pop()
			
		else:
			stack[-1].append(token)
			
	if len(stack) > 1:
		raise MiniNotationError("Missing closing bracket")
		
	return stack[0]


def _parse_recursive (tokens: list, start_time: float, duration: float) -> typing.List[ParsedEvent]:

	"""
	Recursively distribute tokens over the given duration.
	"""

	events: typing.List[ParsedEvent] = []
	step_duration = duration / len(tokens) if tokens else 0

	for i, token in enumerate(tokens):
	
		current_time = start_time + (i * step_duration)
		
		if isinstance(token, list):
			# Recursively parse sub-group
			events.extend(_parse_recursive(token, current_time, step_duration))
			
		elif isinstance(token, str):
			if token in ("~", "."):
				continue
			events.append(ParsedEvent(current_time, step_duration, token))
			
	return events


def _post_process_sustains (events: typing.List[ParsedEvent]) -> typing.List[ParsedEvent]:

	"""
	Merge `_` events into the previous event's duration.
	"""

	if not events:
		return []

	processed: typing.List[ParsedEvent] = []
	last_event = None

	for event in events:
	
		if event.symbol == "_":
			if last_event:
				last_event.duration += event.duration
				
		else:
			processed.append(event)
			last_event = event

	return processed
