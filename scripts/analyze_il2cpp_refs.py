"""Find ARM64 references to IL2CPP metadata string literals.

This is a local reverse-engineering aid. It reads an ELF file through a
read-only mmap and sends small, aligned buffers to Capstone. Capstone's Python
``disasm`` API asks the native library to decode every instruction in the
provided buffer before yielding the first one, so the buffer size is also a
hard bound on its native instruction-array allocation. From the repository
root, run it with local, ignored analysis artifacts, for example::

    uv run python scripts/analyze_il2cpp_refs.py \\
      --binary .local/analysis/libil2cpp.so \\
      --targets .local/analysis/literal-slots.txt \\
      --method-map .local/analysis/method-pointer-map.tsv --progress
"""

from __future__ import annotations

import argparse
import bisect
import json
import mmap
import struct
import sys
import time
from array import array
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, BinaryIO

try:
    from capstone import (  # type: ignore[import-untyped]
        CS_ARCH_ARM64,
        CS_GRP_CALL,
        CS_GRP_JUMP,
        CS_GRP_RET,
        CS_MODE_ARM,
        Cs,
    )
    from capstone.arm64 import (  # type: ignore[import-untyped]
        ARM64_OP_IMM,
        ARM64_OP_MEM,
        ARM64_OP_REG,
    )
except ImportError as exc:  # pragma: no cover - exercised by the CLI environment
    raise SystemExit(
        "Capstone is required for this analysis script; install the project dev "
        "dependencies."
    ) from exc


ELF64_HEADER = struct.Struct("<16sHHIQQQIHHHHHH")
ELF64_SECTION_HEADER = struct.Struct("<IIQQQQIIQQ")
ELFCLASS64 = 2
ELFDATA2LSB = 1
EM_AARCH64 = 183
SHT_PROGBITS = 1
SHF_EXECINSTR = 0x4
SHN_XINDEX = 0xFFFF
DEFAULT_CHUNK_BYTES = 64 * 1024
MAX_CHUNK_BYTES = 256 * 1024
ARM64_INSTRUCTION_BYTES = 4
ARM64_PAGE_SIZE = 1 << 12
ARM64_PAGE_MASK = ~(ARM64_PAGE_SIZE - 1)
PROGRESS_INTERVAL_BYTES = 16 * 1024 * 1024
MAX_SECTION_BYTES = 512 * 1024 * 1024
MAX_SECTION_COUNT = 65_536
MAX_STRING_TABLE_BYTES = 16 * 1024 * 1024
MAX_METHOD_ENTRIES = 2_000_000
MAX_TARGET_COUNT = 256
MAX_RECORDED_SITES_PER_KIND = 256


class ELFMetadataError(ValueError):
    """Raised when an ELF file does not have safe, usable section metadata."""


@dataclass(frozen=True, slots=True)
class ELFSection:
    name: str
    file_offset: int
    virtual_address: int
    size: int
    flags: int
    section_type: int
    alignment: int


@dataclass(frozen=True, slots=True)
class Target:
    label: str
    address: int


@dataclass(frozen=True, slots=True)
class ReferenceSite:
    instruction_address: int
    method_address: int | None
    type_index: int | None


@dataclass(slots=True)
class MatchKind:
    count: int = 0
    sites: list[ReferenceSite] = field(default_factory=list)

    def add(self, site: ReferenceSite) -> None:
        self.count += 1
        if len(self.sites) < MAX_RECORDED_SITES_PER_KIND:
            self.sites.append(site)


@dataclass(slots=True)
class TargetMatches:
    target: Target
    adrp_pages: MatchKind = field(default_factory=MatchKind)
    adr_addresses: MatchKind = field(default_factory=MatchKind)
    add_sub_references: MatchKind = field(default_factory=MatchKind)
    ldr_references: MatchKind = field(default_factory=MatchKind)


