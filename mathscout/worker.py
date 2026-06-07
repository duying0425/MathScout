from celery import Celery

from mathscout.config import get_settings

settings = get_settings()

celery_app = Celery(
    "mathscout",
    broker=settings.redis_url,
    backend=settings.redis_url,
)


@celery_app.task(name="mathscout.source_discovery")
def source_discovery() -> dict[str, object]:
    from mathscout.agents.orchestrator import SourceDiscoveryAgent

    result = SourceDiscoveryAgent().run()
    return {"status": result.status, "payload": result.payload, "error": result.error}


@celery_app.task(name="mathscout.reconcile_candidate")
def reconcile_candidate(
    candidate: dict[str, object],
    matches: list[dict[str, object]],
) -> dict[str, object]:
    from mathscout.agents.orchestrator import ReconciliationAgent
    from mathscout.extraction.schemas import CandidateKnowledgeItemSchema, CandidateMatchSchema

    parsed_candidate = CandidateKnowledgeItemSchema.model_validate(candidate)
    parsed_matches = [CandidateMatchSchema.model_validate(match) for match in matches]
    decision = ReconciliationAgent().decide(parsed_candidate, parsed_matches)
    return decision.model_dump()


@celery_app.task(name="mathscout.plan_orchestration")
def plan_orchestration(
    directive: dict[str, object],
    context: dict[str, object],
) -> dict[str, object]:
    from mathscout.agents.orchestrator import AIOrchestratorAgent
    from mathscout.orchestration.schemas import NaturalLanguageDirective, OrchestrationContext

    parsed_directive = NaturalLanguageDirective.model_validate(directive)
    parsed_context = OrchestrationContext.model_validate(context)
    plan = AIOrchestratorAgent().plan(parsed_directive, parsed_context)
    return plan.model_dump()
