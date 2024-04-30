from machine import *


class CherrySyntaxError(SyntaxError):
    pass


class Argument:
    def __init__(self, arg_type: str, value: int, **kwargs):
        self.type = arg_type
        self.value = value
        self.lit_size = kwargs.pop("lit_size", 1)

    def __len__(self):
        if self.type == "lit":
            return self.lit_size
        else:
            return 2 if self.type in ("mem", ) else 1

    @property
    def size(self) -> int:
        if self.type == "lit":
            return self.lit_size
        elif self.type == "reg":
            return register_pointers[self.value].size
        else:
            return 0  # no inherent size, effectively just False

    def __str__(self):
        return f"Type: {self.type} / Value: {self.value} / Bytes: {bytes(self).hex(sep=' ').upper()}"

    def __bytes__(self):
        return bytes(ByteArray(len(self), self.value))


class Assembler:
    def __init__(self):
        self.opcodes = opcodes
        self.mnemonics = {g.mnemonic: g for g in opcodes.values()}
        self.vague_mnemonics = {g.mnemonic.split("-")[0]: len(g.args) for g in opcodes.values() if "-" in g.mnemonic}
        self.register_pointers = {g["pointer"]: Register.from_json(g) for g in registers}
        self.register_names = {g["name"]: Register.from_json(g) for g in registers}
        self.line_counter = 0

    @property
    def on_line_x(self):
        return f"on line {self.line_counter + 1}"

    @property
    def valid_mnemonics(self) -> list:
        return list(self.mnemonics.keys()) + list(self.vague_mnemonics.keys())

    @staticmethod
    def is_valid_byte_literal(bl: str):
        return bool(re.fullmatch(r"(?i)b[01]{8}((_[01]{8})*|([01]{8})*)", bl))

    @staticmethod
    def read_dec_literal_length(dl: str):
        if ":" in dl:
            return int(dl.split(":")[1])
        else:
            return 1 if -127 <= int(dl) <= 255 else 4

    @staticmethod
    def is_valid_dec_literal(dl: str):
        if not re.fullmatch(r"-?[0-9]+(:[14])?", dl):
            return False
        n = int(dl.split(":")[0])
        length = Assembler.read_dec_literal_length(dl)
        if n < 0:
            n += 2 ** (length * 8)
        return 0 <= n <= 2 ** (length * 8) - 1

    @staticmethod
    def is_valid_hex_literal(hl: str):
        return bool(re.fullmatch(r"(?i)h[a-f0-9]{2}((_[a-f0-9]{2})*|([a-f0-9]{2})*)", hl))

    def interpret_argument(self, argument: str) -> Argument:
        """Converts an argument written in assembly into an Argument object containing its type and value.

        Throws a CherrySyntaxError if the argument is invalid, and thus doubles as an argument validator."""

        if argument.upper() in self.register_names and self.register_names[argument.upper()].op_add != -1:
            return Argument(f"reg", self.register_names[argument.upper()].pointer)

        elif re.match(r"[bB]", argument):
            if not self.is_valid_byte_literal(argument):
                raise CherrySyntaxError(f"Invalid byte literal {self.on_line_x}: {argument}")
            bts = re.findall(r"[01]{8}(?=(_?[01]{8})*$)", argument)
            if len(bts) == 1:
                return Argument("lit", int(argument[1:], 2), lit_size=1)
            elif len(bts) == 4:
                return Argument("lit", int("".join(g for g in argument[1:].split("_")[::-1]), 2), lit_size=4)
            else:
                raise CherrySyntaxError(f"Invalid literal length {self.on_line_x}: {argument}")

        elif re.match(r"[hH]", argument):
            if not self.is_valid_hex_literal(argument):
                raise CherrySyntaxError(f"Invalid hex literal {self.on_line_x}: {argument}")
            bts = re.findall(r"(?i)[a-f0-9]{2}(?=(_?[a-f0-9]{2})*$)", argument)
            if len(bts) == 1:
                return Argument("lit", int(argument[1:], 16), lit_size=1)
            elif len(bts) == 4:
                return Argument("lit", int("".join(g for g in argument[1:].split("_")[::-1]), 16), lit_size=4)
            else:
                raise CherrySyntaxError(f"Invalid literal length {self.on_line_x}: {argument}")

        elif argument.startswith("#"):
            if re.match(r"#[0-9]", argument):
                if not re.fullmatch(r"#[0-9]+", argument):
                    raise CherrySyntaxError(f"Invalid decimal memory address {self.on_line_x}: {argument}")
                return Argument("mem", int(argument[1:]))
            elif re.match(r"#[hH]", argument):
                if not re.fullmatch(r"(?i)#h[a-f0-9]{1,3}(_?[a-f0-9]{3})*", argument):
                    raise CherrySyntaxError(f"Invalid hexadecimal memory address {self.on_line_x}: {argument}")
                return Argument("mem", int(re.sub(r"(?i)[^a-f0-9]", "", argument[2:]), 16))

        elif argument.startswith("@"):
            if (reg := argument[1:].upper()) not in self.register_names:
                raise CherrySyntaxError(f"Invalid register name {self.on_line_x}: {argument}")
            return Argument("indr", self.register_names[reg].pointer)

        elif re.fullmatch(r"-?[0-9]+(:[14])?", argument):
            if not self.is_valid_dec_literal(argument):
                raise CherrySyntaxError(f"Invalid integer literal {self.on_line_x}: {argument}")
            bts = self.read_dec_literal_length(argument)
            n = int(argument.split(":")[0])
            if n < 0:
                n += 2 ** (bts * 8)
            if bts == 1:
                return Argument("lit", n, lit_size=1)
            elif bts == 4:
                return Argument("lit", n, lit_size=4)
            else:
                raise CherrySyntaxError(f"Invalid literal length {self.on_line_x}: {argument}")

        else:
            raise CherrySyntaxError(f"Invalid argument {self.on_line_x}: {argument}")

    def assemble_op_add(self, primary: Argument, secondary: Argument) -> bytes:
        ret = [0 for _ in range(8)]
        ret[0:3] = convert_to_bits(self.register_pointers[secondary.value].op_add, 3)
        if primary.type.endswith("reg") or primary.type == "indr":
            ret[3:6] = convert_to_bits(self.register_pointers[primary.value].op_add, 3)
            ret[6:8] = [int(primary.type == "indr"), int(secondary.type == "indr")]
        else:
            if primary.type.endswith("lit"):
                ret[3:6] = [1, 0, 0]
            elif primary.type == "mem":
                ret[3:6] = [0, 0, 1]
            ret[6:8] = [1, 1]
        return bytes(Byte(ret))

    def common_two_arg_suffix(self, arg1: Argument, arg2: Argument) -> str:
        """Gets the mnemonic suffix for common two-arg instructions like MOV and ADD, given their args."""
        valid_pairings = {
            "reg": ("reg", "indr", "mem"),
            "indr": ("reg", ),
            "lit": ("reg", "indr", "mem"),
            "mem": ("reg", )
        }
        if arg2.type not in valid_pairings[arg1.type]:
            raise CherrySyntaxError(
                f"Invalid argument type {self.on_line_x}: "
                f"{arg1.type} must be paired with {', '.join(valid_pairings[arg1.type])}"
            )
        # if arg2.type == "reg" and arg1.size != 0 and arg1.size != arg2.size:
        #     print(f"Mismatched argument sizes {self.on_line_x}. This is legal, but may cause unexpected behavior.")

        if arg1.type == "lit" and arg2.type != "reg":
            return f"LIT{'IND' if arg2.type == 'indr' else 'MEM'}{'W' if arg1.size == 4 else 'B'}"
        operand_size = arg1.size if arg1.size else arg2.size
        return "W" if operand_size == 4 else "B"

    def assemble_instruction(self, raw_instruction: str) -> bytes:
        """Assembles one line of a file into bytecode."""
        s = raw_instruction.split("//")[0].strip()  # remove comments and trailing spaces
        if not (match := re.match(r"(?i)[A-Z\-]+( +|$)", s)):
            raise CherrySyntaxError(f"No mnemonic {self.on_line_x}: {raw_instruction}")

        mnemonic, s = match[0].strip().upper(), s[match.end():]
        if mnemonic.startswith("IF") and mnemonic in self.valid_mnemonics:
            prefix = bytes([self.mnemonics[mnemonic].code])
            if not (match := re.match(r"(?i)[A-Z\-]+( +|$)", s)):
                raise CherrySyntaxError(f"No mnemonic after conditional {self.on_line_x}: {raw_instruction}")
            mnemonic, s = match[0].strip().upper(), s[match.end():]
        else:
            prefix = bytes([])

        raw_args = re.split(r", *| +", s)
        if mnemonic not in self.valid_mnemonics:
            raise CherrySyntaxError(f"Invalid mnemonic {self.on_line_x}: {raw_instruction}")

        correct_arg_count = self.vague_mnemonics[mnemonic] if mnemonic in self.vague_mnemonics \
            else len(self.mnemonics[mnemonic].args)
        if len(raw_args) != correct_arg_count:
            raise CherrySyntaxError(f"{mnemonic} expected {correct_arg_count} arguments and got {len(raw_args)} "
                                    f"{self.on_line_x}: {raw_instruction}")

        opcode = 255
        args = [self.interpret_argument(g) for g in raw_args]
        op_add = bytearray([])
        givens = bytearray([])

        if mnemonic in self.vague_mnemonics:
            if mnemonic == "PUSH":
                if args[0].type not in ("lit", "rag"):
                    raise CherrySyntaxError(f"Invalid argument type {self.on_line_x}: {raw_args[0]}")
                opcode = self.mnemonics[f"{mnemonic}-{args[0].type[1].upper()}{args[0].type[0].upper()}"].code

            elif mnemonic == "POP":
                if args[0].type != "reg":
                    raise CherrySyntaxError(f"Invalid argument type {self.on_line_x}: {raw_args[0]}")
                opcode = self.mnemonics[f"{mnemonic}-{args[0].type[0].upper()}"].code

            elif mnemonic in ("MOV", "ADD", "SUB", "CMP"):  # standard op-add commands
                suffix = self.common_two_arg_suffix(*args)
                opcode = self.mnemonics[f"{mnemonic}-{suffix}"].code
                if suffix in ("B", "W"):
                    op_add = self.assemble_op_add(*args)
                    if args[0].type in ("lit", "mem"):
                        givens = bytes(args[0])
                elif suffix.startswith("LITIND"):
                    op_add = bytes([args[1].value + 184])
                    givens = bytes(args[0])
                elif suffix.startswith("LITMEM"):
                    givens = bytes(args[1]) + bytes(args[0])

        elif mnemonic in ("JMP", "JREL"):
            opcode = self.mnemonics[mnemonic].code
            givens = bytes(args[0])

        else:  # fallback
            opcode = self.mnemonics[mnemonic].code

        instruction = bytearray([opcode])
        return prefix + instruction + op_add + givens

    def assemble_file(self, source_path: str, destination_path: str, mode: str = "b"):
        open(destination_path, "w")  # clear output file if it exists
        byte_buffer = bytearray([])
        with open(source_path) as src, open(destination_path, "at" if mode == "s" else "ab") as dest:
            for line in src.readlines():
                instruction = self.assemble_instruction(line)
                if mode == "s":
                    byte_buffer.extend(instruction)
                    if len(byte_buffer) >= 16:
                        dest.write(byte_buffer[:16].hex(sep=" ").upper() + "\n")
                        byte_buffer = byte_buffer[16:]
                else:
                    dest.write(instruction)
                self.line_counter += 1
            if mode == "s":
                dest.write(byte_buffer.hex(sep=" ").upper() + "\n")
