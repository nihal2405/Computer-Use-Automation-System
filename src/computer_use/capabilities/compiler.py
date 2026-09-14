"""Compile verified successful actions; never copy an offline workflow fixture."""

from computer_use.schemas.capability import Capability
from computer_use.schemas.common import check_values


def compile_capability(
    task, recorder, *, run_id, identity, outputs, checkpoint_verified, live_provider
):
    if not checkpoint_verified or not recorder.model_responses or not recorder.steps:
        raise ValueError("Compilation requires model decisions and verified execution")
    if identity.product != task.target.product or identity.version not in task.target.versions:
        raise ValueError("Discovered target is incompatible")
    check_values(task.outputs, outputs)
    return Capability(
        schema_version="1.0",
        id=task.id,
        capability_version=task.capability_version,
        description=task.goal,
        provenance="llm_discovery" if live_provider else "development_fixture",
        discovery_run_id=run_id if live_provider else None,
        target=task.target.model_copy(update={"versions": [identity.version]}),
        inputs=task.inputs,
        outputs=task.outputs,
        steps=recorder.steps,
        success_checkpoint=task.success_checkpoint,
        business_outcomes=task.business_outcomes,
        recovery_rules=task.recovery_rules,
    )
