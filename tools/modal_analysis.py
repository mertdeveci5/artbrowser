"""Run static binary analysis on Modal; upload the executable and analysis code only.

No browser profiles, cookies, passwords, Keychain items, or environment secrets
are included. Sandboxes terminate after execution or at their bounded timeout
when --keep-alive is explicitly used.
"""

import argparse
import json
import sys
from pathlib import Path

import modal


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, default=Path("/Applications/Arc.app/Contents/MacOS/Arc"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--sandbox-id", help="Reuse a still-running analysis sandbox")
    parser.add_argument("--keep-alive", action="store_true", help="Keep a successful sandbox until its 10 minute timeout")
    args, analysis_args = parser.parse_known_args()
    app = modal.App.lookup("artbrowser-static-analysis", create_if_missing=True)
    image = modal.Image.debian_slim(python_version="3.12").pip_install("capstone==5.0.9")
    sandbox = (modal.Sandbox.from_id(args.sandbox_id) if args.sandbox_id else
               modal.Sandbox.create(app=app, image=image, cpu=2, memory=2048, timeout=600, block_network=True))
    print("Modal sandbox:", sandbox.object_id, flush=True)
    success = False
    try:
        for source, destination in [
            (args.binary, "/tmp/Arc"),
            (Path(__file__).with_name("analyze_macho.py"), "/tmp/analyze_macho.py"),
        ]:
            if not args.sandbox_id or destination != "/tmp/Arc":
                print("Uploading", source.name, source.stat().st_size, "bytes", flush=True)
                sandbox.filesystem.copy_from_local(str(source), destination)
        print("Executing analysis remotely", flush=True)
        process = sandbox.exec("python", "/tmp/analyze_macho.py", "/tmp/Arc", *analysis_args, timeout=480)
        output = process.stdout.read()
        errors = process.stderr.read()
        process.wait()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output)
        print(json.dumps({"exit_code": process.returncode, "output": str(args.output), "bytes": len(output)}), flush=True)
        if errors:
            print(errors[-4000:], file=sys.stderr)
        if process.returncode:
            raise SystemExit(process.returncode)
        success = True
    finally:
        if args.keep_alive and success:
            print("Sandbox kept for follow-up analysis; it expires automatically", flush=True)
        else:
            sandbox.terminate()
            print("Modal sandbox terminated", flush=True)


if __name__ == "__main__":
    main()
