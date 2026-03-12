import ctypes
import os
import platform
from ctypes import POINTER, byref, c_char_p, c_int, c_void_p
from pathlib import Path


def _candidate_core_roots() -> list[Path]:
    roots: list[Path] = []
    seen: set[str] = set()

    env_root = os.getenv("AHRI_TRE_C_ROOT")
    if env_root:
        env_path = Path(env_root).expanduser().resolve()
        roots.append(env_path)
        seen.add(str(env_path))

    anchors = [Path(__file__).resolve()]
    anchors.extend(Path(__file__).resolve().parents)

    sibling_names = ["AHRI_TRE.C", "AHRI_TRE.c", "AHRI_TRE.jl"]
    for anchor in anchors:
        for sibling_name in sibling_names:
            sibling = (anchor.parent / sibling_name).resolve()
            key = str(sibling)
            if key not in seen:
                roots.append(sibling)
                seen.add(key)

    return roots


def _library_candidates_for_root(core_root: Path, system: str) -> list[Path]:
    base = core_root / "c_core" / "build"
    if system == "windows":
        return [
            base / "Release" / "ahri_tre_c.dll",
            base / "ahri_tre_c.dll",
        ]
    if system == "darwin":
        return [
            base / "libahri_tre_c.dylib",
            base / "Release" / "libahri_tre_c.dylib",
        ]
    return [
        base / "libahri_tre_c.so",
        base / "Release" / "libahri_tre_c.so",
    ]


def default_library_path() -> str:
    env = os.getenv("AHRI_TRE_C_LIB")
    if env:
        return env

    system = platform.system().lower()

    for root in _candidate_core_roots():
        for candidate in _library_candidates_for_root(root, system):
            if candidate.exists():
                return str(candidate)

    raise FileNotFoundError("Could not find AHRI TRE C shared library. Set AHRI_TRE_C_LIB.")