@dataclass(frozen=True, slots=True)
class MethodMap:
    addresses: array[int]
    type_indices: array[int]

    def at(self, instruction_address: int) -> tuple[int | None, int | None]:
        index = bisect.bisect_right(self.addresses, instruction_address) - 1
        if index < 0:
            return None, None
        return int(self.addresses[index]), int(self.type_indices[index])


@dataclass(frozen=True, slots=True)
class ScanSummary:
    instruction_count: int
    bytes_processed: int
    peak_rss_kib: int
    elapsed_seconds: float
    section: ELFSection
    matches: dict[str, TargetMatches]


def _read_exact(file: BinaryIO, size: int, description: str) -> bytes:
    data = file.read(size)
    if len(data) != size:
        raise ELFMetadataError(f"truncated ELF while reading {description}")
    return data


def read_executable_section(path: Path, wanted_name: str = "il2cpp") -> ELFSection:
    """Read and validate ELF64 section metadata without loading ELF contents."""
    file_size = path.stat().st_size
    with path.open("rb") as file:
        header_data = _read_exact(file, ELF64_HEADER.size, "ELF header")
        header = ELF64_HEADER.unpack(header_data)
        ident = header[0]
        if ident[:4] != b"\x7fELF":
            raise ELFMetadataError("input is not an ELF file")
        if ident[4] != ELFCLASS64 or ident[5] != ELFDATA2LSB or ident[6] != 1:
            raise ELFMetadataError("expected a little-endian ELF64 file")
        if header[2] != EM_AARCH64:
            raise ELFMetadataError(f"expected AArch64 ELF (machine={header[2]})")
        if header[3] != 1 or header[8] != ELF64_HEADER.size:
            raise ELFMetadataError("unexpected ELF version or header size")

        section_offset = header[6]
        section_entry_size = header[11]
        section_count = header[12]
        string_table_index = header[13]
        if section_entry_size != ELF64_SECTION_HEADER.size:
            raise ELFMetadataError("unexpected ELF section-header entry size")
        if section_offset < ELF64_HEADER.size:
            raise ELFMetadataError("ELF section-header table overlaps the ELF header")
        if section_offset > file_size - ELF64_SECTION_HEADER.size:
            raise ELFMetadataError("ELF section-header table starts outside the file")

        file.seek(section_offset)
        section_zero = ELF64_SECTION_HEADER.unpack(
            _read_exact(file, ELF64_SECTION_HEADER.size, "section header zero")
        )
        if section_count == 0:
            section_count = section_zero[5]
        if string_table_index == SHN_XINDEX:
            string_table_index = section_zero[6]
        if not 0 < section_count <= MAX_SECTION_COUNT:
            raise ELFMetadataError(f"unreasonable ELF section count: {section_count}")
        table_size = section_count * section_entry_size
        if section_offset + table_size > file_size:
            raise ELFMetadataError("ELF section-header table extends past end of file")
        if not 0 <= string_table_index < section_count:
            raise ELFMetadataError("ELF section-name table index is invalid")

        file.seek(section_offset)
        raw_headers = _read_exact(file, table_size, "section-header table")
        headers = list(ELF64_SECTION_HEADER.iter_unpack(raw_headers))
        strings_header = headers[string_table_index]
        strings_offset, strings_size = strings_header[4], strings_header[5]
        if strings_size > MAX_STRING_TABLE_BYTES:
            raise ELFMetadataError(
                "ELF section-name string table is unreasonably large"
            )
        if strings_offset + strings_size > file_size:
            raise ELFMetadataError(
                "ELF section-name string table extends past end of file"
            )
        file.seek(strings_offset)
        names = _read_exact(file, strings_size, "section-name string table")

    matches: list[ELFSection] = []
    for row in headers:
        name_offset, section_type, flags, address, offset, size, _, _, alignment, _ = (
            row
        )
        if name_offset >= len(names):
            raise ELFMetadataError("section name offset is outside its string table")
        end = names.find(b"\0", name_offset)
        if end < 0:
            raise ELFMetadataError("unterminated ELF section name")
        name = names[name_offset:end].decode("ascii", errors="replace")
        if name != wanted_name:
            continue
        if section_type != SHT_PROGBITS:
            raise ELFMetadataError(f"section {wanted_name!r} is not PROGBITS")
        if not flags & SHF_EXECINSTR:
            raise ELFMetadataError(f"section {wanted_name!r} is not executable")
        if not size or size > MAX_SECTION_BYTES:
            raise ELFMetadataError(f"section {wanted_name!r} has unsafe size {size}")
        if offset > file_size or size > file_size - offset:
            raise ELFMetadataError(f"section {wanted_name!r} extends past end of file")
        if address > (1 << 64) - size:
            raise ELFMetadataError(f"section {wanted_name!r} virtual range overflows")
        if (
            address % ARM64_INSTRUCTION_BYTES
            or offset % ARM64_INSTRUCTION_BYTES
            or size % ARM64_INSTRUCTION_BYTES
            or alignment < 4
            or alignment & (alignment - 1)
            or offset % alignment
        ):
            raise ELFMetadataError(f"section {wanted_name!r} is not 4-byte aligned")
        matches.append(
            ELFSection(name, offset, address, size, flags, section_type, alignment)
        )

    if len(matches) != 1:
        raise ELFMetadataError(
            f"expected exactly one executable section named {wanted_name!r}; "
            f"found {len(matches)}"
        )
    return matches[0]


