from __future__ import annotations

import struct
from array import array
from pathlib import Path

import pytest
from scripts.analyze_il2cpp_refs import (
    ELF64_HEADER,
    ELF64_SECTION_HEADER,
    ELFMetadataError,
    ELFSection,
    MatchKind,
    MethodMap,
    ReferenceSite,
    Target,
    aligned_chunks,
    read_executable_section,
    scan_code,
)


def _word(value: int) -> bytes:
    return value.to_bytes(4, "little")


def _adrp_x0_page_plus_four_pages() -> bytes:
    # At 0x1000 this constructs the page address 0x5000 in x0.
    return _word(0x90000020)


def _add_x1_x0_0x488() -> bytes:
    return _word(0x91000001 | (0x488 << 10))


def _ldr_x1_x0_0x480() -> bytes:
    return _word(0xF9400001 | (0x90 << 10))


def _mov_x0_x2() -> bytes:
    return _word(0xAA0203E0)


def _branch() -> bytes:
    return _word(0x14000000)


def _map(*rows: tuple[int, int]) -> MethodMap:
    return MethodMap(
        array("Q", (address for address, _ in rows)),
        array("I", (type_index for _, type_index in rows)),
    )


def _scan(code: bytes, chunk_size: int = 64 * 1024):
    targets = (Target("add_target", 0x5488), Target("ldr_target", 0x5480))
    return scan_code(
        code,
        0,
        0x1000,
        len(code),
        targets,
        _map((0x1000, 37)),
        chunk_size=chunk_size,
    )[1]


def _fixture_elf(
    tmp_path: Path,
    *,
    section_size: int | None = None,
    section_address: int = 0x1000,
) -> Path:
    names = b"\0.shstrtab\0il2cpp\0"
    strings_offset = 256
    code_offset = (strings_offset + len(names) + 3) & ~3
    code = b"\x1f\x20\x03\xd5"
    actual_size = len(code) if section_size is None else section_size
    ident = b"\x7fELF" + bytes((2, 1, 1)) + bytes(9)
    header = ELF64_HEADER.pack(
        ident,
        3,
        183,
        1,
        0,
        0,
        ELF64_HEADER.size,
        0,
        ELF64_HEADER.size,
        0,
        0,
        ELF64_SECTION_HEADER.size,
        3,
        1,
    )
    section_zero = ELF64_SECTION_HEADER.pack(0, 0, 0, 0, 0, 0, 0, 0, 0, 0)
    strings_header = ELF64_SECTION_HEADER.pack(
        1, 3, 0, 0, strings_offset, len(names), 0, 0, 1, 0
    )
    code_header = ELF64_SECTION_HEADER.pack(
        11, 1, 4, section_address, code_offset, actual_size, 0, 0, 4, 0
    )
    image = bytearray(code_offset + len(code))
    image[: len(header)] = header
    image[ELF64_HEADER.size : ELF64_HEADER.size + 3 * ELF64_SECTION_HEADER.size] = (
        section_zero + strings_header + code_header
    )
    image[strings_offset : strings_offset + len(names)] = names
    image[code_offset : code_offset + len(code)] = code
    path = tmp_path / "synthetic-arm64.so"
    path.write_bytes(image)
    return path


def test_elf_section_metadata_is_read_without_loading_section(
    tmp_path: Path,
) -> None:
    path = _fixture_elf(tmp_path)

    section = read_executable_section(path)

    assert section == ELFSection("il2cpp", 276, 0x1000, 4, 4, 1, 4)


def test_rejects_section_extending_past_file(tmp_path: Path) -> None:
    path = _fixture_elf(tmp_path, section_size=4096)

    with pytest.raises(ELFMetadataError, match="extends past end of file"):
        read_executable_section(path)


def test_rejects_virtual_section_address_overflow(tmp_path: Path) -> None:
    path = _fixture_elf(tmp_path, section_address=(1 << 64) - 2)

    with pytest.raises(ELFMetadataError, match="virtual range overflows"):
        read_executable_section(path)


def test_rejects_non_aarch64_elf(tmp_path: Path) -> None:
    path = _fixture_elf(tmp_path)
    image = bytearray(path.read_bytes())
    struct.pack_into("<H", image, 18, 62)
    path.write_bytes(image)

    with pytest.raises(ELFMetadataError, match="expected AArch64"):
        read_executable_section(path)


