import sys
import json
from app.pipeline.ingest import _extract_video_metadata

with open("probe.json", "r") as f:
    probe_data = json.load(f)

metadata = _extract_video_metadata(probe_data)
print(json.dumps(metadata, indent=4))
