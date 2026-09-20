from uuid import uuid4

from backend.agent_harness import ActionOption
from backend.agent_harness import ActionSelection
from backend.agent_harness import ActionSpace
from backend.agent_harness import ActorRef
from backend.agent_harness import AgentHarness
from backend.agent_harness import DecisionPoint
from backend.agent_harness import DecisionRequest
from backend.agent_harness import HarnessStep
from backend.agent_harness import InformationState
from backend.agent_harness import MemoryScope
from backend.application.agents.harness_event_repository import SqlHarnessEventRepository
from backend.db.database import SessionLocal
from backend.db.database import init_db
from backend.db.models import AgentHarnessEvent
from backend.db.models import Game
from backend.db.models import Player


def test_harness_events_are_persisted_idempotently() -> None:
    init_db()
    game_id = f"harness-events-{uuid4().hex}"
    player_id = f"player-{uuid4().hex}"
    with SessionLocal.begin() as db:
        db.add(Game(id=game_id, status="running"))
        db.add(Player(id=player_id, game_id=game_id, seat_no=1, name="P1", role="Villager"))

    request = DecisionRequest(
        request_id=f"request-{uuid4().hex}",
        environment_id="werewolf",
        episode_id=game_id,
        actor=ActorRef(actor_id=player_id, agent_definition_id="test"),
        decision_point=DecisionPoint(kind="werewolf.vote", sequence=1),
        information_state=InformationState(schema_id="test", schema_version="1", observation={}),
        action_space=ActionSpace(
            options=(ActionOption(option_id="skip", action_type="skip", parameters={}),)
        ),
        memory_scope=MemoryScope(namespace="match", episode_id=game_id, actor_id=player_id),
    )

    class Planner:
        def next_step(self, request, context):
            del request, context
            return HarnessStep.select_action(ActionSelection(option_id="skip"))

    result = AgentHarness(Planner()).run(request)
    repository = SqlHarnessEventRepository()
    repository.save(request, result.events)
    repository.save(request, result.events)

    with SessionLocal() as db:
        rows = (
            db.query(AgentHarnessEvent)
            .filter(AgentHarnessEvent.request_id == request.request_id)
            .order_by(AgentHarnessEvent.seq)
            .all()
        )
    assert len(rows) == len(result.events)
    assert rows[0].event_type == "run.started"
    assert rows[-1].event_type == "run.completed"
