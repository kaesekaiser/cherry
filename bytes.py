class BinaryError(ValueError):
    pass


SupportsBitConversion = int | str | list[int]


def convert_to_bits(data: SupportsBitConversion, length: int = 8) -> list[int]:
    if isinstance(data, int):
        return [int(g) for g in f"{data:b}".rjust(length, "0")[:-(length+1):-1]]
    elif isinstance(data, str):
        if not all(c in "01" for c in data):
            raise BinaryError("The value of a bit must be either 0 or 1.")
        return [int(g) for g in data.rjust(length, "0")[:-(length+1):-1]]
    elif isinstance(data, list):
        return data[:length] + [0 for _ in range(len(data), length)]
    elif isinstance(data, Byte):
        return data.bits


class Byte:  # not a fan of the built-in binary classes
    def __init__(self, data: SupportsBitConversion = 0, size: int = 8):
        self.size = size
        if data:
            self.bits = convert_to_bits(data, length=self.size)
        else:
            self.bits = [0 for _ in range(self.size)]

    @staticmethod
    def from_list(ls: list[int]):
        return Byte(data=ls, size=len(ls))

    @property
    def is_array(self):
        return self.size * 8 == len(self.bits)

    @property
    def value(self):
        return int("".join(str(g) for g in self.bits.__reversed__()), 2)

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
        return bytes(self.value)

    def __str__(self):
        return f"{self.value:b}".rjust(len(self), "0")

    def __getitem__(self, item: int | slice):
        if isinstance(item, slice):
            return Byte.from_list(self.bits[item])
        return self.bits[item]

    def __setitem__(self, key, value):
        if isinstance(key, slice):
            data = convert_to_bits(value, length=len(self.bits[key]))
            print(len(self.bits[key]), data)
            self.bits[key] = data
        elif isinstance(key, int):
            if value != 0 and value != 1:
                raise BinaryError("The value of a bit must be either 0 or 1.")
            self.bits[key] = value

    def flip(self, index: int):
        self.bits[index] = int(not self.bits[index])


class ByteArray(Byte):
    def __init__(self, size: int, data: SupportsBitConversion = 0):
        super().__init__(size=size*8, data=data)
        self.size = size

    @staticmethod
    def from_bytes(bts: list[Byte]):
        return ByteArray(len(bts), [j for g in bts for j in g.bits])

    @property
    def bytes(self) -> list[Byte]:
        return [Byte(self.bits[g*8:g*8+8]) for g in range(self.size)]

    def __str__(self):
        return " ".join(str(g) for g in self.bytes)

    def __getitem__(self, item) -> Byte:
        if isinstance(item, slice):
            return Byte.from_list(self.bits[item])
        return self.bytes[item]
