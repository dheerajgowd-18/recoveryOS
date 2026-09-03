"""FastAPI routes for the RecoveryOS Operations Console & Dashboard."""
import os
from typing import Any, Dict, List
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from dashboard.service import dashboard_service

# Locate templates directory
templates_dir = os.path.join(os.path.dirname(__file__), "templates")
templates = Jinja2Templates(directory=templates_dir)

router = APIRouter(tags=["Operations Console"])


@router.get("/dashboard", response_class=HTMLResponse, summary="Operations Console HTML UI")
async def get_dashboard(request: Request) -> HTMLResponse:
    """Renders the main browser-based RecoveryOS Operations Console dashboard."""
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "title": "RecoveryOS Operations Console",
            "version": "v1.5.0",
        },
    )


@router.get("/dashboard/api/control-room", response_model=Dict[str, Any], summary="Control Room Overview API")
async def get_control_room_api() -> Dict[str, Any]:
    """Returns executive KPI strip, real-time activity stream, and operational status."""
    return dashboard_service.get_control_room_data()


@router.get("/dashboard/api/recovery-queue", response_model=List[Dict[str, Any]], summary="Recovery Queue API")
async def get_recovery_queue_api() -> List[Dict[str, Any]]:
    """Returns prioritized operational queue of recovery opportunities."""
    return dashboard_service.get_recovery_queue()


@router.get("/dashboard/api/cases/{case_id}/replay", response_model=Dict[str, Any], summary="Case Decision Replay API")
async def get_case_replay_api(case_id: str) -> Dict[str, Any]:
    """Returns chronological decision trace, candidate evaluations, and explanations for a case."""
    replay = dashboard_service.get_case_replay(case_id)
    if not replay:
        raise HTTPException(
            status_code=404,
            detail=f"Recovery case with ID '{case_id}' was not found in the decision audit log.",
        )
    return replay


@router.get("/dashboard/api/evaluation", response_model=Dict[str, Any], summary="Evaluation Lab API")
async def get_evaluation_api() -> Dict[str, Any]:
    """Returns benchmark baseline comparisons, Oracle ceiling, regret stats, and sensitivity grid."""
    return dashboard_service.get_evaluation_data()


@router.get("/dashboard/api/policies", response_model=Dict[str, Any], summary="Merchant Policies API")
async def get_policies_api() -> Dict[str, Any]:
    """Returns active merchant policy configuration, frequency limits, and automation mode."""
    return dashboard_service.get_policies()


@router.put("/dashboard/api/policies", response_model=Dict[str, Any], summary="Update Merchant Policies API")
@router.post("/dashboard/api/policies", response_model=Dict[str, Any], summary="Update Merchant Policies API")
async def update_policies_api(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Updates active merchant policy parameters and propagates to Governor runtime immediately."""
    try:
        return dashboard_service.update_merchant_policy(payload)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid policy parameters: {str(e)}") from e


@router.get("/dashboard/api/exceptions", response_model=List[Dict[str, Any]], summary="Operational Exceptions API")
async def get_exceptions_api() -> List[Dict[str, Any]]:
    """Returns notable exceptions: stale scheduled actions, consent blocks, and human escalations."""
    return dashboard_service.get_exceptions()


@router.get("/dashboard/api/llm/status", response_model=Dict[str, Any], summary="LLM Configuration & Connection Status")
async def get_llm_status_api() -> Dict[str, Any]:
    """Returns safe metadata regarding LLM provider, active model, and connection readiness."""
    return dashboard_service.get_llm_status()


@router.post("/dashboard/api/live-demo/run", response_model=Dict[str, Any], summary="Execute Live AI Demo Scenario")
async def run_live_demo_api(request: Request) -> Dict[str, Any]:
    """Executes a preset or custom scenario in LIVE_LLM or DETERMINISTIC mode with strict fail-closed guarantees."""
    try:
        body = await request.json() if request.headers.get("content-type") == "application/json" else {}
    except Exception:
        body = {}
    
    mode = body.get("mode") or request.query_params.get("mode") or "LIVE_LLM"
    scenario_custom = body.get("scenario")
    
    if scenario_custom and isinstance(scenario_custom, dict):
        try:
            return await dashboard_service.run_custom_scenario(scenario_custom, mode=mode)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Custom live scenario execution failed: {str(e)}") from e

    scenario_id = body.get("scenario_id") or body.get("scenario_key") or request.query_params.get("scenario_id") or request.query_params.get("scenario_key") or "scen_demo_timing"
    try:
        return await dashboard_service.run_scenario(scenario_id, mode=mode)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Live demo execution failed: {str(e)}") from e


@router.get("/dashboard/api/dynamic-runs/history", response_model=List[Dict[str, Any]], summary="Get Session Dynamic Runs History")
async def get_dynamic_runs_history_api() -> List[Dict[str, Any]]:
    """Returns chronological log of dynamic scenario runs evaluated during the current session."""
    return dashboard_service.get_dynamic_runs_history()


@router.post("/dashboard/api/scenarios/{scenario_id}/run", response_model=Dict[str, Any], summary="Execute Scenario Lab Simulation")
@router.get("/dashboard/api/scenarios/{scenario_id}/run", response_model=Dict[str, Any], summary="Execute Scenario Lab Simulation")
async def run_scenario_api(scenario_id: str, request: Request) -> Dict[str, Any]:
    """Executes a signature demo case through the RecoveryOS runtime and returns audit trace."""
    mode = "DETERMINISTIC"
    if request.method == "POST":
        try:
            if request.headers.get("content-type") == "application/json":
                body = await request.json()
                mode = body.get("mode", "DETERMINISTIC")
        except Exception:
            mode = "DETERMINISTIC"
    # Also check query param if present
    query_mode = request.query_params.get("mode")
    if query_mode:
        mode = query_mode

    try:
        return await dashboard_service.run_scenario(scenario_id, mode=mode)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Scenario execution failed: {str(e)}") from e
