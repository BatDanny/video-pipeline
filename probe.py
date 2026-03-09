import subprocess
import json

file_path = "/mnt/nas/gopro/Vail 2026/GX010336.MP4"
cmd = [
    "docker", "compose", "exec", "-T", "worker", "ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", "-show_streams", file_path
]
result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
print(result.stdout)
