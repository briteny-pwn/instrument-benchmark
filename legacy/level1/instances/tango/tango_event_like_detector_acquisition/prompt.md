# Task Goal

Create `solution.py`. Connect to the simulator, identify the detector,
configure a 0.05 s exposure, start a four-frame acquisition, collect all frame
event records, wait until acquisition completes, read the final frame count and
mean intensity, then close all resources.

# Output Format

Expose:

```python
def run_experiment(output_path: str) -> dict:
    ...
```

Return the same dictionary that you write as JSON to `output_path`. It must
contain these fields:

```text
device
class
exposure_s
frames
intensities
frame_count
mean_intensity
final_state
```
