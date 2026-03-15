import unittest
from pathlib import Path
import sys
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import ahri_tre_c
from ahri_tre_c.core import AHRI_TRE_C, _library_candidates_for_root, default_library_path


class CoreWrapperTests(unittest.TestCase):
    def _make_mock_lib(self) -> Mock:
        lib = Mock()

        def bind(name: str, fn: Mock) -> None:
            setattr(lib, name, fn)
            setattr(lib, f"ahri_tre_{name}", fn)

        bind("version", Mock(return_value=b"0.2.0"))
        bind("last_error", Mock(return_value=b"boom"))

        # Most wrapper methods use an allocated UTF-8 pointer output and return int status.
        for name in [
            "sha256_file_hex",
            "path_to_file_uri",
            "file_uri_to_path",
            "to_ncname",
            "strip_html",
            "infer_label_from_field_name",
            "get_redcap_choices_for_field_json",
            "extract_table_from_sql",
            "parse_in_list_values_json",
            "parse_check_constraint_values_json",
            "map_value_type",
            "parse_redcap_choices_json",
        ]:
            bind(name, Mock(return_value=0))

        bind("parse_flavour", Mock(return_value=0))
        bind("map_sql_type_to_tre", Mock(return_value=0))
        bind("free", Mock(return_value=None))
        bind("free_ptr", Mock(return_value=None))

        def verify_sha256_stub(_path, _expected, out_match_ptr):
            out_match_ptr._obj.value = 1
            return 0

        def is_ncname_stub(_value, _strict, out_valid_ptr):
            out_valid_ptr._obj.value = 1
            return 0

        bind("verify_sha256_file", Mock(side_effect=verify_sha256_stub))
        bind("is_ncname", Mock(side_effect=is_ncname_stub))
        return lib

    @patch("ahri_tre_c.core.ctypes.CDLL")
    def test_version_works_with_mocked_library(self, cdll_mock: Mock):
        cdll_mock.return_value = self._make_mock_lib()
        client = AHRI_TRE_C("dummy.dll")
        self.assertEqual(client.version(), "0.2.0")

    @patch("ahri_tre_c.core.ctypes.CDLL")
    def test_falls_back_to_prefixed_symbols_for_legacy_libraries(self, cdll_mock: Mock):
        legacy = self._make_mock_lib()

        for name in [
            "version",
            "last_error",
            "free",
            "sha256_file_hex",
            "verify_sha256_file",
            "path_to_file_uri",
            "file_uri_to_path",
            "is_ncname",
            "to_ncname",
            "parse_flavour",
            "map_sql_type_to_tre",
            "extract_table_from_sql",
            "parse_in_list_values_json",
            "parse_check_constraint_values_json",
            "map_value_type",
            "parse_redcap_choices_json",
            "strip_html",
            "infer_label_from_field_name",
            "get_redcap_choices_for_field_json",
        ]:
            delattr(legacy, name)

        cdll_mock.return_value = legacy
        client = AHRI_TRE_C("dummy.dll")
        self.assertEqual(client.version(), "0.2.0")

    @patch("ahri_tre_c.core.ctypes.CDLL")
    def test_verify_sha256_file_returns_bool(self, cdll_mock: Mock):
        cdll_mock.return_value = self._make_mock_lib()
        client = AHRI_TRE_C("dummy.dll")
        self.assertTrue(client.verify_sha256_file("a.txt", "abcd"))

    @patch("ahri_tre_c.core.ctypes.CDLL")
    def test_string_methods_delegate_to_shared_allocator_helper(self, cdll_mock: Mock):
        cdll_mock.return_value = self._make_mock_lib()
        client = AHRI_TRE_C("dummy.dll")

        with patch.object(client, "_call_allocating_utf8", return_value="ok") as helper:
            self.assertEqual(client.sha256_file_hex("file.txt"), "ok")
            self.assertEqual(client.path_to_file_uri("C:/x"), "ok")
            self.assertEqual(client.file_uri_to_path("file:///x"), "ok")
            self.assertEqual(client.to_ncname("a b"), "ok")
            self.assertEqual(client.strip_html("<b>x</b>"), "ok")
            self.assertEqual(client.infer_label_from_field_name("my_field"), "ok")
            self.assertEqual(client.get_redcap_choices_for_field_json("radio", "1, Yes"), "ok")

            self.assertEqual(helper.call_count, 7)

    def test_default_library_path_uses_explicit_env_override(self):
        with patch("ahri_tre_c.core.os.getenv", side_effect=lambda k: "C:/x.dll" if k == "AHRI_TRE_C_LIB" else None):
            self.assertEqual(default_library_path(), "C:/x.dll")

    def test_library_candidates_include_expected_filenames(self):
        root = Path("C:/repo/AHRI_TRE.c")
        windows = [str(p).replace("\\", "/") for p in _library_candidates_for_root(root, "windows")]
        linux = [str(p).replace("\\", "/") for p in _library_candidates_for_root(root, "linux")]

        self.assertTrue(any(p.endswith("/c_core/build/Release/tre_c.dll") for p in windows))
        self.assertTrue(any(p.endswith("/c_core/build/libtre_c.so") for p in linux))

    @patch("ahri_tre_c.core.ctypes.CDLL")
    def test_map_value_type_uses_current_upstream_symbol(self, cdll_mock: Mock):
        lib = self._make_mock_lib()

        def map_value_type_stub(_field_type, _validation, out_type_ptr, out_fmt_ptr):
            out_type_ptr._obj.value = 7
            out_fmt_ptr._obj.value = None
            return 0

        lib.map_value_type = Mock(side_effect=map_value_type_stub)
        lib.ahri_tre_map_value_type = lib.map_value_type

        cdll_mock.return_value = lib
        client = AHRI_TRE_C("dummy.dll")
        self.assertEqual(client.map_value_type("radio"), (7, None))

    def test_package_exports_strict_surface(self):
        self.assertIn("version", ahri_tre_c.__all__)
        self.assertIn("quote_identifier", ahri_tre_c.__all__)
        self.assertIn("prepare_datafile", ahri_tre_c.__all__)
        self.assertNotIn("add_study", ahri_tre_c.__all__)
        self.assertNotIn("connect_mssql", ahri_tre_c.__all__)

    def test_module_level_proxy_uses_default_client(self):
        fake_client = Mock()
        fake_client.quote_ident.return_value = '"name"'

        with patch("ahri_tre_c.core._get_default_client", return_value=fake_client):
            self.assertEqual(ahri_tre_c.quote_ident("name"), '"name"')
            fake_client.quote_ident.assert_called_once_with("name")


if __name__ == "__main__":
    unittest.main()