def test_chunks_are_aligned_bounded_and_cover_region_once() -> None:
    source = bytes(range(256)) * 4
    chunks = list(aligned_chunks(source, 4, 100, 20))

    assert [offset for offset, _ in chunks] == [4, 24, 44, 64, 84]
    assert [len(chunk) for _, chunk in chunks] == [20, 20, 20, 20, 20]
    assert b"".join(chunk for _, chunk in chunks) == source[4:104]


def test_chunks_reject_unbounded_or_unaligned_size() -> None:
    with pytest.raises(ValueError, match="multiple of 4"):
        list(aligned_chunks(bytes(16), 0, 16, 6))
    with pytest.raises(ValueError, match="multiple of 4"):
        list(aligned_chunks(bytes(16), 0, 16, 300 * 1024))


def test_retained_reference_sites_are_capped_but_total_is_counted() -> None:
    matches = MatchKind()

    for address in range(300):
        matches.add(ReferenceSite(address, 0, 1))

    assert matches.count == 300
    assert len(matches.sites) == 256


def test_adrp_add_and_ldr_match_correct_absolute_addresses() -> None:
    code = _adrp_x0_page_plus_four_pages() + _add_x1_x0_0x488() + _ldr_x1_x0_0x480()

    matches = _scan(code, chunk_size=4)

    assert matches["add_target"].adrp_pages.count == 1
    assert matches["ldr_target"].adrp_pages.count == 1
    assert matches["add_target"].add_sub_references.count == 1
    assert (
        matches["add_target"].add_sub_references.sites[0].instruction_address == 0x1004
    )
    assert matches["add_target"].add_sub_references.sites[0].method_address == 0x1000
    assert matches["add_target"].add_sub_references.sites[0].type_index == 37
    assert matches["ldr_target"].ldr_references.count == 1
    assert matches["ldr_target"].ldr_references.sites[0].instruction_address == 0x1008


def test_chunked_scan_matches_single_buffer_scan_across_boundary() -> None:
    code = _adrp_x0_page_plus_four_pages() + _add_x1_x0_0x488() + _ldr_x1_x0_0x480()

    whole_buffer = _scan(code, chunk_size=len(code))
    four_byte_chunks = _scan(code, chunk_size=4)

    assert whole_buffer == four_byte_chunks
    assert whole_buffer["add_target"].add_sub_references.count == 1
    assert whole_buffer["ldr_target"].ldr_references.count == 1


def test_register_write_invalidates_adrp_value() -> None:
    code = _adrp_x0_page_plus_four_pages() + _mov_x0_x2() + _add_x1_x0_0x488()

    matches = _scan(code, chunk_size=4)

    assert matches["add_target"].add_sub_references.count == 0


def test_frame_pointer_alias_is_tracked_for_adrp_and_ldr() -> None:
    adrp_x29 = _word(0x9000003D)
    ldr_x1_from_x29_0x640 = _word(0xF9400001 | (29 << 5) | (0xC8 << 10))
    code = adrp_x29 + ldr_x1_from_x29_0x640
    matches = scan_code(
        code,
        0,
        0x1000,
        len(code),
        (Target("frame_target", 0x5640),),
        _map((0x1000, 37)),
        chunk_size=4,
    )[1]

    assert matches["frame_target"].adrp_pages.count == 1
    assert matches["frame_target"].ldr_references.count == 1


def test_adrp_value_survives_unmodified_register_across_instructions() -> None:
    nops = _word(0xD503201F) * 9
    code = _adrp_x0_page_plus_four_pages() + nops + _add_x1_x0_0x488()

    matches = _scan(code, chunk_size=4)

    assert matches["add_target"].add_sub_references.count == 1


def test_branch_clears_linear_register_state() -> None:
    code = _adrp_x0_page_plus_four_pages() + _branch() + _add_x1_x0_0x488()

    matches = _scan(code, chunk_size=4)

    assert matches["add_target"].add_sub_references.count == 0


def test_new_method_boundary_clears_register_state() -> None:
    code = _adrp_x0_page_plus_four_pages() + _add_x1_x0_0x488()

    matches = scan_code(
        code,
        0,
        0x1000,
        len(code),
        (Target("target", 0x5488),),
        _map((0x1000, 37), (0x1004, 38)),
        chunk_size=4,
    )[1]

    assert matches["target"].add_sub_references.count == 0
