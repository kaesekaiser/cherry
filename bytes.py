import json
import re
from math import ceil


class Instruction:
    def __init__(self, code: int, mnemonic: str, args: list[dict]):
        self.code = code
        self.mnemonic = mnemonic
        self.args = args

    @property
    def base_length(self) -> int:
        return 1 + sum(g["bytes"] for g in self.args)

    @staticmethod
    def from_json(js: dict):
        return Instruction(**js)

    def __bytes__(self):
        return bytes([self.code])


instructions = json.load(open("instructions.json"))
opcodes = {g["code"]: Instruction.from_json(g) for g in instructions}


class BitError(ValueError):
    pass


SupportsBitConversion = int | str | list[int] | bytes


def zero_pad(ls: list, length: int):
    return ls[:length] + [0 for _ in range(len(ls), length)]


def convert_to_bits(data: SupportsBitConversion, length: int = 8) -> list[int]:
    if isinstance(data, int):
        if data < 0:
            data += 2 ** length
        return [int(g) for g in f"{data:b}".rjust(length, "0")[:-(length+1):-1]]
    elif isinstance(data, str):
        if re.fullmatch(r"[01]{8}( +[01]{8})*", data):
            return zero_pad([int(j) for g in data.split() for j in g[::-1]], length)
        elif re.fullmatch(r"0b[01]*", data):
            return [int(g) for g in data[2:].rjust(length, "0")[:-(length+1):-1]]
        elif re.fullmatch(r"[0-9A-Fa-f]{2}( +[0-9A-Fa-f]{2})*", data):
            return zero_pad([j for g in data.split() for j in convert_to_bits(int(g, 16), 8)], length)
        elif re.fullmatch(r"0x[0-9A-Fa-f]*", data):
            return zero_pad([j for g in data[2:] for j in convert_to_bits(int(g, 16), 4)], length)
        else:
            raise BitError(f"Invalid string format: {data}")
    elif isinstance(data, list):
        return zero_pad(data, length)
    elif isinstance(data, Byte):
        return zero_pad(data.bits, length)
    elif isinstance(data, bytes):
        return [j for g in list(data) for j in convert_to_bits(g)]


class Byte:  # not a fan of the built-in binary classes
    def __init__(self, data: SupportsBitConversion = 0, size: int = 8):
        self.size = size
        self.bits = convert_to_bits(data, length=self.size)

    @staticmethod
    def from_bits(ls: list[int]):
        return Byte(data=ls, size=len(ls))

    @property
    def is_array(self):
        return self.size * 8 == len(self.bits)

    @property
    def value(self):
        return int("".join(str(g) for g in self.bits.__reversed__()), 2)

    @property
    def mnemonic(self) -> str:
        if self.value in opcodes:
            return opcodes[self.value].mnemonic
        return "NOP"

    def __len__(self):
        return len(self.bits)

    def __neg__(self):
        return self.__class__(data=[[1, 0][g] for g in self.bits], size=self.size)

    def __and__(self, other):
        return self.__class__(data=self.value & other.value, size=self.size)

    def __or__(self, other):
        return self.__class__(data=self.value | other.value, size=self.size)

    def __xor__(self, other):
        return self.__class__(data=self.value ^ other.value, size=self.size)

    def __eq__(self, other):
        return self.bits == other.bits

    def __lshift__(self, n):
        return self.__class__(data=[0 for _ in range(n)] + self.bits[:-n], size=self.size)

    def __rshift__(self, n):
        return self.__class__(data=self.bits[n:] + [0 for _ in range(n)], size=self.size)

    def __bytes__(self):
        return bytes([self.value])

    @property
    def hex(self):
        return hex(self.value)[2:].upper().rjust(2, "0")

    def __str__(self):
        return f"{self.value:b}".rjust(len(self), "0")

    def __getitem__(self, item: int | slice):
        if isinstance(item, slice):
            return Byte.from_bits(self.bits[item])
        return self.bits[item]

    def __setitem__(self, key, value):
        if isinstance(key, slice):
            data = convert_to_bits(value, length=len(self.bits[key]))
            self.bits[key] = data
        elif isinstance(key, int):
            if value != 0 and value != 1:
                raise BitError("The value of a bit must be either 0 or 1.")
            self.bits[key] = value

    def flip(self, index: int):
        self.bits[index] = int(not self.bits[index])

    @property
    def substring(self):
        return SubValue(self.bits, self.size)

    def signed_int(self):
        return int("".join(str(g) for g in self.bits.__reversed__()), 2) - \
            (2 ** self.size if self.bits[-1] else 0)


class SubValue:
    def __init__(self, data: SupportsBitConversion, size: int):
        self.bits = convert_to_bits(data, length=size)

    def __getitem__(self, item) -> int:
        if isinstance(item, slice):
            return int("".join(str(g) for g in self.bits[item].__reversed__()), 2)
        elif isinstance(item, int):
            return self.bits[item]


class ByteArray(Byte):
    def __init__(self, size: int, data: SupportsBitConversion = 0):
        super().__init__(size=size*8, data=data)
        self.size = size

    @staticmethod
    def from_bytes(bts: list[Byte]):
        return ByteArray(size=len(bts), data=[j for g in bts for j in g.bits])

    @staticmethod
    def from_bits(ls: list[int]):
        return ByteArray(data=ls, size=ceil(len(ls) / 8))

    @property
    def bytes(self) -> list[Byte]:
        return [Byte(self.bits[g*8:g*8+8]) for g in range(self.size)]

    @property
    def hex(self):
        return " ".join(g.hex for g in self.bytes)

    @property
    def opcode(self):
        return self.bytes[0].value

    @property
    def mnemonic(self) -> str:
        return self.bytes[0].mnemonic

    def __str__(self):
        return " ".join(str(g) for g in self.bytes)

    def __getitem__(self, item):  # -> Byte | ByteArray
        if isinstance(item, slice):
            return ByteArray.from_bits([j for g in self.bytes[item] for j in g.bits])
        return self.bytes[item]

    def __bytes__(self):
        return bytes([g.value for g in self.bytes])

    def __len__(self):
        return len(self.bits) // 8

    def signed_int(self):
        return int("".join(str(g) for g in self.bits.__reversed__()), 2) - \
            (2 ** (self.size * 8) if self.bits[-1] else 0)
