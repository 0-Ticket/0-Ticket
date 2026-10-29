"""In-memory Agent Log store (C8, box 12) for tests, shared with the box 27 API tests."""

from soc.l1.agent_log import AgentLogEntry, DuplicateAgentStepError


class FakeAgentLogStore:
    def __init__(self):
        self.entries = []
        self.closed = False

    def save_step(self, step, artifact=None):
        key = (step.subject_type, step.subject_id, step.step)
        if any(
            (entry.step.subject_type, entry.step.subject_id, entry.step.step) == key
            for entry in self.entries
        ):
            raise DuplicateAgentStepError("Agent Log step already exists")
        self.entries.append(AgentLogEntry(step=step, artifact=artifact))

    def list_steps(self, subject_type, subject_id):
        return [
            entry
            for entry in self.entries
            if entry.step.subject_type == subject_type and entry.step.subject_id == subject_id
        ]

    def close(self):
        self.closed = True