def load_targets(path: Path) -> tuple[Target, ...]:
    """Read ``label address`` rows, ignoring blank lines and comments."""
    targets: list[Target] = []
    labels: set[str] = set()
    addresses: set[int] = set()
    with path.open(encoding="utf-8") as file:
        for line_number, line in enumerate(file, 1):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            fields = stripped.split()
            if len(fields) != 2:
                raise ValueError(f"{path}:{line_number}: expected a label and address")
            label, raw_address = fields
            if label in labels:
                raise ValueError(
                    f"{path}:{line_number}: duplicate target label {label!r}"
                )
            try:
                address = int(raw_address, 0)
            except ValueError as exc:
                raise ValueError(
                    f"{path}:{line_number}: invalid target address"
                ) from exc
            if address < 0 or address >= 1 << 64:
                raise ValueError(
                    f"{path}:{line_number}: target address is out of range"
                )
            if address in addresses:
                raise ValueError(f"{path}:{line_number}: duplicate target address")
            if len(targets) >= MAX_TARGET_COUNT:
                raise ValueError(
                    f"target file exceeds safety limit of {MAX_TARGET_COUNT} entries"
                )
            labels.add(label)
            addresses.add(address)
            targets.append(Target(label, address))
    if not targets:
        raise ValueError(f"no targets found in {path}")
    return tuple(targets)


def load_method_map(path: Path) -> MethodMap:
    """Load the sorted ``method-address type-index`` mapping compactly."""
    addresses: array[int] = array("Q")
    type_indices: array[int] = array("I")
    previous = -1
    with path.open(encoding="ascii") as file:
        for line_number, line in enumerate(file, 1):
            fields = line.split()
            if not fields:
                continue
            if len(fields) != 2:
                raise ValueError(
                    f"{path}:{line_number}: expected method address and type index"
                )
            try:
                address = int(fields[0], 16)
                type_index = int(fields[1], 10)
            except ValueError as exc:
                raise ValueError(
                    f"{path}:{line_number}: invalid method-map row"
                ) from exc
            if address < previous:
                raise ValueError(
                    f"{path}:{line_number}: method map is not address-sorted"
                )
            if not 0 <= address < 1 << 64 or not 0 <= type_index < 1 << 32:
                raise ValueError(f"{path}:{line_number}: method-map value out of range")
            if len(addresses) >= MAX_METHOD_ENTRIES:
                raise ValueError(
                    f"method map exceeds safety limit of {MAX_METHOD_ENTRIES} entries"
                )
            addresses.append(address)
            type_indices.append(type_index)
            previous = address
    if not addresses:
        raise ValueError(f"method map is empty: {path}")
    return MethodMap(addresses, type_indices)


