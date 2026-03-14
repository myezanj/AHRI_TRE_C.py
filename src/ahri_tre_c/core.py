import ctypes
import os
import platform
import re
from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path
from typing import Any, Callable

from ctypes import POINTER, byref, c_char_p, c_int, c_void_p


@dataclass(frozen=True)
class ColumnInfo:
    name: str
    type_name: str
    nullable: bool = True
    default: str | None = None


class DatabaseFlavour(IntEnum):
    UNKNOWN = 0
    SQLITE = 1
    DUCKDB = 2
    POSTGRES = 3
    MSSQL = 4


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

    # Prefer the current C core repository name first, then legacy fallbacks.
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
        fn = self._require_symbol(fn_name)
        code = fn(*args, byref(out_ptr))
        if code != 0:
            self._raise_last_error(code)
        try:
            raw = ctypes.cast(out_ptr, c_char_p).value
            return raw.decode("utf-8") if raw else ""
        finally:
            if out_ptr.value:
                self._free_allocated(out_ptr)

    def _call_generic_symbol(self, fn_name: str, *args: Any, **kwargs: Any) -> Any:
        if kwargs:
            raise TypeError(f"{fn_name} does not support keyword arguments in generic mode")
        return self._require_symbol(fn_name)(*args)

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

    def parse_in_list_values(self, values_str: str) -> str:
        return self._call_allocating_utf8("parse_in_list_values_json", values_str.encode("utf-8"))

    def parse_check_constraint_values(self, constraint_def: str, column_name: str) -> str:
        return self._call_allocating_utf8(
            "parse_check_constraint_values_json",
            constraint_def.encode("utf-8"),
            column_name.encode("utf-8"),
        )

    def parse_redcap_choices(self, choices: str) -> str:
        return self._call_allocating_utf8("parse_redcap_choices_json", choices.encode("utf-8"))

    def map_value_type(self, field_type: str, validation: str | None = None) -> tuple[int, str | None]:
        out_type = c_int(0)
        out_fmt = c_void_p()
        validation_arg = None if validation is None else validation.encode("utf-8")
        code = self._require_symbol("map_redcap_value_type")(
            field_type.encode("utf-8"),
            validation_arg,
            byref(out_type),
            byref(out_fmt),
        )
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

    def get_redcap_choices_for_field(self, field_type: str, choices: str | None = None) -> str:
        return self.get_redcap_choices_for_field_json(field_type, choices)

    def parse_in_list_values_json(self, values_str: str) -> str:
        return self.parse_in_list_values(values_str)

    def parse_check_constraint_values_json(self, constraint_def: str, column_name: str) -> str:
        return self.parse_check_constraint_values(constraint_def, column_name)

    def parse_redcap_choices_json(self, choices: str) -> str:
        return self.parse_redcap_choices(choices)

    def map_redcap_value_type(self, field_type: str, validation: str | None = None) -> tuple[int, str | None]:
        return self.map_value_type(field_type, validation)


