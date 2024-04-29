from machine import *


class CherrySyntaxError(SyntaxError):
    pass


class Argument:
    def __init__(self, arg_type: str, value: int):
        self.type = arg_type
        self.value = value

    def __len__(self):
        return 4 if self.type in ("wlit", ) else 2 if self.type in ("mem", ) else 1

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
            return 1 if int("".join(c for c in dl.split(":")[0] if c in "0123456789")) <= 255 else 4

    @staticmethod
    def is_valid_dec_literal(dl: str):
        if not re.fullmatch(r"(?i)d[0-9]{1,3}(_?[0-9]{3})*(:[124])?", dl):
            return False
        n = int("".join(c for c in dl.split(":")[0] if c in "0123456789"))
        length = Assembler.read_dec_literal_length(dl)
        return n <= 2 ** (length * 8) - 1

    @staticmethod
    def is_valid_hex_literal(hl: str):
        return bool(re.fullmatch(r"(?i)h[a-f0-9]{2}((_[a-f0-9]{2})*|([a-f0-9]{2})*)", hl))

    def interpret_argument(self, argument: str) -> Argument:
        """Converts an argument written in assembly into an Argument object containing its type and value.

        Throws a CherrySyntaxError if the argument is invalid, and thus doubles as an argument validator."""

        if argument.upper() in self.register_names:
            reg = self.register_names[argument.upper()]
            return Argument(f"{'w' if reg.size == 4 else 'b'}reg", reg.pointer)

        elif re.match(r"[bB]", argument):
            if not self.is_valid_byte_literal(argument):
                raise CherrySyntaxError(f"Invalid byte literal {self.on_line_x}: {argument}")
            bts = re.findall(r"[01]{8}(?=(_?[01]{8})*$)", argument)
            if len(bts) == 1:
                return Argument("blit", int(argument[1:], 2))
            elif len(bts) == 4:
                return Argument("wlit", int("".join(g for g in argument[1:].split("_")[::-1]), 2))
            else:
                raise CherrySyntaxError(f"Invalid literal length {self.on_line_x}: {argument}")

        elif re.match(r"[dD]", argument):
            if not self.is_valid_dec_literal(argument):
                raise CherrySyntaxError(f"Invalid decimal integer {self.on_line_x}: {argument}")
            bts = self.read_dec_literal_length(argument)
            if bts == 1:
                return Argument("blit", int(re.sub(r"[^0-9]", "", argument.split(":")[0])))
            elif bts == 4:
                return Argument("wlit", int(re.sub(r"[^0-9]", "", argument.split(":")[0])))
            else:
                raise CherrySyntaxError(f"Invalid literal length {self.on_line_x}: {argument}")

        elif re.match(r"[hH]", argument):
            if not self.is_valid_hex_literal(argument):
                raise CherrySyntaxError(f"Invalid hex literal {self.on_line_x}: {argument}")
            bts = re.findall(r"(?i)[a-f0-9]{2}(?=(_?[a-f0-9]{2})*$)", argument)
            if len(bts) == 1:
                return Argument("blit", int(argument[1:], 16))
            elif len(bts) == 4:
                return Argument("wlit", int("".join(g for g in argument[1:].split("_")[::-1]), 16))
            else:
                raise CherrySyntaxError(f"Invalid literal length {self.on_line_x}: {argument}")

        elif argument.startswith("#"):
            if re.match(r"#[dD]", argument):
                if not re.fullmatch(r"#[dD][0-9]{1,3}(_?[0-9]{3})*", argument):
                    raise CherrySyntaxError(f"Invalid decimal memory address {self.on_line_x}: {argument}")
                return Argument("mem", int(re.sub(r"[^0-9]", "", argument[2:])))
            elif re.match(r"#[hH]", argument):
                if not re.fullmatch(r"(?i)#h[a-f0-9]{1,3}(_?[a-f0-9]{3})*", argument):
                    raise CherrySyntaxError(f"Invalid hexadecimal memory address {self.on_line_x}: {argument}")
                return Argument("mem", int(re.sub(r"(?i)[^a-f0-9]", "", argument[2:]), 16))

        elif argument.startswith("@"):
            if (reg := argument[1:].upper()) not in self.register_names:
                raise CherrySyntaxError(f"Invalid register name {self.on_line_x}: {argument}")
            return Argument("indr", self.register_names[reg].pointer)

        else:
            raise CherrySyntaxError(f"Invalid argument {self.on_line_x}: {argument}")

    @staticmethod
    def assemble_op_add(primary: Argument, secondary: Argument) -> bytes:
        ret = [0 for _ in range(8)]
        ret[0:3] = convert_to_bits(secondary.value, 3)  # converting register pointer to bits
        if primary.type.endswith("reg") or primary.type == "indr":
            ret[3:6] = convert_to_bits(primary.value, 3)
            ret[6:8] = [int(primary.type == "indr"), int(secondary.type == "indr")]
        else:
            if primary.type.endswith("lit"):
                ret[3:6] = [1, 0, 0]
            elif primary.type == "mem":
                ret[3:6] = [0, 0, 1]
            ret[6:8] = [1, 1]
        return bytes(Byte(ret))

    def assemble_instruction(self, raw_instruction: str) -> bytes:
        s = raw_instruction.split("%")[0].strip()  # remove comments and trailing spaces
        if not (mnemonic := re.match(r"(?i)[A-Z\-]+( +|$)", s)):
            raise CherrySyntaxError(f"No mnemonic {self.on_line_x}: {raw_instruction}")

        if " " not in s:
            mnemonic, raw_args = mnemonic[0].strip().upper(), []
        else:
            mnemonic, raw_args = mnemonic[0].strip().upper(), re.split(r", *| +", s[len(mnemonic[0]):])
        if mnemonic not in self.valid_mnemonics:
            raise CherrySyntaxError(f"Invalid mnemonic {self.on_line_x}: {raw_instruction}")

        correct_arg_count = self.vague_mnemonics[mnemonic] if mnemonic in self.vague_mnemonics \
            else len(self.mnemonics[mnemonic].args)
        if len(raw_args) != correct_arg_count:
            raise CherrySyntaxError(f"{mnemonic} expected {correct_arg_count} arguments and got {len(raw_args)} "
                                    f"{self.on_line_x}: {raw_instruction}")

        opcode = 0
        args = [self.interpret_argument(g) for g in raw_args]
        op_add = bytearray([])
        givens = bytearray([])

        if mnemonic in self.vague_mnemonics:
            if mnemonic == "PUSH":
                if args[0].type not in ("blit", "breg", "wlit", "wreg"):
                    raise CherrySyntaxError(f"Invalid argument type {self.on_line_x}: {raw_args[0]}")
                opcode = self.mnemonics[f"{mnemonic}-{args[0].type[1].upper()}{args[0].type[0].upper()}"].code

            elif mnemonic == "POP":
                if args[0].type not in ("breg", "wreg"):
                    raise CherrySyntaxError(f"Invalid argument type {self.on_line_x}: {raw_args[0]}")
                opcode = self.mnemonics[f"{mnemonic}-{args[0].type[0].upper()}"].code

            elif mnemonic == "MOV":
                if args[1].type in ("indr", "mem"):
                    operand_size = args[0].type[0].upper()
                    if args[0].type not in ("blit", "breg", "wlit", "wreg"):
                        raise CherrySyntaxError(f"Invalid argument type {self.on_line_x}: {raw_args[0]}")
                    if args[0].type.endswith("lit"):
                        operand_size = args[0].type[0].upper()
                        givens += bytes(ByteArray(size=len(args[0]), data=args[0].value))
                        if args[1].type == "indr":
                            opcode = self.mnemonics[f"{mnemonic}-LITIND{operand_size}"].code
                        else:
                            opcode = self.mnemonics[f"{mnemonic}-LITMEM{operand_size}"].code
                            givens += bytes(ByteArray(size=2, data=args[1].value))
                    else:
                        opcode = self.mnemonics[f"{mnemonic}-{operand_size}"].code
                        op_add = self.assemble_op_add(*args)
                elif args[1].type.endswith("reg"):
                    operand_size = args[1].type[0].upper()
                    if args[0].type.endswith("lit"):
                        if args[0].type == "wlit" and args[1].type == "breg":
                            raise CherrySyntaxError(f"Mismatched argument length {self.on_line_x}: {raw_instruction}")
                        operand_size = args[0].type[0].upper()
                        givens += bytes(ByteArray(size=len(args[0]), data=args[0].value))
                    elif args[0].type == "mem":
                        givens += bytes(ByteArray(size=2, data=args[0].value))
                    elif args[0].type not in (f"breg", "wreg", "indr"):
                        raise CherrySyntaxError(f"Invalid argument type {self.on_line_x}: {raw_args[0]}")
                    opcode = self.mnemonics[f"{mnemonic}-{operand_size}"].code
                    op_add = self.assemble_op_add(*args)
                else:
                    raise CherrySyntaxError(f"Invalid argument type {self.on_line_x}: {raw_args[1]}")

        else:  # fallback
            opcode = self.mnemonics[mnemonic].code

        instruction = bytearray([opcode])
        return instruction + op_add + givens

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
