from bytes import *


class Register:
    def __init__(self, data: SupportsBitConversion | Byte = 0, **kwargs):
        self.size = kwargs.pop("size", 1)
        self.bits = convert_to_bits(data, self.size * 8)

    @property
    def bytes(self):
        return ByteArray.from_bits(self.bits)

    @property
    def value(self):
        return self.bytes.value

    @property
    def hex(self):
        return self.bytes.hex

    def __getitem__(self, item) -> Byte | ByteArray:
        return self.bytes[item]

    def __setitem__(self, key, value):
        self.bytes[key] = value

    def __str__(self):
        return str(self.bytes)

    def write(self, data: SupportsBitConversion | Byte):
        self.bits = convert_to_bits(data, self.size * 8)


class Drive:
    def __init__(self, no_bytes: int):
        self.size = no_bytes
        self.bits = [0 for _ in range(no_bytes * 8)]

    def read_at(self, address: int, no_bytes: int = 2):
        return ByteArray.from_bits(self.bits[address * 8:(address + no_bytes) * 8])

    def write_at(self, address: int, data: ByteArray | SupportsBitConversion, no_bytes: int = 0):
        if isinstance(data, ByteArray):
            no_bytes = len(data)
        elif not no_bytes:
            raise ValueError("Must specify the number of bytes to write non-ByteArray objects to registers.")
        self.bits[address * 8:(address + no_bytes) * 8] = convert_to_bits(data, no_bytes * 8)
        if address + no_bytes > self.size:
            del self.bits[self.size*8:]


class Machine:
    def __init__(self):
        self.memory = Drive(256)
        self.registers = [Register() for _ in range(4)]
        self.flags = {"Z": False, "C": False, "S": False}
        self.instruction_pointer = 0
        self.active = False

    def state_map(self):
        return ("\n".join(f"[{chr(65 + n)}] {g} ({g.value})" for n, g in enumerate(self.registers))) + "\n" + \
            (" ".join(f"{k}: {int(v)}" for k, v in self.flags.items())) + f" IP: {self.instruction_pointer}"

    def set_flag(self, flag: str):
        self.flags[flag] = True

    def clear_flag(self, flag: str):
        self.flags[flag] = False

    def process_instruction(self, instruction: ByteArray):
        print(instruction.hex)
        opcode = instruction[0]
        address_mode, register, nybble = int(opcode[0:2]), int(opcode[2:4]), int(opcode[4:8])
        self.instruction_pointer += 2

        if address_mode == 0:
            external_data = instruction[1]
        elif address_mode == 1:
            external_data = self.memory.read_at(instruction[1].value, 1)
        else:
            external_data = Byte()

        register_data = self.registers[register].bytes

        if opcode == 0:  # HLT
            self.active = False
            return

        if nybble == 2:  # LD
            self.registers[register].write(external_data)

        if nybble == 3:  # ST
            self.memory.write_at(int(instruction[1]), register_data)

        if 4 <= nybble <= 7:  # ADD, SUB
            carry = int(self.flags["C"]) if opcode[4] else 1 if opcode[5] else 0
            result = int(register_data) + int(-external_data if opcode[5] else external_data) + carry
            self.registers[register].write(result)
            self.flags["Z"] = not bool(result % 256)
            self.flags["C"] = result >= 256
            self.flags["S"] = bool((result % 256) // 128)

        if 8 <= nybble <= 10:  # OR, XOR, AND
            result = (register_data | external_data) if nybble == 8 else (register_data ^ external_data) \
                if nybble == 9 else (register_data & external_data)
            self.registers[register].write(result)
            self.flags["Z"] = not bool(result)

        if nybble == 11:  # CMP
            self.flags["Z"] = register_data == external_data
            self.flags["C"] = register_data > external_data
            self.flags["S"] = register_data < external_data

        if nybble >= 14:  # JMP
            if opcode[3:5] == 0 or self.flags[["Z", "C", "S"][int(opcode[3:5]) - 1]] == opcode[2]:
                if address_mode == 0:
                    self.instruction_pointer += (int(instruction[1]) + 128) % 256 - 128
                else:
                    self.instruction_pointer = int(instruction[1])

    def run(self, start_at: int = 0, step_by_step: bool = False):
        self.instruction_pointer = start_at
        self.active = True
        while self.active:
            instruction = self.memory.read_at(self.instruction_pointer)
            self.process_instruction(instruction)
            print(self.state_map() + "\n")
            if step_by_step:
                _ = input()

    def execute_file(self, path: str, start_at: int = 0, step_by_step: bool = False):
        """Executes a raw bytecode file with the given path."""
        print(f"[SYS] Executing file...")
        with open(path, "rb") as fp:
            # write file to memory in pages to prevent massive list or I/O operations
            page = 0
            page_length = 4096
            while bts := fp.read(page_length):
                self.memory.write_at(page * page_length + start_at, bts, page_length)
                page += 1
        self.run(start_at, step_by_step)
