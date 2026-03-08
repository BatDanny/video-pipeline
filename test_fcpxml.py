from app.export.fcpxml import FCPXMLBuilder
import math

class DummyVideo:
    id = "1"
    resolution = "1920x1080"
    fps = 30.0
    duration_sec = 10.0
    filepath = "/tmp/test.mp4"
    filename = "test.mp4"

class DummyClip:
    tags = []
    effective_score = 90
    start_sec = 0.0
    duration_sec = 5.0

data = [{"clip": DummyClip(), "video": DummyVideo()}]
builder = FCPXMLBuilder()
print(builder.build(data))
