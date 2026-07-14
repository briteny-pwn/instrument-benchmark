# Task Goal

Create `solution.py`. Connect to the simulator, discover and identify the
spectrometer, set its central wavelength to 550.0 nm, trigger one measurement,
wait for completion, read the wavelength and count arrays, calculate the point
count, peak wavelength, peak count, and integrated counts, then close all
resources.

# Output Format

Expose:

```python
def run_experiment(output_path: str) -> dict:
    ...
```

Return the same dictionary that you write as JSON to `output_path`. It must
contain these fields:

```text
instrument
resource
central_wavelength_nm
point_count
peak_wavelength_nm
peak_counts
integrated_counts
completed
```
