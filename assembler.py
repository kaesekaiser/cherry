from machine import *
from time import time
import json
import os


space_replace = "冇"
mnemonics = json.load(open("instructions.json", "r"))
mnemonics.update({v["alias"]: v for v in mnemonics.values() if v.get("alias")})


class CherrySyntaxError(SyntaxError):
    pass


class Argument:
    def __init__(self, address_mode: int, value: int):
        self.address_mode = address_mode
        self.value = value

    def __bytes__(self) -> bytes:
        return bytes(ByteArray(2 if self.address_mode == 3 else 1, self.value))


class Assembler:
    register_names = ["A", "B", "C", "D"]

    def __init__(self):
        self.current_line = 0
        self.current_bytecode_length = 0
        self.named_references = {}
        self.ref_sources = {}
        self.ref_destinations = {}

    @property
    def on_line_x(self):
        return f"on line {self.current_line + 1}"

    @staticmethod
    def integer_arg_length(arg: str, base: int = 10):
        if ":" in arg:
            return int(arg.split(":")[1])
        else:
            return 1 if -127 <= int(arg.strip("hH"), base) <= 255 else 4

    @staticmethod
    def is_valid_dec_literal(dl: str):
        return bool(re.fullmatch(r"-?[0-9]+", dl))

    @staticmethod
    def is_valid_hex_literal(hl: str):
        return bool(re.fullmatch(r"(?i)[0-9a-f]+h", hl))

    @staticmethod
    def starts_with_named_ref(line: str) -> re.Match:
        return re.match(r"(?i)[a-z_][a-z0-9_\-.]+:", line)

    def is_reserved_name(self, name: str):
        return name.upper() in self.register_names or name.upper() in mnemonics or \
            self.is_valid_dec_literal(name) or self.is_valid_hex_literal(name)

    @staticmethod
    def format_string_literal(s: str):
        return s.replace("\\n", "\n").replace("\\t", "\t")

    def find_string_literals(self, s: str, max_length: int = 0, start_pos: int = 0) -> dict[int, int]:
        if "'" not in s[start_pos:] and '"' not in s[start_pos:]:
            return {}
        nxt, ret = start_pos, {}
        while nxt < len(s):
            if s[nxt] in "'\"":
                if s[nxt] not in s[nxt+1:]:
                    raise CherrySyntaxError(f"No closing quote found for string at position {nxt} {self.on_line_x}.")
                close = nxt + s[nxt+1:].index(s[nxt]) + 1
                content = self.format_string_literal(s[nxt+1:close])
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

    @staticmethod
    def arg_count(mnemonic: str) -> int:
        return (not isinstance(mnemonics[mnemonic]["register_dyad"], int)) + \
            (not isinstance(mnemonics[mnemonic]["address_dyad"], int))

    def interpret_argument(self, argument: str) -> Argument:
        if re.match(r"[01]{8}[bB]", argument):
            return Argument(0, int(argument[:-1], 2))

        if self.is_valid_hex_literal(argument):
            return Argument(0, int(argument[:-1], 16) % 256)

        elif self.is_valid_dec_literal(argument):
            return Argument(0, int(argument) % 256)

        elif re.match(r"[#@]", argument):
            if re.fullmatch(r"[#@][0-9]+", argument):
                n = int(argument[1:])
            elif re.fullmatch(r"(?i)[#@][0-9a-f]+h", argument):
                n = int(argument[1:-1], 16)
            else:
                raise CherrySyntaxError(f"Invalid memory address {self.on_line_x}: {argument}")
            if not (0 <= n < 65536):
                raise CherrySyntaxError(f"Out-of-bounds reference {self.on_line_x}: {argument}")
            if argument.startswith("@") and n >= 256:
                raise CherrySyntaxError(f"Out-of-bounds indexed reference {self.on_line_x}: {argument}")
            return Argument(2 if argument.startswith("@") else 1 if n < 256 else 3, n)

        else:
            raise CherrySyntaxError(f"Invalid argument {self.on_line_x}: {argument}")

    def assemble_instruction(self, raw_instruction: str) -> bytes:
        """Assembles one line of a file into bytecode."""
        s = raw_instruction.split("//")[0].strip(" \t\n")  # remove comments and trailing whitespace characters
        if not s:
            return bytes()

        if match := self.starts_with_named_ref(s):
            self.ref_destinations[match[0][:-1].lower()] = self.current_bytecode_length
            s = s[match.end():].strip()
        if not s:
            return bytes()

        if not (match := re.match(r"(?i)[A-Z\-]+( +|$)", s)):
            raise CherrySyntaxError(f"No mnemonic {self.on_line_x}: {raw_instruction}")

        for start, stop in self.find_string_literals(s, max_length=4, start_pos=match.end()).items():
            # replace the spaces in strings with a different character so they don't get split up, then revert later
            s = s[:start] + s[start:stop].replace(" ", space_replace) + s[stop:]

        mnemonic, s = match[0].strip().upper(), s[match.end():]
        if mnemonic not in mnemonics:
            raise CherrySyntaxError(f"Invalid mnemonic {self.on_line_x}: {raw_instruction}")
        codes = mnemonics[mnemonic]

        args = re.split(r", *| +", s) if s else []
        correct_arg_count = self.arg_count(mnemonic)
        if len(args) != correct_arg_count:
            raise CherrySyntaxError(f"{mnemonic} expected {correct_arg_count} arguments and got {len(args)} "
                                    f"{self.on_line_x}: {raw_instruction}")

        if codes["register_dyad"] == "register":
            if args[0].upper() not in self.register_names:
                raise CherrySyntaxError(f"{mnemonic} expected register, got \"{args[0]}\" "
                                        f"{self.on_line_x}: {raw_instruction}")
            register_dyad = self.register_names.index(args.pop(0).upper())
        else:
            register_dyad = codes["register_dyad"]

        if codes["address_dyad"] == "address":
            if args[0].lower() in self.named_references:
                self.ref_sources[args[0].lower()] = self.ref_sources.get(args[0].lower(), []) + \
                                                    [self.current_bytecode_length + 1]
                address_dyad = 1
                immediate = bytes([0])
            else:
                argument = self.interpret_argument(args[0])
                if argument.address_mode == codes.get("disallowed_address"):
                    raise CherrySyntaxError(f"Disallowed address mode {argument.address_mode} for {mnemonic} "
                                            f"{self.on_line_x}: {raw_instruction}")
                address_dyad = argument.address_mode
                immediate = bytes(argument)
        else:
            address_dyad = codes["address_dyad"]
            immediate = bytes()

        opcode = codes["nybble"] * 16 + register_dyad * 4 + address_dyad
        return bytes([opcode]) + immediate

    def assemble_file(self, source_path: str, destination_path: str, allow_overwrite: bool = True):
        # find all named references first to allow for non-linear referencing
        print("[SYS] Assembling file...")
        for n, line in enumerate(open(source_path, encoding="utf8")):
            if match := self.starts_with_named_ref(line):
                name, s = match[0][:-1], line[match.end():].strip()
                if self.is_reserved_name(name):
                    raise CherrySyntaxError(f"Reserved name on line {n}: {name}")
                elif name.lower() in self.named_references:
                    raise CherrySyntaxError(f"Duplicate name on line {n}: {name}")
                self.named_references[name.lower()] = -1

        # writing
        temp_path = f"tmp{int(time())}.chy"
        open(temp_path, "w")  # clear temp file if it already exists (for whatever reason)
        try:
            with open(temp_path, "ab") as dest:
                for line in open(source_path, encoding="utf8").readlines():
                    instruction = self.assemble_instruction(line)
                    if instruction:
                        dest.write(instruction)
                        self.current_bytecode_length += len(instruction)
                    self.current_line += 1
        except CherrySyntaxError as e:
            os.remove(temp_path)
            raise e

        # final checks
        try:
            with open(temp_path, "r+b") as fp:
                for name in self.named_references:
                    for location in self.ref_sources.get(name, []):
                        fp.seek(location)
                        fp.write(bytes(Byte(self.ref_destinations[name])))
            try:
                os.rename(temp_path, destination_path)
            except FileExistsError as e:
                if allow_overwrite:
                    os.remove(destination_path)
                    os.rename(temp_path, destination_path)
                else:
                    os.remove(temp_path)
                    raise e
        except CherrySyntaxError as e:
            os.remove(temp_path)
            raise e
        else:
            print(f"[SYS] Assembly completed. Total length: {self.current_bytecode_length} bytes")
