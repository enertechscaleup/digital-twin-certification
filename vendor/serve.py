"""Serve simulated twin owners' endpoints over HTTP, one port per twin.

    python -m vendor.serve                       # motor on 9101, compressor on 9102
    python -m engine run --scenario scenarios/demo_full_cycle.json \\
        --vendor motor=http://127.0.0.1:9101/ --vendor compressor=http://127.0.0.1:9102/
    python -m vendor.serve --project projects/fulfilment_cell.json --first-port 9201

Each endpoint answers the platform's JSON requests (engine/boundary.py) and keeps
its twin's formula and parameters to itself. These stand in for owners' own
environments; no real vendor is connected in this prototype.
"""

from __future__ import annotations

import argparse
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from projects import DEFAULT_PROJECT, load_project
from vendor.endpoint import VendorEndpoint, simulated_endpoints


def handler_for(endpoint: VendorEndpoint) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802 (http.server's naming)
            body = self.rfile.read(int(self.headers.get("Content-Length", 0))).decode()
            reply = endpoint.handle(body).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(reply)))
            self.end_headers()
            self.wfile.write(reply)

        def log_message(self, *args):
            pass

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m vendor.serve", description=__doc__.splitlines()[0])
    parser.add_argument("--first-port", type=int, default=9101)
    parser.add_argument("--project", default=str(DEFAULT_PROJECT), help="project file (default: the compressor train)")
    args = parser.parse_args()
    servers = []
    for i, (twin, endpoint) in enumerate(simulated_endpoints(load_project(args.project)).items()):
        server = ThreadingHTTPServer(("127.0.0.1", args.first_port + i), handler_for(endpoint))
        servers.append(server)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        print(f"{twin}: http://127.0.0.1:{args.first_port + i}/ (simulated vendor endpoint)")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        for s in servers:
            s.shutdown()


if __name__ == "__main__":
    main()
