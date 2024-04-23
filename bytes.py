def convert_to_bits(data: int | str | list[int], length: int = 8) -> list[int]:
    if isinstance(data, int):
        return [int(g) for g in f"{data:b}".rjust(length, "0")[:-(length+1):-1]]
    elif isinstance(data, str):
        if not all(c in "01" for c in data):
            raise ValueError("The value of a bit must be either 0 or 1.")
        return [int(g) for g in data.rjust(length, "0")[:-(length+1):-1]]
    elif isinstance(data, list):
        return data[:length] + [0 for _ in range(len(data), length)]


class Byte:  # not a fan of the built-in binary classes
    def __init__(self, value: int | str | list[int] = 0):
        if value:
            self.bits = convert_to_bits(value)
        else:
            self.bits = [0 for _ in range(8)]

    @property
    def value(self):
        return int("".join(str(g) for g in self.bits.__reversed__()), 2)

    def __neg__(self):
        return Byte([(1, 0)[g] for g in self.bits])

    def __and__(self, other):
        return Byte(self.value & other.value)

    def __or__(self, other):
        return Byte(self.value | other.value)

    def __xor__(self, other):
        return Byte(self.value ^ other.value)

    def __eq__(self, other):
        return self.value == other.value

    def __lshift__(self, other):
        return Byte(self.value << other)

    def __rshift__(self, other):
        return Byte(self.value >> other)

    def __bytes__(self):
        return bytes(self.value)

    def __str__(self):
        return f"{self.value:b}".rjust(8, "0")

    def __getitem__(self, item: int | slice):
        return self.bits[item]

    def __setitem__(self, key, value):
        if isinstance(key, slice):
            data = convert_to_bits(value, length=len(self.bits[key]))
            print(len(self.bits[key]), data)
            self.bits[key] = data
        elif isinstance(key, int):
            if value != 0 and value != 1:
                raise ValueError("The value of a bit must be either 0 or 1.")
            self.bits[key] = value

    def flip(self, index):
        self.bits[index] = int(not self.bits[index])
