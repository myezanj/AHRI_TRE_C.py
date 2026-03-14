import ctypes
import os
import platform
import re
from ctypes import POINTER, byref, c_char_p, c_int, c_size_t, c_ubyte, c_void_p
from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ColumnInfo:
    name: str
    type_name: str
    nullable: bool = True
    default: str | None = None


class DatabaseFlavour(IntEnum):
    UNKNOWN = 0
    MSSQL = 1
    DUCKDB = 2
    POSTGRESQL = 3
    SQLITE = 4
    MYSQL = 5


def _normalize_remote(remote: str) -> str:
    value = (remote or "").strip()
    if value.endswith(".git"):
        value = value[:-4]
    return value.rstrip("/")


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text or "")


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

    sibling_names = ["AHRI_TRE.c", "AHRI_TRE.C", "AHRI_TRE.jl"]
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
            base / "Release" / "tre_c.dll",
            base / "tre_c.dll",
            base / "Release" / "ahri_tre_c.dll",
            base / "ahri_tre_c.dll",
        ]
    if system == "darwin":
        return [
            base / "libtre_c.dylib",
            base / "Release" / "libtre_c.dylib",
            base / "libahri_tre_c.dylib",
            base / "Release" / "libahri_tre_c.dylib",
        ]
    return [
        base / "libtre_c.so",
        base / "Release" / "libtre_c.so",
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
        self._bound_functions: dict[str, Any] = {}
        self._configure_signatures()

    def _bind_symbol(self, name: str) -> Any:
        fn = self._bound_functions.get(name)
        if fn is not None:
            return fn

        try:
            fn = getattr(self.lib, name)
        except AttributeError:
            try:
                fn = getattr(self.lib, f"ahri_tre_{name}")
            except AttributeError:
                raise

        self._bound_functions[name] = fn
        return fn

    def _require_symbol(self, name: str) -> Any:
        try:
            return self._bind_symbol(name)
        except AttributeError as exc:
            raise NotImplementedError(
                f"C library symbol is unavailable: '{name}' (also tried 'ahri_tre_{name}')"
            ) from exc

    def _configure_signatures(self) -> None:
        specs: list[tuple[str, list[Any], Any]] = [
            ("sha256_file_hex", [c_char_p, POINTER(c_void_p)], c_int),
            ("verify_sha256_file", [c_char_p, c_char_p, POINTER(c_int)], c_int),
            ("path_to_file_uri", [c_char_p, POINTER(c_void_p)], c_int),
            ("file_uri_to_path", [c_char_p, POINTER(c_void_p)], c_int),
            ("emptydir", [c_char_p, c_int, c_int, c_int], c_int),
            ("is_ncname", [c_char_p, c_int, POINTER(c_int)], c_int),
            ("is_start_char", [c_char_p, POINTER(c_int)], c_int),
            ("is_name_char", [c_char_p, c_int, POINTER(c_int)], c_int),
            ("to_ncname", [c_char_p, c_char_p, c_char_p, c_int, c_int, POINTER(c_void_p)], c_int),
            ("parse_flavour", [c_char_p, POINTER(c_int)], c_int),
            ("map_sql_type_to_tre", [c_char_p, POINTER(c_int)], c_int),
            ("map_sql_type_to_tre_for_flavour", [c_char_p, c_int, POINTER(c_int)], c_int),
            ("get_datasetname", [c_char_p, c_char_p, c_int, c_int, c_int, c_int, POINTER(c_void_p)], c_int),
            ("get_datafilename", [c_char_p, c_int, c_int, c_int, POINTER(c_void_p)], c_int),
            (
                "get_datalake_file_path",
                [c_char_p, c_char_p, c_char_p, c_char_p, c_int, c_int, c_int, POINTER(c_void_p)],
                c_int,
            ),
            ("prepare_datafile_digest", [c_char_p, c_char_p, POINTER(c_void_p)], c_int),
            ("prepare_datafile_json", [c_char_p, c_char_p, c_int, c_int, c_char_p, POINTER(c_void_p)], c_int),
            ("dataset_to_arrow_output_path", [c_char_p, c_char_p, c_int, POINTER(c_int), POINTER(c_void_p)], c_int),
            ("dataset_to_csv_output_path", [c_char_p, c_char_p, c_int, c_int, POINTER(c_int), POINTER(c_void_p)], c_int),
            (
                "dataset_to_arrow_write_bytes",
                [c_char_p, c_char_p, POINTER(c_ubyte), c_size_t, c_int, POINTER(c_void_p)],
                c_int,
            ),
            ("dataset_to_csv_write_text", [c_char_p, c_char_p, c_char_p, c_int, POINTER(c_void_p)], c_int),
            (
                "dataset_to_csv_write_bytes",
                [c_char_p, c_char_p, c_int, POINTER(c_ubyte), c_size_t, c_int, POINTER(c_void_p)],
                c_int,
            ),
            ("normalise_orcid_rolename", [c_char_p, POINTER(c_void_p)], c_int),
            ("makeparams_json", [c_int, POINTER(c_void_p)], c_int),
            ("quote_ident", [c_char_p, POINTER(c_void_p)], c_int),
            ("quote_identifier", [c_char_p, c_int, POINTER(c_void_p)], c_int),
            ("quote_sql_str", [c_char_p, POINTER(c_void_p)], c_int),
            ("quote_qualified_identifier", [c_char_p, POINTER(c_void_p)], c_int),
            ("julia_type_to_sql_string", [c_char_p, POINTER(c_void_p)], c_int),
            ("tre_type_to_duckdb_sql", [c_int, POINTER(c_void_p)], c_int),
            ("extract_table_from_sql", [c_char_p, POINTER(c_void_p)], c_int),
            ("parse_in_list_values", [c_char_p, POINTER(c_void_p)], c_int),
            ("parse_in_list_values_json", [c_char_p, POINTER(c_void_p)], c_int),
            ("parse_check_constraint_values", [c_char_p, c_char_p, POINTER(c_void_p)], c_int),
            ("parse_check_constraint_values_json", [c_char_p, c_char_p, POINTER(c_void_p)], c_int),
            ("map_value_type", [c_char_p, c_char_p, POINTER(c_int), POINTER(c_void_p)], c_int),
            ("parse_redcap_choices", [c_char_p, POINTER(c_void_p)], c_int),
            ("parse_redcap_choices_json", [c_char_p, POINTER(c_void_p)], c_int),
            ("strip_html", [c_char_p, POINTER(c_void_p)], c_int),
            ("infer_label_from_field_name", [c_char_p, POINTER(c_void_p)], c_int),
            ("get_redcap_choices_for_field", [c_char_p, c_char_p, POINTER(c_void_p)], c_int),
            ("get_redcap_choices_for_field_json", [c_char_p, c_char_p, POINTER(c_void_p)], c_int),
            ("normalize_git_remote", [c_char_p, POINTER(c_void_p)], c_int),
            ("looks_like_editor_or_julia_internal", [c_char_p, POINTER(c_int)], c_int),
            ("canonical_path", [c_char_p, POINTER(c_void_p)], c_int),
            ("git_commit_info_json", [c_char_p, c_int, c_char_p, POINTER(c_void_p)], c_int),
            ("caller_file_runtime", [c_char_p, POINTER(c_void_p)], c_int),
        ]

        for fn_name in ["version", "last_error"]:
            try:
                fn = self._bind_symbol(fn_name)
                fn.restype = c_char_p
            except AttributeError:
                pass

        for fn_name, argtypes, restype in specs:
            try:
                fn = self._bind_symbol(fn_name)
            except AttributeError:
                continue
            fn.argtypes = argtypes
            fn.restype = restype

        for free_name in ["free", "free_ptr"]:
            try:
                free_fn = self._bind_symbol(free_name)
                free_fn.argtypes = [c_void_p]
                free_fn.restype = None
            except AttributeError:
                continue

    def _free_allocated(self, ptr: c_void_p) -> None:
        for free_name in ["free", "free_ptr"]:
            try:
                self._require_symbol(free_name)(ptr)
                return
            except NotImplementedError:
                continue

    def _call_allocating_utf8(self, fn_name: str, *args: Any) -> str:
        out_ptr = c_void_p()
        code = self._require_symbol(fn_name)(*args, byref(out_ptr))
        if code != 0:
            self._raise_last_error(code)
        try:
            raw = ctypes.cast(out_ptr, c_char_p).value
            return raw.decode("utf-8") if raw else ""
        finally:
            if out_ptr.value:
                self._free_allocated(out_ptr)

    def _call_bool_output(self, fn_name: str, *args: Any) -> bool:
        out_value = c_int(0)
        code = self._require_symbol(fn_name)(*args, byref(out_value))
        if code != 0:
            self._raise_last_error(code)
        return bool(out_value.value)

    def _call_int_output(self, fn_name: str, *args: Any) -> int:
        out_value = c_int(0)
        code = self._require_symbol(fn_name)(*args, byref(out_value))
        if code != 0:
            self._raise_last_error(code)
        return int(out_value.value)

    def _call_status_only(self, fn_name: str, *args: Any) -> None:
        code = self._require_symbol(fn_name)(*args)
        if code != 0:
            self._raise_last_error(code)

    def _bytes_pointer(self, data: bytes | bytearray | memoryview) -> tuple[Any, int]:
        raw = bytes(data)
        array = (c_ubyte * len(raw)).from_buffer_copy(raw)
        return array, len(raw)

    def version(self) -> str:
        raw = self._require_symbol("version")()
        return raw.decode("utf-8") if raw else ""

    def last_error(self) -> str:
        raw = self._require_symbol("last_error")()
        return raw.decode("utf-8") if raw else ""

    def _raise_last_error(self, code: int) -> None:
        msg = self.last_error() or "Unknown AHRI_TRE C error"
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

    def emptydir(self, path: str, create: bool = False, retries: int = 0, wait_millis: int = 0) -> None:
        self._call_status_only("emptydir", path.encode("utf-8"), int(create), retries, wait_millis)

    def is_ncname(self, value: str, strict: bool = False) -> bool:
        return self._call_bool_output("is_ncname", value.encode("utf-8"), int(strict))

    def is_start_char(self, value: str) -> bool:
        return self._call_bool_output("is_start_char", value.encode("utf-8"))

    def is_name_char(self, value: str, strict: bool = False) -> bool:
        return self._call_bool_output("is_name_char", value.encode("utf-8"), int(strict))

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

    def parse_flavour(self, flavour: str) -> DatabaseFlavour:
        return DatabaseFlavour(self._call_int_output("parse_flavour", flavour.encode("utf-8")))

    def map_sql_type_to_tre(self, sql_type: str) -> int:
        return self._call_int_output("map_sql_type_to_tre", sql_type.encode("utf-8"))

    def map_sql_type_to_tre_for_flavour(self, sql_type: str, flavour: int | DatabaseFlavour) -> int:
        return self._call_int_output(
            "map_sql_type_to_tre_for_flavour",
            sql_type.encode("utf-8"),
            int(flavour),
        )

    def get_datasetname(
        self,
        study_name: str,
        asset_name: str,
        major: int,
        minor: int,
        patch: int,
        include_schema: bool = False,
    ) -> str:
        return self._call_allocating_utf8(
            "get_datasetname",
            study_name.encode("utf-8"),
            asset_name.encode("utf-8"),
            major,
            minor,
            patch,
            int(include_schema),
        )

    def get_datafilename(self, asset_name: str, major: int, minor: int, patch: int) -> str:
        return self._call_allocating_utf8(
            "get_datafilename", asset_name.encode("utf-8"), major, minor, patch
        )

    def get_datalake_file_path(
        self,
        lake_data: str,
        study_name: str,
        asset_name: str,
        source_file_path: str,
        major: int,
        minor: int,
        patch: int,
    ) -> str:
        return self._call_allocating_utf8(
            "get_datalake_file_path",
            lake_data.encode("utf-8"),
            study_name.encode("utf-8"),
            asset_name.encode("utf-8"),
            source_file_path.encode("utf-8"),
            major,
            minor,
            patch,
        )

    def prepare_datafile_digest(self, file_path: str, precomputed_digest: str | None = None) -> str:
        digest_arg = None if precomputed_digest is None else precomputed_digest.encode("utf-8")
        return self._call_allocating_utf8(
            "prepare_datafile_digest", file_path.encode("utf-8"), digest_arg
        )

    def prepare_datafile_json(
        self,
        file_path: str,
        edam_format: str,
        compress: bool = False,
        encrypt: bool = False,
        precomputed_digest: str | None = None,
    ) -> str:
        digest_arg = None if precomputed_digest is None else precomputed_digest.encode("utf-8")
        return self._call_allocating_utf8(
            "prepare_datafile_json",
            file_path.encode("utf-8"),
            edam_format.encode("utf-8"),
            int(compress),
            int(encrypt),
            digest_arg,
        )

    def dataset_to_arrow_output_path(
        self, dataset_name: str, outputdir: str, replace: bool = False
    ) -> tuple[str, bool]:
        out_overwrite = c_int(0)
        out_ptr = c_void_p()
        code = self._require_symbol("dataset_to_arrow_output_path")(
            dataset_name.encode("utf-8"),
            outputdir.encode("utf-8"),
            int(replace),
            byref(out_overwrite),
            byref(out_ptr),
        )
        if code != 0:
            self._raise_last_error(code)
        try:
            raw = ctypes.cast(out_ptr, c_char_p).value
            return (raw.decode("utf-8") if raw else "", bool(out_overwrite.value))
        finally:
            if out_ptr.value:
                self._free_allocated(out_ptr)

    def dataset_to_csv_output_path(
        self, dataset_name: str, outputdir: str, compress: bool = False, replace: bool = False
    ) -> tuple[str, bool]:
        out_overwrite = c_int(0)
        out_ptr = c_void_p()
        code = self._require_symbol("dataset_to_csv_output_path")(
            dataset_name.encode("utf-8"),
            outputdir.encode("utf-8"),
            int(compress),
            int(replace),
            byref(out_overwrite),
            byref(out_ptr),
        )
        if code != 0:
            self._raise_last_error(code)
        try:
            raw = ctypes.cast(out_ptr, c_char_p).value
            return (raw.decode("utf-8") if raw else "", bool(out_overwrite.value))
        finally:
            if out_ptr.value:
                self._free_allocated(out_ptr)

    def dataset_to_arrow_write_bytes(
        self, dataset_name: str, outputdir: str, data: bytes | bytearray | memoryview, replace: bool = False
    ) -> str:
        payload, payload_len = self._bytes_pointer(data)
        return self._call_allocating_utf8(
            "dataset_to_arrow_write_bytes",
            dataset_name.encode("utf-8"),
            outputdir.encode("utf-8"),
            payload,
            payload_len,
            int(replace),
        )

    def dataset_to_csv_write_text(
        self, dataset_name: str, outputdir: str, csv_text: str, replace: bool = False
    ) -> str:
        return self._call_allocating_utf8(
            "dataset_to_csv_write_text",
            dataset_name.encode("utf-8"),
            outputdir.encode("utf-8"),
            csv_text.encode("utf-8"),
            int(replace),
        )

    def dataset_to_csv_write_bytes(
        self,
        dataset_name: str,
        outputdir: str,
        data: bytes | bytearray | memoryview,
        compress: bool = False,
        replace: bool = False,
    ) -> str:
        payload, payload_len = self._bytes_pointer(data)
        return self._call_allocating_utf8(
            "dataset_to_csv_write_bytes",
            dataset_name.encode("utf-8"),
            outputdir.encode("utf-8"),
            int(compress),
            payload,
            payload_len,
            int(replace),
        )

    def normalise_orcid_rolename(self, orcid: str) -> str:
        return self._call_allocating_utf8("normalise_orcid_rolename", orcid.encode("utf-8"))

    def makeparams_json(self, n: int) -> str:
        return self._call_allocating_utf8("makeparams_json", n)

    def quote_ident(self, name: str) -> str:
        return self._call_allocating_utf8("quote_ident", name.encode("utf-8"))

    def quote_identifier(self, name: str, flavour: int | DatabaseFlavour) -> str:
        return self._call_allocating_utf8("quote_identifier", name.encode("utf-8"), int(flavour))

    def quote_sql_str(self, value: str) -> str:
        return self._call_allocating_utf8("quote_sql_str", value.encode("utf-8"))

    def quote_qualified_identifier(self, name: str) -> str:
        return self._call_allocating_utf8("quote_qualified_identifier", name.encode("utf-8"))

    def julia_type_to_sql_string(self, julia_type: str) -> str:
        return self._call_allocating_utf8("julia_type_to_sql_string", julia_type.encode("utf-8"))

    def tre_type_to_duckdb_sql(self, value_type_id: int) -> str:
        return self._call_allocating_utf8("tre_type_to_duckdb_sql", value_type_id)

    def extract_table_from_sql(self, sql: str) -> str:
        return self._call_allocating_utf8("extract_table_from_sql", sql.encode("utf-8"))

    def parse_in_list_values(self, values_str: str) -> str:
        return self._call_allocating_utf8("parse_in_list_values", values_str.encode("utf-8"))

    def parse_in_list_values_json(self, values_str: str) -> str:
        return self._call_allocating_utf8("parse_in_list_values_json", values_str.encode("utf-8"))

    def parse_check_constraint_values(self, constraint_def: str, column_name: str) -> str:
        return self._call_allocating_utf8(
            "parse_check_constraint_values",
            constraint_def.encode("utf-8"),
            column_name.encode("utf-8"),
        )

    def parse_check_constraint_values_json(self, constraint_def: str, column_name: str) -> str:
        return self._call_allocating_utf8(
            "parse_check_constraint_values_json",
            constraint_def.encode("utf-8"),
            column_name.encode("utf-8"),
        )

    def map_value_type(self, field_type: str, validation: str | None = None) -> tuple[int, str | None]:
        out_type = c_int(0)
        out_fmt = c_void_p()
        validation_arg = None if validation is None else validation.encode("utf-8")
        try:
            fn = self._require_symbol("map_value_type")
        except NotImplementedError:
            fn = self._require_symbol("map_redcap_value_type")
        code = fn(field_type.encode("utf-8"), validation_arg, byref(out_type), byref(out_fmt))
        if code != 0:
            self._raise_last_error(code)
        try:
            fmt = None
            if out_fmt.value:
                raw = ctypes.cast(out_fmt, c_char_p).value
                fmt = raw.decode("utf-8") if raw else None
            return out_type.value, fmt
        finally:
            if out_fmt.value:
                self._free_allocated(out_fmt)

    def parse_redcap_choices(self, choices: str) -> str:
        return self._call_allocating_utf8("parse_redcap_choices", choices.encode("utf-8"))

    def parse_redcap_choices_json(self, choices: str) -> str:
        return self._call_allocating_utf8("parse_redcap_choices_json", choices.encode("utf-8"))

    def strip_html(self, text: str) -> str:
        return self._call_allocating_utf8("strip_html", text.encode("utf-8"))

    def infer_label_from_field_name(self, field_name: str) -> str:
        return self._call_allocating_utf8("infer_label_from_field_name", field_name.encode("utf-8"))

    def get_redcap_choices_for_field(self, field_type: str, choices: str | None = None) -> str:
        choices_arg = None if choices is None else choices.encode("utf-8")
        return self._call_allocating_utf8(
            "get_redcap_choices_for_field",
            field_type.encode("utf-8"),
            choices_arg,
        )

    def get_redcap_choices_for_field_json(self, field_type: str, choices: str | None = None) -> str:
        choices_arg = None if choices is None else choices.encode("utf-8")
        return self._call_allocating_utf8(
            "get_redcap_choices_for_field_json",
            field_type.encode("utf-8"),
            choices_arg,
        )

    def normalize_git_remote(self, url: str) -> str:
        return self._call_allocating_utf8("normalize_git_remote", url.encode("utf-8"))

    def looks_like_editor_or_julia_internal(self, path: str) -> bool:
        return self._call_bool_output("looks_like_editor_or_julia_internal", path.encode("utf-8"))

    def canonical_path(self, path: str) -> str:
        return self._call_allocating_utf8("canonical_path", path.encode("utf-8"))

    def git_commit_info_json(
        self, dir_path: str, short_hash: bool = False, script_path: str | None = None
    ) -> str:
        script_arg = None if script_path is None else script_path.encode("utf-8")
        return self._call_allocating_utf8(
            "git_commit_info_json", dir_path.encode("utf-8"), int(short_hash), script_arg
        )

    def caller_file_runtime(self, hint_path: str | None = None) -> str:
        hint_arg = None if hint_path is None else hint_path.encode("utf-8")
        return self._call_allocating_utf8("caller_file_runtime", hint_arg)

    def prepare_datafile(
        self,
        file_path: str,
        edam_format: str,
        compress: bool = False,
        encrypt: bool = False,
        precomputed_digest: str | None = None,
    ) -> str:
        return self.prepare_datafile_json(
            file_path,
            edam_format,
            compress=compress,
            encrypt=encrypt,
            precomputed_digest=precomputed_digest,
        )

    def makeparams(self, n: int) -> str:
        return self.makeparams_json(n)

    def map_redcap_value_type(self, field_type: str, validation: str | None = None) -> tuple[int, str | None]:
        return self.map_value_type(field_type, validation)

    def git_commit_info(
        self, dir_path: str, short_hash: bool = False, script_path: str | None = None
    ) -> str:
        return self.git_commit_info_json(dir_path, short_hash=short_hash, script_path=script_path)

    def sha256_digest_hex(self, file_path: str) -> str:
        return self.sha256_file_hex(file_path)

    def verify_sha256_digest(self, file_path: str, expected_hex: str) -> bool:
        return self.verify_sha256_file(file_path, expected_hex)


_HEADER_API_NAMES = [
    "version",
    "last_error",
    "sha256_file_hex",
    "verify_sha256_file",
    "path_to_file_uri",
    "file_uri_to_path",
    "emptydir",
    "is_ncname",
    "is_start_char",
    "is_name_char",
    "to_ncname",
    "parse_flavour",
    "map_sql_type_to_tre",
    "map_sql_type_to_tre_for_flavour",
    "get_datasetname",
    "get_datafilename",
    "get_datalake_file_path",
    "prepare_datafile_digest",
    "prepare_datafile_json",
    "dataset_to_arrow_output_path",
    "dataset_to_csv_output_path",
    "dataset_to_arrow_write_bytes",
    "dataset_to_csv_write_text",
    "dataset_to_csv_write_bytes",
    "normalise_orcid_rolename",
    "makeparams_json",
    "quote_ident",
    "quote_identifier",
    "quote_sql_str",
    "quote_qualified_identifier",
    "julia_type_to_sql_string",
    "tre_type_to_duckdb_sql",
    "extract_table_from_sql",
    "parse_in_list_values",
    "parse_in_list_values_json",
    "parse_check_constraint_values",
    "parse_check_constraint_values_json",
    "map_value_type",
    "parse_redcap_choices",
    "parse_redcap_choices_json",
    "strip_html",
    "infer_label_from_field_name",
    "get_redcap_choices_for_field",
    "get_redcap_choices_for_field_json",
    "normalize_git_remote",
    "looks_like_editor_or_julia_internal",
    "canonical_path",
    "git_commit_info_json",
    "caller_file_runtime",
]

_COMPATIBILITY_ALIAS_NAMES = [
    "prepare_datafile",
    "makeparams",
    "map_redcap_value_type",
    "git_commit_info",
    "sha256_digest_hex",
    "verify_sha256_digest",
]

_MODULE_PROXY_NAMES = [*_HEADER_API_NAMES, *_COMPATIBILITY_ALIAS_NAMES]

_default_client: AHRI_TRE_C | None = None


def _get_default_client() -> AHRI_TRE_C:
    global _default_client
    if _default_client is None:
        _default_client = AHRI_TRE_C()
    return _default_client


def _attach_module_proxy(name: str) -> None:
    if name in globals():
        return

    def _proxy(*args: Any, **kwargs: Any) -> Any:
        method = getattr(_get_default_client(), name)
        return method(*args, **kwargs)

    _proxy.__name__ = name
    globals()[name] = _proxy


for _name in _MODULE_PROXY_NAMES:
    _attach_module_proxy(_name)


__all__ = [
    "AHRI_TRE_C",
    "ColumnInfo",
    "DatabaseFlavour",
    "default_library_path",
    "_normalize_remote",
    "_strip_html",
]
