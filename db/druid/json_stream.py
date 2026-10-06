'''Stream the elements of a JSON array, such as a Druid response, with bounded
memory.

Each element is decoded by the standard library's C scanner, so integers stay
exact (Druid's Long.MIN_VALUE included) and doubles become correctly rounded
floats. NaN, the infinities and numbers out of double range are rejected: Druid
quotes NaN and the infinities as strings, and the yajl parser used before WP-3b
rejected them too.

The buffer holds the text from the start of the element being decoded. While that
element is incomplete, or malformed (the decoder cannot tell the two apart until
the body ends), more of the body is read after it. Once that text passes
_MAX_ELEMENT_CHARS the parse fails with ValueError.
'''

import codecs
import json
import math
import re
from typing import IO, Any, Iterator

_READ_BYTES = 1024 * 1024
# Druid rows are a few hundred bytes. Padding or an unterminated token inside one
# element must be buffered to decode it, so cap it (security gate F3).
_MAX_ELEMENT_CHARS = 64 * 1024 * 1024
_WHITESPACE = re.compile(r'[ \t\n\r]*')
_NUMBER_TAIL = re.compile(r'(?:\.|[eE][+-]?)\Z')


def _reject_constant(name: str) -> Any:
    raise ValueError(f'{name} is not valid JSON')


def _finite_float(text: str) -> float:
    value = float(text)
    if math.isinf(value):
        raise ValueError(f'{text} is out of double range')
    return value


_decode_value = json.JSONDecoder(
    parse_constant=_reject_constant, parse_float=_finite_float
).raw_decode


class _Buffer:
    '''UTF-8 text read from a binary file, with the consumed prefix dropped.'''

    def __init__(self, fp: IO[bytes]):
        self.fp = fp
        self.decode = codecs.getincrementaldecoder('utf-8')().decode
        self.text = ''
        self.pos = 0
        self.eof = False

    def fill(self) -> None:
        # Pending text is the start of one element still being decoded.
        pending = len(self.text) - self.pos
        if pending > _MAX_ELEMENT_CHARS:
            raise ValueError(
                f'one element of the JSON array is larger than {_MAX_ELEMENT_CHARS} '
                'characters'
            )
        # Read at least as much as is pending, so one element larger than a read
        # costs linear, not quadratic, time.
        data = self.fp.read(max(_READ_BYTES, pending))
        self.eof = not data
        self.text = self.text[self.pos :] + self.decode(data, final=self.eof)
        self.pos = 0

    def next_char(self) -> str:
        '''Skip whitespace and return the next character, or '' at the end.'''
        while True:
            self.pos = _WHITESPACE.match(self.text, self.pos).end()  # type: ignore[union-attr]
            if self.pos < len(self.text) or self.eof:
                return self.text[self.pos : self.pos + 1]
            self.fill()

    def value(self) -> Any:
        while True:
            try:
                value, end = _decode_value(self.text, self.pos)
            except json.JSONDecodeError:
                if self.eof:
                    raise
                self.fill()
                continue
            # A number that ends the buffer may continue in the next read: after its
            # last digit ("12" of "123"), or after a decimal point or exponent
            # marker ("0" of "0.5", "1.5" of "1.5e-3"), which raw_decode leaves.
            if not self.eof and (
                end == len(self.text) or _NUMBER_TAIL.match(self.text, end)
            ):
                self.fill()
                continue
            self.pos = end
            return value


def iter_json_array(fp: IO[bytes]) -> Iterator[Any]:
    '''Yield each element of the JSON array in `fp`, a UTF-8 binary file. Raise
    ValueError for anything else, including data after the array.'''
    buffer = _Buffer(fp)
    if buffer.next_char() != '[':
        raise ValueError('expected a JSON array')
    buffer.pos += 1
    if buffer.next_char() == ']':
        buffer.pos += 1
    else:
        while True:
            yield buffer.value()
            separator = buffer.next_char()
            buffer.pos += 1
            if separator == ']':
                break
            if separator != ',':
                raise ValueError(f'expected "," or "]", found {separator!r}')
            buffer.next_char()
    if buffer.next_char():
        raise ValueError('data after the JSON array')