def aligned_chunks(
    source: Any, offset: int, size: int, chunk_size: int
) -> Iterator[tuple[int, bytes]]:
    """Yield bounded ARM64 chunks; 4-byte alignment removes boundary overlap."""
    if (
        chunk_size < ARM64_INSTRUCTION_BYTES
        or chunk_size > MAX_CHUNK_BYTES
        or chunk_size % ARM64_INSTRUCTION_BYTES
    ):
        raise ValueError(
            "chunk size must be a multiple of "
            f"{ARM64_INSTRUCTION_BYTES} from {ARM64_INSTRUCTION_BYTES} to "
            f"{MAX_CHUNK_BYTES}"
        )
    if (
        offset < 0
        or size <= 0
        or offset + size > len(source)
        or size % ARM64_INSTRUCTION_BYTES
    ):
        raise ValueError("code range is outside the source or is not 4-byte aligned")
    relative = 0
    while relative < size:
        length = min(chunk_size, size - relative)
        length -= length % ARM64_INSTRUCTION_BYTES
        if length == 0:
            raise ValueError("code range ended on an incomplete ARM64 instruction")
        start = offset + relative
        yield start, bytes(source[start : start + length])
        relative += length


def _register_index(instruction: Any, register_id: int) -> int | None:
    """Map Xn/Wn names to their shared architectural register number."""
    name = instruction.reg_name(register_id)
    if name == "fp":
        return 29
    if name == "lr":
        return 30
    if len(name) > 1 and name[0] in {"x", "w"} and name[1:].isdigit():
        index = int(name[1:])
        return index if index < 31 else None
    return None


def _site(method_map: MethodMap, address: int) -> ReferenceSite:
    method_address, type_index = method_map.at(address)
    return ReferenceSite(address, method_address, type_index)


def _record_exact(
    address: int,
    instruction_address: int,
    method_map: MethodMap,
    matches: dict[int, TargetMatches],
    kind: str,
) -> None:
    result = matches.get(address)
    if result is not None:
        getattr(result, kind).add(_site(method_map, instruction_address))


