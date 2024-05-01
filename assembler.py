from machine import *


space_replace = "冇"


class CherrySyntaxError(SyntaxError):
    pass


class Argument:
    def __init__(self, arg_type: str, value: int | str, **kwargs):
        self.type = arg_type
        self.value = value
        self.lit_size = kwargs.pop("lit_size", 0)

    @staticmethod
    def null():
        return Argument("null", 0)

    def __len__(self):  # length in bytes of the argument passed to the interpreter
        if self.type == "lit":
            return self.lit_size
        else:
            return 2 if self.type in ("mem", ) else 0 if self.type == "null" else 1

    @property
    def size(self) -> int:  # operand size
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
        self.output_length = 0
        self.aliases = {}

    @property
    def on_line_x(self):
        return f"on line {self.line_counter + 1}"

    @property
    def valid_mnemonics(self) -> list:
        return list(self.mnemonics.keys()) + list(self.vague_mnemonics.keys())

    @staticmethod
    def integer_arg_length(arg: str, base: int = 10):
        if ":" in arg:
            return int(arg.split(":")[1])
        else:
            return 1 if -127 <= int(arg.strip("hH"), base) <= 255 else 4

    @staticmethod
    def is_valid_dec_literal(dl: str):
        if not re.fullmatch(r"-?[0-9]+(:[14])?", dl):
            return False
        n = int(dl.split(":")[0])
        length = Assembler.integer_arg_length(dl)
        if n < 0:
            n += 2 ** (length * 8)
        return 0 <= n <= 2 ** (length * 8) - 1

    @staticmethod
    def is_valid_hex_literal(hl: str):
        if not re.fullmatch(r"(?i)[0-9a-f]+h(:[14])?", hl):
            return False
        n = int(hl.split(":")[0][:-1], 16)
        length = Assembler.integer_arg_length(hl, 16)
        return n <= 2 ** (length * 8) - 1

    def interpret_argument(self, argument: str, force_size: int = 0) -> Argument:
        """Converts an argument written in assembly into an Argument object containing its type and value.

        Throws a CherrySyntaxError if the argument is invalid, and thus doubles as an argument validator."""

        if argument.startswith("'") or argument.startswith('"'):
            return Argument(
                "lit", ByteArray.from_ascii(argument[1:-1].replace(space_replace, " ")).value,
                lit_size=force_size if force_size else 4
            )

        elif argument.upper() in self.register_names and self.register_names[argument.upper()].op_add != -1:
            return Argument("reg", self.register_names[argument.upper()].pointer)

        elif argument.lower() in self.aliases:
            return Argument("alias", argument.lower())

        elif re.match(r"[01]{8}[bB]", argument):
            return Argument("lit", int(argument[:-1], 2), lit_size=force_size if force_size else 1)

        elif re.match(r"(?i)[0-9a-f]+h(?=:|$)", argument):
            if not self.is_valid_hex_literal(argument):
                raise CherrySyntaxError(f"Invalid hex literal {self.on_line_x}: {argument}")
            n = int(argument.split(":")[0][:-1], 16)
            bts = self.integer_arg_length(argument, 16)
            if bts in (1, 4):
                return Argument("lit", n, lit_size=force_size if force_size else bts)
            else:
                raise CherrySyntaxError(f"Invalid literal length {self.on_line_x}: {argument}")

        elif argument.startswith("#"):
            if re.fullmatch(r"#[0-9]+", argument):
                return Argument("mem", int(argument[1:]))
            elif re.fullmatch(r"(?i)#[0-9a-f]+h", argument):
                return Argument("mem", int(argument[1:-1], 16))
            else:
                raise CherrySyntaxError(f"Invalid memory address {self.on_line_x}: {argument}")

        elif argument.startswith("@"):
            if (reg := argument[1:].upper()) not in self.register_names:
                raise CherrySyntaxError(f"Invalid register name {self.on_line_x}: {argument}")
            return Argument("indr", self.register_names[reg].pointer)

        elif re.fullmatch(r"-?[0-9]+(:[14])?", argument):
            if not self.is_valid_dec_literal(argument):
                raise CherrySyntaxError(f"Invalid integer literal {self.on_line_x}: {argument}")
            bts = self.integer_arg_length(argument)
            n = int(argument.split(":")[0])
            if n < 0:
                n += 2 ** (bts * 8)
            return Argument("lit", n, lit_size=bts)

        else:
            raise CherrySyntaxError(f"Invalid argument {self.on_line_x}: {argument}")

    def assemble_op_add(self, primary: Argument, secondary: Argument = Argument.null()) -> bytes:
        ret = [0 for _ in range(8)]
        ret[0:3] = convert_to_bits(self.register_pointers[secondary.value].op_add, 3)
        if primary.type == "reg" or primary.type == "indr":
            ret[3:6] = convert_to_bits(self.register_pointers[primary.value].op_add, 3)
            ret[6:8] = [int(primary.type == "indr"), int(secondary.type == "indr")]
        else:
            if primary.type == "lit":
                ret[3:6] = [1, 0, 0]
            elif primary.type == "mem":
                ret[3:6] = [0, 0, 1]
            ret[6:8] = [1, 1]
        return bytes(Byte(ret))

    def common_two_arg_suffix(self, arg1: Argument, arg2: Argument, force_operand_size: int = 0) -> str:
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
        operand_size = force_operand_size if force_operand_size else arg1.size if arg1.size else arg2.size
        return "W" if operand_size == 4 else "B"

    def is_reserved_name(self, alias: str):
        return alias.upper() in self.register_names or alias.upper() in self.valid_mnemonics or \
            self.is_valid_dec_literal(alias) or self.is_valid_hex_literal(alias)

    def find_strings(self, s: str, max_length: int = 0, start_pos: int = 0) -> dict[int, int]:
        if "'" not in s[start_pos:] and '"' not in s[start_pos:]:
            return {}
        nxt, ret = start_pos, {}
        while nxt < len(s):
            if s[nxt] in "'\"":
                if s[nxt] not in s[nxt+1:]:
                    raise CherrySyntaxError(f"No closing quote found for string at position {nxt} {self.on_line_x}.")
                close = nxt + s[nxt+1:].index(s[nxt]) + 1
                content = s[nxt+1:close]
                if max_length and (len(content) > max_length):
                    raise CherrySyntaxError(
                        f"Overlong string found at position {nxt} {self.on_line_x} "
                        f"(length {len(content)}, max allowed {max_length})"
                    )
                if not content.isascii():
                    raise CherrySyntaxError(f"Non-ASCII string found at position {nxt} {self.on_line_x}.")
                ret[nxt] = close + 1
                nxt = close + 1
            else:
                nxt += 1
        return ret

    def assemble_instruction(self, raw_instruction: str) -> bytes:
        """Assembles one line of a file into bytecode."""
        s = raw_instruction.split("//")[0].strip(" \t\n")  # remove comments and trailing whitespace characters
        if not s:
            return
        
        if match := re.match(r"(?i)[a-z_][a-z0-9_\-.]+:", s):
            alias, s = match[0][:-1], s[match.end():].strip()
            if self.is_reserved_name(alias):
                raise CherrySyntaxError(f"Reserved alias {self.on_line_x}: {alias}")
            elif alias.lower() in self.aliases:
                raise CherrySyntaxError(f"Duplicate alias {self.on_line_x}: {alias}")
            self.aliases[alias.lower()] = self.output_length
        if not s:
            return
        
        if not (match := re.match(r"(?i)[A-Z\-]+( +|$)", s)):
            raise CherrySyntaxError(f"No mnemonic {self.on_line_x}: {raw_instruction}")

        for start, stop in self.find_strings(s, max_length=4, start_pos=match.end()).items():
            # replace the spaces in strings with a different character so they don't get split up, then revert later
            s = s[:start] + s[start:stop].replace(" ", space_replace) + s[stop:]

        mnemonic, s = match[0].strip().upper(), s[match.end():]
        if mnemonic.startswith("IF") and mnemonic in self.valid_mnemonics:
            prefix = bytes([self.mnemonics[mnemonic].code])
            if not (match := re.match(r"(?i)[A-Z\-]+( +|$)", s)):
                raise CherrySyntaxError(f"No mnemonic after conditional {self.on_line_x}: {raw_instruction}")
            mnemonic, s = match[0].strip().upper(), s[match.end():]
        else:
            prefix = bytes([])

        if mnemonic not in self.valid_mnemonics:
            raise CherrySyntaxError(f"Invalid mnemonic {self.on_line_x}: {raw_instruction}")

        if "-" in mnemonic:
            if mnemonic.split("-")[1] == "B":
                force_size = 1
            elif mnemonic.split("-")[1] == "W":
                force_size = 4
            else:
                raise CherrySyntaxError(f"Over-specified mnemonic {self.on_line_x}: {raw_instruction}")
            mnemonic = mnemonic.split("-")[0]
        else:
            force_size = 0

        raw_args = re.split(r", *| +", s) if s else []
        correct_arg_count = self.vague_mnemonics[mnemonic] if mnemonic in self.vague_mnemonics \
            else len(self.mnemonics[mnemonic].args)
        if len(raw_args) != correct_arg_count:
            raise CherrySyntaxError(f"{mnemonic} expected {correct_arg_count} arguments and got {len(raw_args)} "
                                    f"{self.on_line_x}: {raw_instruction}")

        args = [self.interpret_argument(g, force_size=force_size) for g in raw_args]
        op_add = bytearray([])
        givens = bytearray([])

        if mnemonic == "PUSH":
            if args[0].type not in ("lit", "reg"):
                raise CherrySyntaxError(f"Invalid argument type {self.on_line_x}: {raw_args[0]}")
            size = force_size if force_size else args[0].size
            opcode = self.mnemonics[f"{mnemonic}-{args[0].type[0].upper()}{'W' if size == 4 else 'B'}"].code

        elif mnemonic == "POP":
            if args[0].type != "reg":
                raise CherrySyntaxError(f"Invalid argument type {self.on_line_x}: {raw_args[0]}")
            size = force_size if force_size else args[0].size
            opcode = self.mnemonics[f"{mnemonic}-{'W' if size == 4 else 'B'}"].code

        elif mnemonic in ("MOV", "ADD", "SUB", "CMP"):  # standard op-add commands
            suffix = self.common_two_arg_suffix(*args, force_operand_size=force_size)
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

        elif mnemonic == "OUT":
            if args[0].type not in ("reg", "indr", "mem", "lit"):
                raise CherrySyntaxError(f"Invalid argument type {self.on_line_x}: {raw_args[0]}")
            operand_size = force_size if force_size else args[0].size if args[0].size else 1
            if args[0].type in ("reg", "indr"):
                suffix = ""
                op_add = self.assemble_op_add(args[0])
            else:
                suffix = "MEM" if args[0].type == "mem" else "LIT"
                givens = bytes(args[0])
            opcode = self.mnemonics[f"{mnemonic}-{suffix}{'W' if operand_size == 4 else 'B'}"].code

        elif mnemonic == "JMP":
            if args[0].type not in ("mem", "alias"):
                raise CherrySyntaxError(f"Invalid argument type {self.on_line_x}: {raw_args[0]}")
            opcode = self.mnemonics[mnemonic].code
            givens = bytes(self.aliases[args[0].value]) if args[0].type == "alias" else bytes(args[0])
        
        elif mnemonic == "JREL":
            if args[0].type != "lit":
                raise CherrySyntaxError(f"Invalid argument type {self.on_line_x}: {raw_args[0]}")
            if args[0].size != 1:
                raise CherrySyntaxError(f"Oversize relative jump {self.on_line_x}: must be between -128 and 127")
            opcode = self.mnemonics[mnemonic].code
            givens = bytes(args[0])

        else:  # fallback
            opcode = self.mnemonics[mnemonic].code

        instruction = bytearray([opcode])
        return prefix + instruction + op_add + givens

    def assemble_file(self, source_path: str, destination_path: str, mode: str = "b"):
        open(destination_path, "w")  # clear output file if it exists
        byte_buffer = bytearray([])
        with open(source_path, encoding="utf8") as src, open(destination_path, "at" if mode == "s" else "ab") as dest:
            for line in src.readlines():
                instruction = self.assemble_instruction(line)
                if instruction:
                    if mode == "s":
                        byte_buffer.extend(instruction)
                        if len(byte_buffer) >= 16:
                            dest.write(byte_buffer[:16].hex(sep=" ").upper() + "\n")
                            byte_buffer = byte_buffer[16:]
                    else:
                        dest.write(instruction)
                    self.output_length += len(instruction)
                self.line_counter += 1
            if mode == "s":
                dest.write(byte_buffer.hex(sep=" ").upper() + "\n")