class AHRI_TRE_C:
    def __init__(self, library_path: str | None = None):
        self.lib = ctypes.CDLL(str(Path(library_path or default_library_path()).resolve()))

        self.lib.version.restype = c_char_p
        self.lib.last_error.restype = c_char_p

        self.lib.sha256_file_hex.argtypes = [c_char_p, POINTER(c_void_p)]
        self.lib.sha256_file_hex.restype = c_int

        self.lib.verify_sha256_file.argtypes = [c_char_p, c_char_p, POINTER(c_int)]
        self.lib.verify_sha256_file.restype = c_int

        self.lib.path_to_file_uri.argtypes = [c_char_p, POINTER(c_void_p)]
        self.lib.path_to_file_uri.restype = c_int

        self.lib.file_uri_to_path.argtypes = [c_char_p, POINTER(c_void_p)]
        self.lib.file_uri_to_path.restype = c_int

        self.lib.is_ncname.argtypes = [c_char_p, c_int, POINTER(c_int)]
        self.lib.is_ncname.restype = c_int

        self.lib.to_ncname.argtypes = [c_char_p, c_char_p, c_char_p, c_int, c_int, POINTER(c_void_p)]
        self.lib.to_ncname.restype = c_int

        self.lib.parse_flavour.argtypes = [c_char_p, POINTER(c_int)]
        self.lib.parse_flavour.restype = c_int

        self.lib.map_sql_type_to_tre.argtypes = [c_char_p, POINTER(c_int)]
        self.lib.map_sql_type_to_tre.restype = c_int

        self.lib.extract_table_from_sql.argtypes = [c_char_p, POINTER(c_void_p)]
        self.lib.extract_table_from_sql.restype = c_int

        self.lib.parse_in_list_values_json.argtypes = [c_char_p, POINTER(c_void_p)]
        self.lib.parse_in_list_values_json.restype = c_int

        self.lib.parse_check_constraint_values_json.argtypes = [c_char_p, c_char_p, POINTER(c_void_p)]
        self.lib.parse_check_constraint_values_json.restype = c_int

        self.lib.map_value_type.argtypes = [c_char_p, c_char_p, POINTER(c_int), POINTER(c_void_p)]
        self.lib.map_value_type.restype = c_int

        self.lib.parse_redcap_choices_json.argtypes = [c_char_p, POINTER(c_void_p)]
        self.lib.parse_redcap_choices_json.restype = c_int

        self.lib.strip_html.argtypes = [c_char_p, POINTER(c_void_p)]
        self.lib.strip_html.restype = c_int

        self.lib.infer_label_from_field_name.argtypes = [c_char_p, POINTER(c_void_p)]
        self.lib.infer_label_from_field_name.restype = c_int

        self.lib.get_redcap_choices_for_field_json.argtypes = [c_char_p, c_char_p, POINTER(c_void_p)]
        self.lib.get_redcap_choices_for_field_json.restype = c_int

        self.lib.free_ptr.argtypes = [c_void_p]
        self.lib.free_ptr.restype = None

    def version(self) -> str:
        return self.lib.version().decode("utf-8")

    def _raise_last_error(self, code: int):
        raw = self.lib.last_error()
        msg = raw.decode("utf-8") if raw else "Unknown AHRI_TRE C error"
        raise RuntimeError(f"AHRI_TRE C error {code}: {msg}")

    def sha256_file_hex(self, file_path: str) -> str:
        out_ptr = c_void_p()
        code = self.lib.sha256_file_hex(file_path.encode("utf-8"), byref(out_ptr))
        if code != 0:
            self._raise_last_error(code)
        try:
            digest = ctypes.cast(out_ptr, c_char_p).value.decode("utf-8")
        finally:
            self.lib.free_ptr(out_ptr)
        return digest

    def verify_sha256_file(self, file_path: str, expected_hex: str) -> bool:
        out_match = c_int(0)
        code = self.lib.verify_sha256_file(
            file_path.encode("utf-8"), expected_hex.encode("utf-8"), byref(out_match)
        )
        if code != 0:
            self._raise_last_error(code)
        return bool(out_match.value)

    def path_to_file_uri(self, path: str) -> str:
        out_ptr = c_void_p()
        code = self.lib.path_to_file_uri(path.encode("utf-8"), byref(out_ptr))
        if code != 0:
            self._raise_last_error(code)
        try:
            return ctypes.cast(out_ptr, c_char_p).value.decode("utf-8")
        finally:
            self.lib.free_ptr(out_ptr)

    def file_uri_to_path(self, uri: str) -> str:
        out_ptr = c_void_p()
        code = self.lib.file_uri_to_path(uri.encode("utf-8"), byref(out_ptr))
        if code != 0:
            self._raise_last_error(code)
        try:
            return ctypes.cast(out_ptr, c_char_p).value.decode("utf-8")
        finally:
            self.lib.free_ptr(out_ptr)

    def is_ncname(self, value: str, strict: bool = False) -> bool:
        out_valid = c_int(0)
        code = self.lib.is_ncname(value.encode("utf-8"), int(strict), byref(out_valid))
        if code != 0:
            self._raise_last_error(code)
        return bool(out_valid.value)

    def to_ncname(self, value: str, replacement: str = "_", prefix: str = "_", avoid_reserved: bool = True, strict: bool = False) -> str:
        out_ptr = c_void_p()
        code = self.lib.to_ncname(
            value.encode("utf-8"),
            replacement.encode("utf-8"),
            prefix.encode("utf-8"),
            int(avoid_reserved),
            int(strict),
            byref(out_ptr),
        )
        if code != 0:
            self._raise_last_error(code)
        try:
            return ctypes.cast(out_ptr, c_char_p).value.decode("utf-8")
        finally:
            self.lib.free_ptr(out_ptr)

    def strip_html(self, text: str) -> str:
        out_ptr = c_void_p()
        code = self.lib.strip_html(text.encode("utf-8"), byref(out_ptr))
        if code != 0:
            self._raise_last_error(code)
        try:
            return ctypes.cast(out_ptr, c_char_p).value.decode("utf-8")
        finally:
            self.lib.free_ptr(out_ptr)

    def infer_label_from_field_name(self, field_name: str) -> str:
        out_ptr = c_void_p()
        code = self.lib.infer_label_from_field_name(field_name.encode("utf-8"), byref(out_ptr))
        if code != 0:
            self._raise_last_error(code)
        try:
            return ctypes.cast(out_ptr, c_char_p).value.decode("utf-8")
        finally:
            self.lib.free_ptr(out_ptr)

    def get_redcap_choices_for_field_json(self, field_type: str, choices: str | None = None) -> str:
        out_ptr = c_void_p()
        choices_arg = None if choices is None else choices.encode("utf-8")
        code = self.lib.get_redcap_choices_for_field_json(
            field_type.encode("utf-8"),
            choices_arg,
            byref(out_ptr),
        )
        if code != 0:
            self._raise_last_error(code)
        try:
            return ctypes.cast(out_ptr, c_char_p).value.decode("utf-8")
        finally:
            self.lib.free_ptr(out_ptr)
