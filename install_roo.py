import subprocess

print("Installing Roo Code extension...")
result = subprocess.run(["code", "--install-extension", "/home/dannydebian/dev/video-pipeline/Roo-Code/bin/roo-cline-3.51.1.vsix"], capture_output=True, text=True)
print("STDOUT:", result.stdout)
print("STDERR:", result.stderr)
print("Return code:", result.returncode)
