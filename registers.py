import json
from bytes import *


class Register:
    def __init__(self, size: int, data: SupportsBitConversion | Byte = 0, children: dict[str, int] = ()):
        self.size = size
        self.bits = convert_to_bits(data, length=self.size * 8)
        self.children = dict(children)

    @property
    def bytes(self):
        return ByteArray(self.size, self.bits)

    @staticmethod
    def from_json(js: dict):
        return Register(size=js["size"], data=js.get("data", 0), children=js.get("children", {}))

    def __str__(self):
        return str(ByteArray(self.size, self.bits))

    def write(self, data: SupportsBitConversion | Byte):
        self.bits = convert_to_bits(data, length=self.size * 8)


class Drive(Register):
    def write_at(self, address: int, data: SupportsBitConversion | Byte):
        self.bits[address:address+8] = convert_to_bits(data)


class Machine:
    def __init__(self):
        registers = json.load(open("registers.json"))
        self.registers = {k: Register.from_json(v) for k, v in registers.items()}
        self.register_pointers = {v["pointer"]: k for k, v in registers.items()}
        self.memory = Register(65536)  # just implementing memory as a continuous linear address space w/o paging

    def get_register(self, code: str | int) -> Register:
        return self.registers[self.register_pointers.get(code, code)]

    def write_to_register(self, pointer: str | int, data: SupportsBitConversion | Byte):
        (register := self.get_register(pointer)).write(data)
        for k, v in register.children.items():
            self.get_register(k).write(register.bytes[v:])