def scan_code(
    source: Any,
    section_offset: int,
    section_address: int,
    section_size: int,
    targets: Sequence[Target],
    method_map: MethodMap,
    chunk_size: int = DEFAULT_CHUNK_BYTES,
    progress: bool = False,
) -> tuple[int, dict[str, TargetMatches], int]:
    """Scan an executable region while retaining only bounded match state."""
    by_address = {target.address: TargetMatches(target) for target in targets}
    pages: dict[int, list[TargetMatches]] = {}
    for target in by_address.values():
        pages.setdefault(target.target.address & ~0xFFF, []).append(target)

    decoder = Cs(CS_ARCH_ARM64, CS_MODE_ARM)
    decoder.detail = True
    tracked: dict[int, int] = {}
    method_index = bisect.bisect_left(method_map.addresses, section_address)
    instruction_count = 0
    processed = 0
    next_progress = PROGRESS_INTERVAL_BYTES
    for chunk_file_offset, chunk in aligned_chunks(
        source, section_offset, section_size, chunk_size
    ):
        chunk_address = section_address + chunk_file_offset - section_offset
        decoded = decoder.disasm(chunk, chunk_address)
        chunk_instruction_count = 0
        try:
            for instruction in decoded:
                instruction_count += 1
                chunk_instruction_count += 1
                pc = instruction.address
                processed += ARM64_INSTRUCTION_BYTES
                if method_index < len(method_map.addresses):
                    if method_map.addresses[method_index] == pc:
                        tracked.clear()
                    while (
                        method_index < len(method_map.addresses)
                        and method_map.addresses[method_index] <= pc
                    ):
                        method_index += 1

                operands = instruction.operands
                mnemonic = instruction.mnemonic
                destination: int | None = None
                propagated: int | None = None

                if (
                    mnemonic == "adrp"
                    and len(operands) >= 2
                    and operands[0].type == ARM64_OP_REG
                    and operands[1].type == ARM64_OP_IMM
                ):
                    destination = _register_index(instruction, operands[0].reg)
                    page_address = operands[1].imm & ARM64_PAGE_MASK
                    for match in pages.get(page_address, ()):
                        match.adrp_pages.add(_site(method_map, pc))
                    propagated = page_address
                elif (
                    mnemonic == "adr"
                    and len(operands) >= 2
                    and operands[0].type == ARM64_OP_REG
                    and operands[1].type == ARM64_OP_IMM
                ):
                    destination = _register_index(instruction, operands[0].reg)
                    adr_address = operands[1].imm
                    _record_exact(
                        adr_address, pc, method_map, by_address, "adr_addresses"
                    )
                    propagated = adr_address
                elif (
                    mnemonic in {"add", "sub"}
                    and len(operands) >= 3
                    and operands[0].type == ARM64_OP_REG
                    and operands[1].type == ARM64_OP_REG
                    and operands[2].type == ARM64_OP_IMM
                ):
                    destination = _register_index(instruction, operands[0].reg)
                    source_register = _register_index(instruction, operands[1].reg)
                    source_value = (
                        tracked.get(source_register)
                        if source_register is not None
                        else None
                    )
                    if source_value is not None:
                        displacement = operands[2].imm
                        propagated = (
                            source_value + displacement
                            if mnemonic == "add"
                            else source_value - displacement
                        )
                        _record_exact(
                            propagated, pc, method_map, by_address, "add_sub_references"
                        )
                elif (
                    mnemonic
                    in {
                        "ldr",
                        "ldrb",
                        "ldrh",
                        "ldrsw",
                        "ldrsb",
                        "ldrsh",
                        "ldur",
                        "ldurb",
                        "ldurh",
                        "ldursw",
                        "ldursb",
                        "ldursh",
                    }
                    and len(operands) >= 2
                ):
                    if operands[0].type == ARM64_OP_REG:
                        destination = _register_index(instruction, operands[0].reg)
                    loaded_address: int | None = None
                    if operands[1].type == ARM64_OP_MEM:
                        base_register = _register_index(
                            instruction, operands[1].mem.base
                        )
                        base_value = (
                            tracked.get(base_register)
                            if base_register is not None
                            else None
                        )
                        if base_value is not None and not operands[1].mem.index:
                            loaded_address = base_value + operands[1].mem.disp
                    elif operands[1].type == ARM64_OP_IMM:
                        loaded_address = operands[1].imm
                    if loaded_address is not None:
                        _record_exact(
                            loaded_address, pc, method_map, by_address, "ldr_references"
                        )

                _, written = instruction.regs_access()
                for register_id in written:
                    register = _register_index(instruction, register_id)
                    if register is not None:
                        tracked.pop(register, None)
                if destination is not None and propagated is not None:
                    tracked[destination] = propagated

                if any(
                    instruction.group(group)
                    for group in (CS_GRP_JUMP, CS_GRP_CALL, CS_GRP_RET)
                ):
                    # This linear pass has no control-flow graph, so don't carry
                    # register constants onto another possible path.
                    tracked.clear()

                if progress and processed >= next_progress:
                    print(
                        f"progress: {processed:,}/{section_size:,} bytes; "
                        f"instructions={instruction_count:,}; "
                        f"peak_rss_kib={_peak_rss_kib():,}",
                        file=sys.stderr,
                        flush=True,
                    )
                    next_progress += PROGRESS_INTERVAL_BYTES
        finally:
            decoded.close()
            if "instruction" in locals():
                del instruction
        decoded_bytes = chunk_instruction_count * ARM64_INSTRUCTION_BYTES
        if decoded_bytes != len(chunk):
            raise ValueError(
                f"Capstone decoded {decoded_bytes} of {len(chunk)} "
                f"bytes at 0x{chunk_address:x}"
            )
        del decoded
        del chunk
    return (
        instruction_count,
        {target.label: by_address[target.address] for target in targets},
        processed,
    )


