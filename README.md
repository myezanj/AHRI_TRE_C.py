# ahri-tre-c (Python)

Python package for calling the AHRI TRE C core shared library.

This package is designed to call the C core from the AHRI_TRE.c project.

Repository used by default:

- [AHRI_TRE.c](https://github.com/myezanj/AHRI_TRE.c.git)

## C ABI symbol policy

The Python binding now targets Julia-style unprefixed C symbols as the primary API surface (for example: `version`, `last_error`, `map_value_type`).

Prefixed symbols (for example: `ahri_tre_version`, `ahri_tre_last_error`) are still exported by the C core as compatibility aliases and remain safe for existing integrations.

## Install (editable)

```bash
pip install -e .
```

## Build C core first

Keep your local C core checkout up to date before building:

```bash
git -C ../AHRI_TRE.c pull --ff-only
```

```bash
cmake -S c_core -B c_core/build
cmake --build c_core/build --config Release
```

If AHRI_TRE.c is a sibling repository, set:

```bash
export AHRI_TRE_C_ROOT=/path/to/AHRI_TRE.c
```

On Windows PowerShell:

```powershell
$env:AHRI_TRE_C_ROOT = "C:\\path\\to\\AHRI_TRE.c"
```

Preferred shared env alias (also supported):

```powershell
$env:TRE_C_ROOT = "C:\\path\\to\\AHRI_TRE.c"
```

If you already know the compiled shared library path, you can set:

```powershell
$env:AHRI_TRE_C_LIB = "C:\\path\\to\\ahri_tre_c.dll"
```

Preferred shared env alias (also supported):

```powershell
$env:TRE_C_LIB = "C:\\path\\to\\ahri_tre_c.dll"
```

## Shared C version window policy

This wrapper enforces a shared C-core compatibility window at load time so
wrapper releases can remain independent while targeting the same ABI lane.

Defaults:

- `TRE_C_VERSION_MIN=0.2.0`
- `TRE_C_VERSION_MAX=0.2.x`

Supported legacy aliases:

- `AHRI_TRE_C_VERSION_MIN`
- `AHRI_TRE_C_VERSION_MAX`

## Usage

```python
from ahri_tre_c import AHRI_TRE_C, default_library_path

client = AHRI_TRE_C(default_library_path())
print(client.version())
```

You can also set `AHRI_TRE_C_LIB` to override the shared library path directly.

## Development quick check

```bash
python -m compileall src
```
