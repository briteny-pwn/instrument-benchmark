# Task Goal

Discover the available resources, identify `MockLogger300`, select sensor
channel A, read its temperature and relative humidity, and close every resource
you open.

# Output Format

Create a file named `solution.py` exposing:

```python
def run_experiment(output_path: str) -> dict:
    ...
```

Return the same dictionary that you write as JSON to `output_path`:

```json
{
  "instrument": "MockLogger300",
  "selected_resource": "<discovered resource>",
  "channel": "A",
  "temperature_c": "<measured value>",
  "relative_humidity_percent": "<measured value>"
}
```