def _peak_rss_kib() -> int:
    """Return this process' max RSS on Linux, where ru_maxrss is in KiB."""
    import resource

    return int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)


def _site_json(site: ReferenceSite) -> dict[str, str | int | None]:
    return {
        "instructionAddress": f"0x{site.instruction_address:x}",
        "methodAddress": (
            f"0x{site.method_address:x}" if site.method_address is not None else None
        ),
        "typeIndex": site.type_index,
    }


def _match_json(matches: TargetMatches) -> dict[str, Any]:
    def encode(kind: MatchKind) -> dict[str, Any]:
        return {"count": kind.count, "sites": [_site_json(site) for site in kind.sites]}

    return {
        "address": f"0x{matches.target.address:x}",
        "adrpPageReferences": encode(matches.adrp_pages),
        "adrReferences": encode(matches.adr_addresses),
        "addSubReferences": encode(matches.add_sub_references),
        "ldrReferences": encode(matches.ldr_references),
    }


def run_scan(
    binary: Path,
    target_file: Path,
    method_map_file: Path,
    chunk_size: int,
    progress: bool,
) -> ScanSummary:
    section = read_executable_section(binary)
    targets = load_targets(target_file)
    method_map = load_method_map(method_map_file)
    started = time.perf_counter()
    with binary.open("rb") as file:
        with mmap.mmap(file.fileno(), 0, access=mmap.ACCESS_READ) as source:
            instruction_count, matches, processed = scan_code(
                source,
                section.file_offset,
                section.virtual_address,
                section.size,
                targets,
                method_map,
                chunk_size=chunk_size,
                progress=progress,
            )
    elapsed = time.perf_counter() - started
    return ScanSummary(
        instruction_count,
        processed,
        _peak_rss_kib(),
        elapsed,
        section,
        matches,
    )


def _summary_json(summary: ScanSummary) -> dict[str, Any]:
    section = summary.section
    return {
        "binary": "local input; no binary contents included",
        "section": {
            "name": section.name,
            "fileOffset": f"0x{section.file_offset:x}",
            "virtualAddress": f"0x{section.virtual_address:x}",
            "sizeBytes": section.size,
        },
        "bytesProcessed": summary.bytes_processed,
        "instructionsDecoded": summary.instruction_count,
        "elapsedSeconds": round(summary.elapsed_seconds, 3),
        "peakRssKiB": summary.peak_rss_kib,
        "matches": {
            label: _match_json(matches) for label, matches in summary.matches.items()
        },
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Find ARM64 references to IL2CPP metadata string literals.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Reads the ELF through a read-only mmap and limits Capstone to small, "
            "aligned buffers.\n"
            "Example:\n"
            "  uv run python scripts/analyze_il2cpp_refs.py \\\n"
            "    --binary .local/analysis/libil2cpp.so \\\n"
            "    --targets .local/analysis/literal-slots.txt \\\n"
            "    --method-map .local/analysis/method-pointer-map.tsv --progress"
        ),
    )
    parser.add_argument("--binary", type=Path, required=True, help="local ELF binary")
    parser.add_argument(
        "--targets", type=Path, required=True, help="literal label/address file"
    )
    parser.add_argument("--method-map", type=Path, required=True)
    parser.add_argument("--chunk-bytes", type=int, default=DEFAULT_CHUNK_BYTES)
    parser.add_argument("--progress", action="store_true")
    parser.add_argument(
        "--output", type=Path, help="write JSON summary to this local path"
    )
    args = parser.parse_args(argv)
    try:
        summary = run_scan(
            args.binary,
            args.targets,
            args.method_map,
            args.chunk_bytes,
            args.progress,
        )
        output = json.dumps(_summary_json(summary), indent=2) + "\n"
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(output, encoding="utf-8")
            print(f"wrote {args.output}")
        else:
            print(output, end="")
        return 0
    except (ELFMetadataError, OSError, ValueError) as exc:
        print(f"analysis error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
