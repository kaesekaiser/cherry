from bytes import *


registers = json.load(open("registers.json"))


class Register:
    def __init__(self, size: int, data: SupportsBitConversion | Byte = 0, children: dict[str, int] = (), **kwargs):
        self.size = size
        self.bits = convert_to_bits(data, length=self.size * 8)
        self.children = dict(children)
        self.name = kwargs.get("name")

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
        return Register(**js)

    def __getitem__(self, item) -> Byte | ByteArray:
        return self.bytes[item]

    def __str__(self):
        return str(self.bytes)

    def write(self, data: SupportsBitConversion | Byte):
        self.bits = convert_to_bits(data, length=self.size * 8)

    def write_at(self, address: int | ByteArray, data: SupportsBitConversion | Byte, no_bytes: int):
        if isinstance(address, ByteArray):
            address = address.value
        self.bits[address*8:(address+no_bytes)*8] = convert_to_bits(data, no_bytes * 8)
        if address + no_bytes > self.size:
            del self.bits[self.size*8:]


class Drive(Register):
    def read(self, address: int | ByteArray, no_bytes: int) -> ByteArray:
        if isinstance(address, ByteArray):
            address = address.value
        return ByteArray.from_list(self.bits[address*8:(address+no_bytes)*8])


class Machine:
    def __init__(self):
        self.register_names = {g["name"]: Register.from_json(g) for g in registers}
        self.register_pointers = {g["pointer"]: g["name"] for g in registers}
        self.parent_registers = {j: g for g in self.register_names.values() for j in g.children}
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
        return self.register_names[self.register_pointers.get(code, code)]

    def write_to_register(self, pointer: str | int | Byte, data: SupportsBitConversion | Byte):
        if isinstance(pointer, Byte):
            pointer = pointer.value
        (register := self.get_register(pointer)).write(data)
        for k, v in register.children.items():
            self.get_register(k).write(register.bytes[v:])
        if parent := self.parent_registers.get(register.name):
            self.copy_change_to_parent(register, parent)

    def copy_change_to_parent(self, child: Register, parent: Register):
        """When a child register is overwritten, the change is copied over to its parent via this function."""
        parent.write_at(parent.children[child.name], child.value, child.size)
        if grandparent := self.parent_registers.get(parent.name):
            self.copy_change_to_parent(parent, grandparent)

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
            else:
                content = instruction[1:1+length]
            self.write_to_register("SP", self.get_register("SP").value - length)
            self.memory.write_at(self.get_register("SP").value, content, length)

        elif core == "POP":
            length = 4 if suffix[0] == "W" else 1
            self.write_to_register(instruction[1], self.read_stack(length))
            self.write_to_register("SP", self.get_register("SP").value + length)

        elif core == "MOV":
            length = 4 if suffix[2] == "W" else 1
            if suffix[0] == "R":
                content = self.get_register(instruction[1]).bytes
                arg2pos = 2
            elif suffix[0] == "A":
                content = self.memory.read(self.get_register(instruction[1]).bytes, length)
                arg2pos = 2
            elif suffix[0] == "M":
                content = self.memory.read(instruction[1:3], length)
                arg2pos = 3
            else:
                content = instruction[1:1+length]
                arg2pos = 1 + length

            if suffix[1] == "R":
                self.write_to_register(instruction[arg2pos], content)
            elif suffix[1] == "A":
                self.memory.write_at(self.get_register(instruction[arg2pos]).value, content, length)
            else:
                self.memory.write_at(instruction[arg2pos:arg2pos+2], content, length)

    def run(self, address: int):
        """Runs a program starting at the given memory address."""
        self.write_to_register("IP", address)
        print(f"Initial state:\n{self.state_map}")
        while True:
            instruction_pointer = self.get_register("IP").value
            next_instruction = self.memory.read(instruction_pointer, 16)
            print(f"Instruction {self.operation_counter}: {next_instruction.hex}\n")
            if next_instruction.mnemonic == "HLT":
                break
            else:
                self.execute_instruction(next_instruction)
            self.write_to_register("IP", instruction_pointer + opcodes[next_instruction.opcode]["arg_bytes"] + 1)
            print(self.state_map)
            self.operation_counter += 1
        print("System halted.")