_REQUIRED_API_NAMES = [
    "add_datastore_orcid",
    "add_domain",
    "add_entity",
    "add_entity_relation",
    "add_study",
    "add_study_domain",
    "add_transformation",
    "add_transformation_input",
    "add_transformation_output",
    "add_variable",
    "attach_datafile",
    "attach_datafile_version",
    "caller_file_runtime",
    "closedatastore",
    "connect_mssql",
    "convert_missing_to_string",
    "create_asset",
    "create_dataset_meta",
    "create_duckdb_table_sql",
    "create_lake_database",
    "create_store_database",
    "create_transformation",
    "createassets",
    "createdatastore",
    "createentities",
    "createmapping",
    "createstudies",
    "createtransformations",
    "createvariables",
    "dataset_to_arrow",
    "dataset_to_csv",
    "dataset_to_dataframe",
    "dataset_variables",
    "emptydir",
    "ensure_mssql_driver_registered",
    "ensure_vocabulary",
    "extract_table_from_sql",
    "file_uri_to_path",
    "find_mssql_driver_in_directory",
    "find_system_odbc_driver",
    "get_asset",
    "get_assetversions",
    "get_check_constraint_values",
    "get_code_table_vocabulary",
    "get_column_comment",
    "get_column_type_info",
    "get_datafile",
    "get_datafile_meta",
    "get_datafile_metadata",
    "get_datafilename",
    "get_datalake_file_path",
    "get_dataset",
    "get_dataset_variables",
    "get_dataset_versions",
    "get_datasetname",
    "get_domain",
    "get_domain_variables",
    "get_domainentities",
    "get_domainrelations",
    "get_domains",
    "get_eav_variable_names",
    "get_entity",
    "get_entityrelation",
    "get_enum_values",
    "get_foreign_key_reference",
    "get_latest_version",
    "get_namedkey",
    "get_original_column_type",
    "get_query_columns",
    "get_studies",
    "get_study",
    "get_study_assets",
    "get_study_datafiles",
    "get_study_datasets",
    "get_study_domains",
    "get_study_variables",
    "get_study_variables_df",
    "get_studyid",
    "get_table",
    "get_table_columns",
    "get_variable",
    "get_variable_id",
    "get_vocabularies",
    "get_vocabulary",
    "git_commit_info",
    "ingest_file",
    "ingest_file_version",
    "ingest_redcap_project",
    "initstudytypes",
    "initvalue_types",
    "insertdata",
    "insertwithidentity",
    "is_code_table",
    "is_enum_type",
    "is_ncname",
    "julia_type_to_sql_string",
    "lines",
    "list_domainentities",
    "list_domainrelations",
    "list_study_assets_df",
    "list_study_transformations",
    "load_query",
    "make_asset",
    "makeparams",
    "map_sql_type_to_tre",
    "map_value_type",
    "opendatastore",
    "parse_check_constraint_values",
    "parse_flavour",
    "parse_in_list_values",
    "parse_redcap_choices",
    "path_to_file_uri",
    "prepare_datafile",
    "prepareinsertstatement",
    "prepareselectstatement",
    "quote_ident",
    "quote_identifier",
    "quote_sql_str",
    "read_dataset",
    "redcap_export_eav",
    "redcap_fields",
    "redcap_metadata",
    "redcap_post",
    "redcap_post_tofile",
    "redcap_project_info",
    "redcap_project_info_df",
    "register_datafile",
    "register_dataset",
    "register_redcap_datadictionary",
    "save_asset_version",
    "save_dataset_variables",
    "save_version",
    "savedataframe",
    "selectdataframe",
    "set_version",
    "sha256_digest_hex",
    "sql_meta",
    "sql_to_dataset",
    "table_exists",
    "table_has_primary_key",
    "to_ncname",
    "transaction_begin",
    "transaction_commit",
    "transaction_rollback",
    "transform_eav_to_dataset",
    "transform_eav_to_table",
    "tre_type_to_duckdb_sql",
    "update_domain",
    "update_variable",
    "updatevalues",
    "upsert_entity",
    "upsert_entityrelation",
    "upsert_study",
    "upsert_variable",
    "verify_sha256_digest",
    "vocabulary_items",
    "wrap_query_for_metadata",
    "_normalize_remote",
    "_strip_html",
]


def _attach_generic_method(name: str) -> None:
    if hasattr(AHRI_TRE_C, name):
        return

    def _method(self: AHRI_TRE_C, *args: Any, **kwargs: Any) -> Any:
        return self._call_generic_symbol(name, *args, **kwargs)

    _method.__name__ = name
    _method.__qualname__ = f"AHRI_TRE_C.{name}"
    setattr(AHRI_TRE_C, name, _method)


for _name in sorted(set(_REQUIRED_API_NAMES)):
    if _name.isidentifier():
        _attach_generic_method(_name)


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


for _name in sorted(set(_REQUIRED_API_NAMES)):
    if _name.isidentifier():
        _attach_module_proxy(_name)


_base_exports = [
    "AHRI_TRE_C",
    "ColumnInfo",
    "DatabaseFlavour",
    "default_library_path",
    "_normalize_remote",
    "_strip_html",
]
__all__ = _base_exports
