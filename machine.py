from bytes import *


class OpcodeError(ValueError):
    pass


registers = json.load(open("registers.json"))


class Register:
    def __init__(self, size: int, data: SupportsBitConversion | Byte = 0, children: dict[str, int] = (), **kwargs):
        self.size = size
        self.bits = convert_to_bits(data, length=self.size * 8)
        self.children = dict(children)
        self.name = kwargs.get("name")
        self.pointer = kwargs.get("pointer", 0)

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

    def write_at(self, address: int | ByteArray, data: SupportsBitConversion | Byte, no_bytes: int = 0):
        if isinstance(address, ByteArray):
            address = address.value
        if isinstance(data, ByteArray):
            no_bytes = len(data)
        elif not no_bytes:
            raise ValueError("Must specify the number of bytes to write non-ByteArray objects to registers.")
        self.bits[address*8:(address+no_bytes)*8] = convert_to_bits(data, no_bytes * 8)
        if address + no_bytes > self.size:
            del self.bits[self.size*8:]


class Drive(Register):
    def read(self, address: int | ByteArray, no_bytes: int) -> ByteArray:
        if isinstance(address, ByteArray):
            address = address.value
        return ByteArray.from_bits(self.bits[address * 8:(address + no_bytes) * 8])


# noinspection PyTupleAssignmentBalance
class Machine:
    def __init__(self):
        self.register_names = {g["name"]: Register.from_json(g) for g in registers}
        self.register_pointers = {g["pointer"]: g["name"] for g in registers}
        self.parent_registers = {j: g for g in self.register_names.values() for j in g.children}
        self.memory = Drive(65536)  # just implementing memory as a continuous linear address space w/o paging
        self.operation_counter = 0

    @property
    def state_map(self):
        return f"  [GA] {self.get_register('GA').hex}    [IP] {self.get_register('IP').hex}\n" \
               f"  [GB] {self.get_register('GB').hex}    [SP] {self.get_register('SP').hex}\n" \
               f"  [GC] {self.get_register('GC').hex}    [FL] {self.get_register('FL')}\n" \
               f"  [GD] {self.get_register('GD').hex}\n"

    def get_register(self, code: str | int | Byte) -> Register:
        if isinstance(code, Byte):
            code = code.value
        return self.register_names[self.register_pointers.get(code, code)]

    @property
    def instruction_pointer(self):
        return self.get_register("IP").value

    def write_to_register(self, pointer: str | int | Byte, data: SupportsBitConversion | Byte):
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

    def increment_reg(self, pointer: str | int | Byte, n: int = 1):
        self.write_to_register(pointer, self.get_register(pointer).value + n)

    def read_stack(self, no_bytes: int = 4):
        return self.memory.read(self.get_register("SP").value, no_bytes)

    @property
    def op_add_register_codes(self):
        return "GA", "GB", "GC", "GD", None, None, None, None  # these will be set once i have more registers

    def op_add_primary(self, op_add: Byte) -> tuple[str]:
        if op_add.substring[6:8] == 3:
            return "special", ("none", "given_literal", None, None, "given_address", None, None, None)[op_add.substring[3:6]]
        elif op_add.substring[6:8] == 1:
            return "memory", self.get_register(self.op_add_register_codes[op_add.substring[3:6]]).value
        else:
            return "register", self.op_add_register_codes[op_add.substring[3:6]]

    def op_add_secondary(self, op_add: Byte) -> tuple[str]:
        if op_add.substring[6:8] == 2:
            return "memory", self.get_register(self.op_add_register_codes[op_add.substring[0:3]]).value
        else:
            return "register", self.op_add_register_codes[op_add.substring[0:3]]

    def read_op_add(self, op_add: Byte, which: str, operand_size: int) -> Byte | ByteArray:
        if which == "s":
            src_type, src_value = self.op_add_secondary(op_add)
        else:  # which == "p"
            src_type, src_value = self.op_add_primary(op_add)
            if src_type == "special":
                raise ValueError("Cannot read special operands with read_op_add().")
        if src_type == "register":
            return self.get_register(src_value).bytes[:operand_size]
        elif src_type == "memory":
            return self.memory.read(src_value, operand_size)

    def write_op_add(self, op_add: Byte, which: str, data: ByteArray):
        if which == "s":
            dest_type, dest_value = self.op_add_secondary(op_add)
        else:  # which == "p"
            dest_type, dest_value = self.op_add_primary(op_add)
            if dest_type == "special":
                raise ValueError("Cannot write to special operands with write_op_add().")
        if dest_type == "register":
            self.write_to_register(dest_value, data)
        elif dest_type == "memory":
            self.memory.write_at(dest_value, data)

    def execute_instruction(self, instruction: ByteArray):
        """Executes the instruction written into the given ByteArray.

        This function is an extreme abstraction of the process, obviously."""

        operation = instruction[0]
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
            operand_size = 4 if operation[2] else 1
            if operation.substring[0:2] == 0:
                op_type, op_value = self.op_add_primary(instruction[1])
                if op_type == "special":  # op_type == "special"
                    if op_value == "none":
                        content = ByteArray(operand_size, 0)
                    elif op_value == "given_literal":
                        self.increment_reg("IP", operand_size)
                        content = instruction[2:2 + operand_size]
                    elif op_value == "given_address":
                        self.increment_reg("IP", 2)
                        content = self.memory.read(instruction[2:4].value, operand_size)
                    else:  # in effect would do nothing but should be avoided
                        raise OpcodeError(f"Bad op-add byte encountered at position {self.instruction_pointer+1}.")
                else:
                    content = self.read_op_add(instruction[1], "p", operand_size)

                self.write_op_add(instruction[1], "s", content)


    def run(self, address: int):
        """Runs a program starting at the given memory address."""
        self.write_to_register("IP", address)
        print(f"Initial state:\n{self.state_map}")
        while True:
            next_instruction = self.memory.read(self.instruction_pointer, 16)
            print(f"Instruction {self.operation_counter}: {next_instruction.hex}\n")
            if next_instruction.mnemonic == "HLT":
                break
            else:
                self.execute_instruction(next_instruction)
            self.increment_reg("IP", opcodes[next_instruction.opcode].base_length)
            print(self.state_map)
            self.operation_counter += 1
        print("System halted.")

    def execute_file(self, path: str):
        """Executes a raw bytecode file with the given path."""
        with open(path, "rb") as fp:
            # write file to memory in pages to prevent massive list or I/O operations
            page = 0
            page_length = 4096
            while bts := fp.read(page_length):
                self.memory.write_at(page * page_length, bts, page_length)
                page += 1
        self.run(0)
