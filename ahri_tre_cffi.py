from ahri_tre_c import AHRI_TRE_C, default_library_path

__all__ = ["AHRI_TRE_C", "default_library_path"]


def main() -> None:
    """Small local smoke test for the CFFI wrapper."""
    client = AHRI_TRE_C(default_library_path())
    print("version:", client.version())


if __name__ == "__main__":
    main()
