"""Loopback-only operator UI; bearer token, origin checks, and no raw UI persistence."""

import asyncio
import hmac
import secrets
import json
import sys
from threading import Thread

from flask import Flask, jsonify, request, Response
from werkzeug.serving import make_server, WSGIRequestHandler


PAGE = """<!doctype html><html lang="en"><meta charset="utf-8"><title>Automation operator</title>
<style>body{font:16px system-ui;max-width:900px;margin:40px auto;padding:20px;background:#f5f7fa;color:#152536}button{padding:12px 18px;margin:8px 8px 8px 0;border:0;border-radius:8px;background:#176b65;color:white;cursor:pointer}button:disabled{opacity:.35}pre{white-space:pre-wrap;background:white;padding:20px;border-radius:10px}#notice{padding:16px;background:#e1eeeb}small{color:#526070}</style>
<h1>Automation operator</h1><p id="goal"></p><p id="notice">Connecting…</p>
<strong id="state"></strong><p id="step"></p><div><button id="takeover">Take control</button><button id="focus">Show bank window</button><button id="resume">Verify and resume</button><button id="cancel">Cancel run</button></div>
<p>Take control, resolve the obstacle in the existing bank window, then request resume. Keep the requested member's account page open. Resume will verify it and reread the outputs.</p>
<small id="events"></small><h2>Sanitized intervention</h2><pre id="context"></pre>
<script>
const token=location.hash.slice(1);history.replaceState(null,'',location.pathname);
const headers={Authorization:'Bearer '+token,'Content-Type':'application/json'};
let busy=false;
async function update(command){try{const response=await fetch(command?'/api/command':'/api/state',{method:command?'POST':'GET',headers,body:command?JSON.stringify({command}):undefined});const s=await response.json();if(!response.ok){document.querySelector('#notice').textContent=s.error;return;}document.querySelector('#state').textContent=s.state;document.querySelector('#goal').textContent=s.goal;document.querySelector('#step').textContent='Stopped action: '+(s.step_action||'none')+' · Reason: '+(s.intervention?.reason||'none');document.querySelector('#notice').textContent=s.notice;document.querySelector('#context').textContent=JSON.stringify(s.intervention,null,2);document.querySelector('#events').textContent='Captured human events: '+s.human_events;document.querySelector('#takeover').disabled=s.state!=='AWAITING_HUMAN';document.querySelector('#resume').disabled=s.state!=='HUMAN_CONTROL';document.querySelector('#cancel').disabled=['COMPLETED','FAILED'].includes(s.state);}catch(e){document.querySelector('#notice').textContent='Operator server disconnected. Check the command result in the terminal.';}}
for(const id of ['takeover','focus','resume','cancel'])document.getElementById(id).onclick=async()=>{if(busy)return;busy=true;try{await update(id);}finally{busy=false;}};
update();setInterval(()=>{if(!busy)update();},1000);
</script></html>"""


class QuietHandler(WSGIRequestHandler):
    def log_request(self, *args, **kwargs):
        pass


class OperatorServer:
    def __init__(self, coordinator, *, port=0):
        self.coordinator = coordinator
        self.loop = asyncio.get_running_loop()
        self.token = secrets.token_urlsafe(32)
        app = Flask("local_handoff_operator")
        app.config["MAX_CONTENT_LENGTH"] = 2048
        self.server = make_server("127.0.0.1", port, app, threaded=True, request_handler=QuietHandler)
        self.origin = f"http://127.0.0.1:{self.server.server_port}"
        self.url = self.origin + "/#" + self.token

        @app.before_request
        def protect():
            if request.host != f"127.0.0.1:{self.server.server_port}" or request.headers.get("Origin", self.origin) != self.origin:
                return jsonify(error="Untrusted request origin"), 403
            if request.path.startswith("/api/") and not hmac.compare_digest(request.headers.get("Authorization", ""), "Bearer " + self.token):
                return jsonify(error="Operator authorization required"), 403

        @app.after_request
        def headers(response):
            response.headers.update({"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
                "Content-Security-Policy": "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"})
            return response

        @app.get("/")
        def page():
            return Response(PAGE, mimetype="text/html")

        def dispatch(coroutine):
            future = asyncio.run_coroutine_threadsafe(coroutine, self.loop)
            try:
                return jsonify(future.result(timeout=45))
            except Exception:
                future.cancel()
                return jsonify(error="Command unavailable; check control state and session"), 409

        @app.get("/api/state")
        def state():
            return dispatch(coordinator.status())

        @app.post("/api/command")
        def command():
            data = request.get_json(silent=True)
            if (not isinstance(data, dict) or set(data) != {"command"} or not isinstance(data["command"], str)
                    or data["command"] not in {"takeover", "resume", "cancel", "focus"}):
                return jsonify(error="Invalid operator command"), 400
            return dispatch(coordinator.command(data["command"]))

        self.app = app
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    async def close(self):
        await asyncio.to_thread(self.server.shutdown)
        self.server.server_close()
        await asyncio.to_thread(self.thread.join, 5)


async def run_interactive(engine, *, wait_timeout=900):
    from computer_use.handoff.coordinator import HandoffCoordinator
    async with engine:
        coordinator = HandoffCoordinator(engine, wait_timeout=wait_timeout)
        operator = OperatorServer(coordinator)
        print(json.dumps({"operator_url": operator.url}), file=sys.stderr, flush=True)
        try:
            return await engine.run()
        finally:
            await operator.close()
