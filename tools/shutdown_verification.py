"""Bounded controller for the disposable, packaged-app shutdown verification.

Run `serve`, then issue `start` / `stop` / `exit` commands in separate calls.
Only the QA app can be launched or terminated. Live Arc/ArtBrowser are protected.
"""

import argparse
import datetime
import json
import os
from pathlib import Path
import signal
import subprocess
import socket
import threading
import time
import sys

from verification_proxy import VerificationProxy


def write_json(path, value):
    temporary = path.with_suffix(".next")
    temporary.write_text(json.dumps(value, indent=2)+"\n")
    temporary.replace(path)


def qa_pids(app):
    rows = subprocess.run(["ps","-axo","pid=,uid=,comm="], capture_output=True,text=True,check=True).stdout
    result=[]
    for line in rows.splitlines():
        parts=line.strip().split(None,2)
        if len(parts)==3 and int(parts[1])==os.getuid() and parts[2].startswith(str(app)+"/"):
            result.append(int(parts[0]))
    return result


def stop_qa(app):
    for sig in (signal.SIGTERM,signal.SIGKILL):
        for pid in qa_pids(app):
            try: os.kill(pid,sig)
            except ProcessLookupError: pass
        time.sleep(.3)


def serve(work):
    config=json.loads((work/"configuration.json").read_text())
    app=Path(config["app"])
    if app.parent!=work or app.name!="ArtBrowser Verification.app": raise SystemExit("Unsafe QA application path")
    if Path(config["alias"]).resolve()!=Path(config["profile"]): raise SystemExit("QA profile alias changed")
    if qa_pids(app): raise SystemExit("QA app is already running")
    previous_status=work/"status.json"
    previous_port=json.loads(previous_status.read_text()).get("proxy_port",0) if previous_status.exists() else 0
    proxy=VerificationProxy(work/"proxy-events.jsonl",previous_port)
    port=proxy.server_address[1]
    thread=threading.Thread(target=proxy.serve_forever,daemon=True);thread.start()
    support=Path.home()/"Library/Application Support"
    protected=[Path("/Applications/Arc.app"),support/"Arc",Path.home()/"Applications/ArtBrowser.app",support/"ArtBrowser",support/"ArtBrowser.noindex",support.parent/"Preferences/company.thebrowser.Browser.plist",support.parent/"Preferences/local.artbrowser.app.plist",Path.home()/"Library/Keychains"]
    rules=["(version 1)","(allow default)","(deny network-outbound)",f'(allow network-outbound (remote ip "localhost:{port}"))','(deny mach-lookup (global-name "com.apple.securityd") (global-name "com.apple.securityd.xpc") (global-name "com.apple.securityd.system"))','(deny file* (subpath "/Library/Keychains"))']
    for path in protected: rules.append(f"(deny file* (subpath {json.dumps(str(path))}))")
    policy=work/"isolation.sb";policy.write_text("\n".join(rules)+"\n")
    probes=[]
    for path in [protected[0]/"Contents/MacOS/Arc",protected[1]/"StorableSidebar.json",protected[2]/"Contents/MacOS/ArtBrowser",Path(config["profile"]).parents[3]/"ArtBrowser.noindex/Profile/StorableSidebar.json"]:
        check=subprocess.run(["sandbox-exec","-f",str(policy),"cat",str(path)],capture_output=True)
        # A nonexistent path does not count as proof of isolation.
        if path.exists() and (check.returncode==0 or b"Operation not permitted" not in check.stderr):
            raise RuntimeError("Original/live profile protection failed")
        probes.append({"path":str(path),"exists":path.exists(),"denied":b"Operation not permitted" in check.stderr})
    # A controlled, reachable forbidden listener avoids confusing a DNS/TLS
    # failure with policy denial.
    forbidden=socket.socket();forbidden.bind(("127.0.0.1",0));forbidden.listen()
    forbidden_port=forbidden.getsockname()[1]
    with socket.create_connection(("127.0.0.1",forbidden_port),timeout=2):pass
    probe="import socket,json,sys; s=socket.socket(); e=s.connect_ex(('127.0.0.1',int(sys.argv[1]))); print(json.dumps({'errno':e})); sys.exit(0 if e==1 else 1)"
    denied=subprocess.run(["sandbox-exec","-f",str(policy),sys.executable,"-I","-S","-c",probe,str(forbidden_port)],capture_output=True)
    if denied.returncode!=0 or json.loads(denied.stdout).get("errno")!=1: raise RuntimeError("Controlled network-denial probe did not prove EPERM: "+denied.stderr.decode()+denied.stdout.decode())
    allowed=subprocess.run(["sandbox-exec","-f",str(policy),"curl","--noproxy","*","--max-time","3","-sS",f"http://127.0.0.1:{port}/state"],capture_output=True)
    if allowed.returncode or b"Shutdown verification page loaded" not in allowed.stdout:raise RuntimeError("Permitted fixture port is not reachable")
    write_json(work/"isolation-proof.json",{"protected_paths":probes,"controlled_forbidden_port_denied":True,"allowed_fixture_port_reachable":True,"proxy_allowlist":["example.com","example.org","iana.org","www.iana.org"],"host_date":datetime.datetime.now(datetime.timezone.utc).isoformat()})
    status={"controller":"ready","proxy_port":port,"fixture_url":f"http://127.0.0.1:{port}/state","app":str(app),"running":False}
    write_json(work/"status.json",status)
    print(json.dumps(status),flush=True)
    deadline=time.monotonic()+1200;phase_deadline=0
    try:
        while time.monotonic()<deadline:
            control=work/"command.json"
            if control.exists():
                command=json.loads(control.read_text());control.unlink()
                action=command["action"]
                if action=="exit":break
                if action=="stop":
                    stop_qa(app)
                    status.update(awaiting_launch=False)
                elif action=="start":
                    if qa_pids(app): raise RuntimeError("QA session still running")
                    phase=command["phase"]
                    proxy.response_mode=command["response"]
                    if not phase.replace("-","").isalnum():raise ValueError("Invalid phase label")
                    target=datetime.datetime.fromisoformat(command["date"]).replace(tzinfo=datetime.timezone.utc)
                    shift=int(target.timestamp()-time.time())
                    envargs=["__CFBundleIdentifier=local.artbrowser.verification","ARTBROWSER_SMOKE_TEST=1",f"ARTBROWSER_QA_DATE_SHIFT={shift}",f"ARTBROWSER_QA_PROXY_PORT={port}",f"ARTBROWSER_QA_FORBIDDEN_PORT={forbidden_port}",f"ARTBROWSER_QA_REPORT={work/(phase+'-events.jsonl')}",f"ARTBROWSER_QA_LOG_DIRECTORY={work/(phase+'-logs')}",f"ARTBROWSER_QA_RESPONSE={command['response']}",f"ARTBROWSER_QA_REVOKE_AFTER={command.get('revoke_after',0)}"]
                    environment_values={item.split("=",1)[0]:item.split("=",1)[1] for item in envargs if item.startswith("ARTBROWSER_")}
                    selected_policy=policy
                    if command.get("allow_security_broker"):
                        selected_policy=work/(phase+"-isolation.sb")
                        selected_policy.write_text("\n".join(line for line in policy.read_text().splitlines() if "(deny mach-lookup" not in line)+"\n")
                    write_json(work/"launch-settings.json",{"environment":environment_values,"policy":str(selected_policy),"arguments":["--no-sandbox",f"--proxy-server=http://127.0.0.1:{port}","--disable-quic","--dns-prefetch-disable"]})
                    status.update(phase=phase,target_date=command["date"],response=command["response"],running=False,awaiting_launch=True,watchdog_stopped=False,os_security_broker_denied=not command.get("allow_security_broker",False))
                    print("Armed",phase,"for normal macOS launch; date",command["date"],flush=True)
                status["running"]=bool(qa_pids(app));write_json(work/"status.json",status)
            if status.get("awaiting_launch"):
                current=qa_pids(app)
                if current:
                    phase_deadline=time.monotonic()+180
                    status.update(running=True,pid=current[0],awaiting_launch=False)
                    write_json(work/"status.json",status)
            if status.get("running"):
                if not qa_pids(app):
                    status.update(running=False)
                    write_json(work/"status.json",status)
                elif time.monotonic()>phase_deadline:
                    stop_qa(app);status.update(running=False,watchdog_stopped=True)
                    write_json(work/"status.json",status)
            time.sleep(.25)
    finally:
        stop_qa(app)
        proxy.stopping.set();proxy.shutdown();proxy.server_close()
        forbidden.close()
        status.update(controller="stopped",running=False);write_json(work/"status.json",status)
        print("QA controller, copied browser and loopback proxy stopped",flush=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action",choices=["serve","start","stop","exit","status"])
    parser.add_argument("--phase",default="offline")
    parser.add_argument("--date",default="2026-12-23T12:00:00")
    parser.add_argument("--response",choices=["offline","gone","disabled","timeout"],default="offline")
    parser.add_argument("--revoke-after",type=int,default=0)
    parser.add_argument("--allow-security-broker",action="store_true",help="Diagnostic control: retain file/network/API isolation but allow macOS security service lookup")
    args=parser.parse_args();os.umask(0o077)
    pointer=Path.home()/"Library/Application Support/ArtBrowserPreservation.noindex/current-shutdown-verification.txt"
    work=Path(pointer.read_text().strip())
    if args.action=="serve":return serve(work)
    if args.action=="status":print((work/"status.json").read_text());return
    if not (work/"status.json").exists() or json.loads((work/"status.json").read_text())["controller"]!="ready":raise SystemExit("QA controller is not running")
    write_json(work/"command.json",{"action":args.action,"phase":args.phase,"date":args.date,"response":args.response,"revoke_after":args.revoke_after,"allow_security_broker":args.allow_security_broker})
    print("Queued",args.action,args.phase)


if __name__=="__main__":main()
