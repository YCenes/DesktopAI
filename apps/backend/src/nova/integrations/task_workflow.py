"""Sabit, bounded graph. Checkpoint, izin veya execution journal değildir."""
import os
import sqlite3
import time
from typing import TypedDict

# Ortamda tracing anahtarı olsa da bu yerel aşama dış telemetri açmaz.
os.environ["LANGSMITH_TRACING"] = "false"
os.environ["LANGCHAIN_TRACING_V2"] = "false"
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt, Command
from langgraph.errors import GraphRecursionError
from langsmith import tracing_context

from nova.domain.tasks import TaskError, TERMINAL


class WorkflowState(TypedDict):
    task_id: str


class TaskWorkflow:
    def __init__(self, execution, path):
        self.execution = execution
        self.connection = sqlite3.connect(path, check_same_thread=False)
        self.checkpointer = SqliteSaver(self.connection, serde=JsonPlusSerializer(
            pickle_fallback=False, allowed_json_modules=None, allowed_msgpack_modules=None))
        graph = StateGraph(WorkflowState)
        graph.add_node("validate", self.validate)
        graph.add_node("permission", self.permission)
        graph.add_node("await_approval", self.await_approval)
        graph.add_node("execute", self.execute)
        graph.add_node("record", self.record)
        graph.add_edge(START, "validate")
        graph.add_edge("validate", "permission")
        graph.add_conditional_edges("permission", self.route, {"stop": END, "approval": "await_approval", "execute": "execute"})
        graph.add_edge("await_approval", "execute")
        graph.add_edge("execute", "record")
        graph.add_edge("record", END)
        self.graph = graph.compile(checkpointer=self.checkpointer)

    def status(self, task_id):
        with self.execution.store.transaction() as db:
            return self.execution.store.row(db, task_id)["status"]

    def budget(self, config):
        if time.monotonic() >= config["configurable"]["deadline"]:
            raise TaskError("WORKFLOW_TIMEOUT", "Görev süre sınırını aştı.")

    def validate(self, state, config):
        self.budget(config)
        with self.execution.store.transaction() as db:
            row = self.execution.store.row(db, state["task_id"])
            self.execution.check_session(row)
            self.execution.registry.validate(self.execution.action(row))
            if row["status"] == "queued":
                self.execution.store.transition(db, state["task_id"], "running", "validated")
        return {}

    def permission(self, state, config):
        self.budget(config)
        self.execution.prepare(state["task_id"])
        return {}

    def route(self, state):
        status = self.status(state["task_id"])
        return "stop" if status in TERMINAL else ("approval" if status == "awaiting_approval" else "execute")

    def await_approval(self, state, config):
        self.budget(config)
        interrupt({"task_id": state["task_id"], "simulated": True})
        self.budget(config)
        return {}

    def execute(self, state, config):
        self.budget(config)
        self.execution.execute(state["task_id"], config["configurable"]["deadline"])
        return {}

    def record(self, state, config):
        # Sonucun asıl kaydı ExecutionService transaction'ında zaten kalıcıdır.
        return {}

    def run(self, task_id, resume=False, max_steps=8, timeout=5):
        config = {"configurable": {"thread_id": task_id, "deadline": time.monotonic() + timeout},
                  "recursion_limit": max_steps, "callbacks": []}
        try:
            with tracing_context(enabled=False):
                self.graph.invoke(Command(resume=True) if resume else {"task_id": task_id}, config, durability="sync")
        except GraphRecursionError:
            raise TaskError("WORKFLOW_STEP_LIMIT", "Görev adım sınırını aştı.") from None

    def close(self):
        self.connection.close()
