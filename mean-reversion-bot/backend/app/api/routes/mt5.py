"""Local demo controls; the existing remote/Deriv bot is independent."""
import io
import csv
import json
import threading
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from app.execution.mt5_demo import DemoConfig, MT5DemoRunner


def local_only(request: Request):
    if not request.client or request.client.host not in ("127.0.0.1", "::1", "localhost", "testclient"):
        raise HTTPException(403, "MT5 controls are available only on the local PC")
    origin = request.headers.get("origin")
    if origin and origin not in ("http://localhost:3000", "http://127.0.0.1:3000",
                                  "http://localhost:5173", "http://127.0.0.1:5173",
                                  "http://127.0.0.1:8000", "http://localhost:8000"):
        raise HTTPException(403, "Untrusted browser origin")


router = APIRouter(dependencies=[Depends(local_only)])
_creation_lock = threading.Lock()


def get_runner(request: Request):
    with _creation_lock:
        if not hasattr(request.app.state, "mt5_demo"):
            request.app.state.mt5_demo = MT5DemoRunner()
    return request.app.state.mt5_demo


@router.get("/status")
def status(runner=Depends(get_runner)):
    return runner.status()


@router.put("/strategy")
def strategy(config: DemoConfig, runner=Depends(get_runner)):
    return runner.configure(config)


@router.post("/connect")
def connect(runner=Depends(get_runner)):
    return runner.connect()


@router.post("/start")
def start(runner=Depends(get_runner)):
    return runner.start()


@router.post("/stop")
def stop(runner=Depends(get_runner)):
    return runner.stop()


@router.get("/journal")
def journal(limit: int = Query(200, ge=1, le=10000), runner=Depends(get_runner)):
    return runner.journal(limit)


@router.get("/journal.csv")
def export(runner=Depends(get_runner)):
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["id", "timestamp_utc", "account", "kind", "details_json"])
    # Complete journal export, including broker deal tickets and exit P&L.
    for row in reversed(runner.journal(2147483647)):
        writer.writerow([row["id"], row["ts"], row["account"], row["kind"], json.dumps(row["data"])])
    return Response(output.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="v751s-mt5-journal.csv"'})
