from bytes import *


class Register:
    def __init__(self, size: int, data: SupportsBitConversion | Byte = 0, children: dict[str, int] = ()):
        self.size = size
        self.bits = convert_to_bits(data, length=self.size * 8)
        self.children = dict(children)

    @property
    def bytes(self):
        return ByteArray(self.size, self.bits)

    @property
    def value(self):
        return self.bytes.value

    @property
    def hex(self):
        return self.bytes.hex

    @staticmethod
    def from_json(js: dict):
        return Register(size=js["size"], data=js.get("data", 0), children=js.get("children", {}))

    def __getitem__(self, item) -> Byte | ByteArray:
        return self.bytes[item]

    def __str__(self):
        return str(self.bytes)

    def write(self, data: SupportsBitConversion | Byte):
        self.bits = convert_to_bits(data, length=self.size * 8)


class Drive(Register):
    def read(self, address: int | ByteArray, no_bytes: int) -> Byte:
        if isinstance(address, ByteArray):
            address = address.value
        return ByteArray.from_list(self.bits[address*8:(address+no_bytes)*8])

    def write_at(self, address: int | ByteArray, data: SupportsBitConversion | Byte, no_bytes: int):
        if isinstance(address, ByteArray):
            address = address.value
        self.bits[address*8:(address+no_bytes)*8] = convert_to_bits(data, no_bytes * 8)
        if address + no_bytes > self.size:
            del self.bits[self.size*8:]


class Machine:
    def __init__(self):
        registers = json.load(open("registers.json"))
        self.registers = {k: Register.from_json(v) for k, v in registers.items()}
        self.register_pointers = {v["pointer"]: k for k, v in registers.items()}
        self.memory = Drive(65536)  # just implementing memory as a continuous linear address space w/o paging
        self.operation_counter = 0

    @property
    def state_map(self):
        return f"  [AG] {self.get_register('AG').hex}    [IP] {self.get_register('IP').hex}\n" \
               f"  [BG] {self.get_register('BG').hex}    [SP] {self.get_register('SP').hex}\n" \
               f"  [CG] {self.get_register('CG').hex}    [FL] {self.get_register('FL')}\n"

    def get_register(self, code: str | int | Byte) -> Register:
        if isinstance(code, Byte):
            code = code.value
        return self.registers[self.register_pointers.get(code, code)]

    def write_to_register(self, pointer: str | int | Byte, data: SupportsBitConversion | Byte):
        if isinstance(pointer, Byte):
            pointer = pointer.value
        (register := self.get_register(pointer)).write(data)
        for k, v in register.children.items():
            self.get_register(k).write(register.bytes[v:])

    def read_stack(self, no_bytes: int = 4):
        return self.memory.read(self.get_register("SP").value, no_bytes)

    def execute_instruction(self, instruction: ByteArray):
        """Executes the instruction written into the given ByteArray.

        This function is an extreme abstraction of the process, obviously."""

        mnemonic = instruction.mnemonic
        core = mnemonic.split("-")[0]
        suffix = mnemonic.split("-")[1] if "-" in mnemonic else ""

        if core == "PUSH":
            length = 4 if suffix[1] == "W" else 1
            if suffix[0] == "R":
                content = self.get_register(instruction[1]).bytes
            elif suffix[0] == "A":
                content = self.memory.read(instruction[1], length)
            else:
                content = instruction[1:1+length]
            self.write_to_register("SP", self.get_register("SP").value - length)
            self.memory.write_at(self.get_register("SP").value, content, length)

        elif core == "POP":
            length = 4 if suffix[0] == "W" else 1
            self.write_to_register(instruction[1], self.read_stack(length))
            self.write_to_register("SP", self.get_register("SP").value + length)

    def run(self, address: int):
        """Runs a program starting at the given memory address."""
        self.write_to_register("IP", address)
        # print(f"Initial state:\n{self.state_map}")
        while True:
            instruction_pointer = self.get_register("IP").value
            next_instruction = self.memory.read(instruction_pointer, 16)
            # print(f"Instruction: {next_instruction.hex}\n")
            if next_instruction.mnemonic == "HLT":
                break
            else:
                self.execute_instruction(next_instruction)
            self.write_to_register("IP", instruction_pointer + opcodes[next_instruction.mnemonic]["arg_bytes"] + 1)
            # print(f"After instruction {self.operation_counter}:\n{self.state_map}")
            self.operation_counter += 1
