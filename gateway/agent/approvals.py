# built-in
import uuid

# local
from gateway.audit.models import RemediationApproval
from gateway.audit.store import record_event, save_approval
from gateway.time_utils import now_ist

HIGH_IMPACT_ACTIONS = {"close_circuit", "drain_upstream", "create_incident_ticket"}


async def request_approval(
    action: str, upstream_url: str, arguments: dict, reason: str
) -> dict:
    approval = RemediationApproval(
        approval_id=str(uuid.uuid4()),
        action=action,
        upstream_url=upstream_url,
        arguments=arguments,
        reason=reason,
        requested_at=now_ist(),
    )
    await save_approval(approval)
    await record_event(
        event_type="approval_requested",
        upstream_url=upstream_url,
        message=f"Human approval requested for {action.replace('_', ' ')}.",
        metadata={"approval_id": approval.approval_id, "reason": reason},
    )
    return {
        "status": "pending_approval",
        "approval_id": approval.approval_id,
        "action": action,
        "upstream_url": upstream_url,
        "message": "Action was not executed and is waiting for an operator decision.",
    }
