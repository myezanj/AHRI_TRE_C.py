# ahri-tre-c (Python)

Python package for calling the AHRI TRE C core shared library.

This package is designed to call the C core from the AHRI_TRE.C project.

## Install (editable)

```bash
pip install -e .
```

## Build C core first

```bash
cmake -S c_core -B c_core/build
cmake --build c_core/build --config Release
```

If AHRI_TRE.C is a sibling repository, set:

```bash
export AHRI_TRE_C_ROOT=/path/to/AHRI_TRE.C
```

On Windows PowerShell:

```powershell
$env:AHRI_TRE_C_ROOT = "C:\\path\\to\\AHRI_TRE.C"
```

If you already know the compiled shared library path, you can set:

```powershell
$env:AHRI_TRE_C_LIB = "C:\\path\\to\\ahri_tre_c.dll"
```

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
