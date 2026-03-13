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

    module_path = Path(__file__).resolve()
    anchors = [module_path]
    anchors.extend(module_path.parents)

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
        self._bound_functions: dict[str, object] = {}
        self._missing_symbols: set[str] = set()
        self._configure_signatures()

    def _bind_symbol(self, name: str) -> object:
        fn = self._bound_functions.get(name)
        if fn is not None:
            return fn

        try:
            fn = getattr(self.lib, name)
        except AttributeError:
            try:
                fn = getattr(self.lib, f"ahri_tre_{name}")
            except AttributeError:
                self._missing_symbols.add(name)
                raise

        self._bound_functions[name] = fn
        return fn

    def _require_symbol(self, name: str) -> object:
        try:
            return self._bind_symbol(name)
        except AttributeError as exc:
            raise NotImplementedError(
                f"C library symbol is unavailable: '{name}' (also tried 'ahri_tre_{name}')"
            ) from exc

    def _configure_signatures(self) -> None:
        specs: list[tuple[str, list[object], object]] = [
            ("sha256_file_hex", [c_char_p, POINTER(c_void_p)], c_int),
            ("verify_sha256_file", [c_char_p, c_char_p, POINTER(c_int)], c_int),
            ("path_to_file_uri", [c_char_p, POINTER(c_void_p)], c_int),
            ("file_uri_to_path", [c_char_p, POINTER(c_void_p)], c_int),
            ("is_ncname", [c_char_p, c_int, POINTER(c_int)], c_int),
            (
                "to_ncname",
                [c_char_p, c_char_p, c_char_p, c_int, c_int, POINTER(c_void_p)],
                c_int,
            ),
            ("parse_flavour", [c_char_p, POINTER(c_int)], c_int),
            ("map_sql_type_to_tre", [c_char_p, POINTER(c_int)], c_int),
            ("extract_table_from_sql", [c_char_p, POINTER(c_void_p)], c_int),
            ("parse_in_list_values_json", [c_char_p, POINTER(c_void_p)], c_int),
            (
                "parse_check_constraint_values_json",
                [c_char_p, c_char_p, POINTER(c_void_p)],
                c_int,
            ),
            (
                "map_redcap_value_type",
                [c_char_p, c_char_p, POINTER(c_int), POINTER(c_void_p)],
                c_int,
            ),
            ("parse_redcap_choices_json", [c_char_p, POINTER(c_void_p)], c_int),
            ("strip_html", [c_char_p, POINTER(c_void_p)], c_int),
            ("infer_label_from_field_name", [c_char_p, POINTER(c_void_p)], c_int),
            (
                "get_redcap_choices_for_field_json",
                [c_char_p, c_char_p, POINTER(c_void_p)],
                c_int,
            ),
        ]

        try:
            version_fn = self._bind_symbol("version")
            version_fn.restype = c_char_p
        except AttributeError:
            pass

        try:
            last_error_fn = self._bind_symbol("last_error")
            last_error_fn.restype = c_char_p
        except AttributeError:
            pass

        for name, argtypes, restype in specs:
            try:
                fn = self._bind_symbol(name)
            except AttributeError:
                continue
            fn.argtypes = argtypes
            fn.restype = restype

        try:
            free_fn = self._bind_symbol("free")
            free_fn.argtypes = [c_void_p]
            free_fn.restype = None
        except AttributeError:
            pass

    def _call_allocating_utf8(self, fn_name: str, *args: object) -> str:
        out_ptr = c_void_p()
        fn = self._require_symbol(fn_name)
        code = fn(*args, byref(out_ptr))
        if code != 0:
            self._raise_last_error(code)
        try:
            raw = ctypes.cast(out_ptr, c_char_p).value
            return raw.decode("utf-8") if raw else ""
        finally:
            self._require_symbol("free")(out_ptr)

    def version(self) -> str:
        return self._require_symbol("version")().decode("utf-8")

    def _raise_last_error(self, code: int):
        try:
            raw = self._require_symbol("last_error")()
            msg = raw.decode("utf-8") if raw else "Unknown AHRI_TRE C error"
        except NotImplementedError:
            msg = "Unknown AHRI_TRE C error"
        raise RuntimeError(f"AHRI_TRE C error {code}: {msg}")

    def sha256_file_hex(self, file_path: str) -> str:
        return self._call_allocating_utf8("sha256_file_hex", file_path.encode("utf-8"))

    def verify_sha256_file(self, file_path: str, expected_hex: str) -> bool:
        out_match = c_int(0)
        code = self._require_symbol("verify_sha256_file")(
            file_path.encode("utf-8"), expected_hex.encode("utf-8"), byref(out_match)
        )
        if code != 0:
            self._raise_last_error(code)
        return bool(out_match.value)

    def path_to_file_uri(self, path: str) -> str:
        return self._call_allocating_utf8("path_to_file_uri", path.encode("utf-8"))

    def file_uri_to_path(self, uri: str) -> str:
        return self._call_allocating_utf8("file_uri_to_path", uri.encode("utf-8"))

    def is_ncname(self, value: str, strict: bool = False) -> bool:
        out_valid = c_int(0)
        code = self._require_symbol("is_ncname")(value.encode("utf-8"), int(strict), byref(out_valid))
        if code != 0:
            self._raise_last_error(code)
        return bool(out_valid.value)

    def to_ncname(
        self,
        value: str,
        replacement: str = "_",
        prefix: str = "_",
        avoid_reserved: bool = True,
        strict: bool = False,
    ) -> str:
        return self._call_allocating_utf8(
            "to_ncname",
            value.encode("utf-8"),
            replacement.encode("utf-8"),
            prefix.encode("utf-8"),
            int(avoid_reserved),
            int(strict),
        )

    def strip_html(self, text: str) -> str:
        return self._call_allocating_utf8("strip_html", text.encode("utf-8"))

    def infer_label_from_field_name(self, field_name: str) -> str:
        return self._call_allocating_utf8("infer_label_from_field_name", field_name.encode("utf-8"))

    def get_redcap_choices_for_field_json(self, field_type: str, choices: str | None = None) -> str:
        choices_arg = None if choices is None else choices.encode("utf-8")
        return self._call_allocating_utf8(
            "get_redcap_choices_for_field_json",
            field_type.encode("utf-8"),
            choices_arg,
        )
