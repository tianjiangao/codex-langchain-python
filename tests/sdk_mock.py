"""Explicit synthetic SDK used only by offline tests. Never live evidence."""

import queue
import threading
import uuid
from types import SimpleNamespace


def event(method, data):
    return SimpleNamespace(method=method, payload=SimpleNamespace(model_dump=lambda **kwargs: data))


class ScriptedSDK:
    clients = []
    reply_text = "OFFLINE_OK"
    hold = False
    barrier = None

    def __init__(self, config, approval_handler):
        self.handler = approval_handler
        self.config = config
        self.thread = "MOCK_" + str(uuid.uuid4())
        self.turn = "MOCK_" + str(uuid.uuid4())
        self.stage = 0
        self.events = queue.Queue()
        self.ready = threading.Event()
        self.interrupts = 0
        self.clients.append(self)

    def start(self):
        pass

    def initialize(self):
        pass

    def close(self):
        pass

    def account_read(self, params):
        return SimpleNamespace(model_dump=lambda **kwargs: {"account": {"type": "chatgpt"}})

    def thread_start(self, params):
        self.params = params
        return SimpleNamespace(thread=SimpleNamespace(id=self.thread), model=params["model"])

    def turn_start(self, thread, prompt, params):
        self.prompt, self.turn_params = prompt, params
        return SimpleNamespace(turn=SimpleNamespace(id=self.turn))

    def turn_interrupt(self, *args):
        self.interrupts += 1
        self.events.put(event("turn/completed", {"turn": {"status": "interrupted"}}))

    def next_turn_notification(self, turn):
        self.ready.set()
        if self.hold:
            return self.events.get(timeout=3)
        if self.stage == 0:
            if self.barrier:
                self.barrier.wait(timeout=3)
            text = self.reply_text
            if self.params["dynamicTools"]:
                tool = self.params["dynamicTools"][0]["name"]
                self.result = self.handler(
                    "item/tool/call",
                    {
                        "threadId": self.thread,
                        "turnId": self.turn,
                        "callId": "MOCK_CALL_" + self.thread,
                        "tool": tool,
                        "arguments": {"a": 7, "b": 5},
                    },
                )
                text = self.result["contentItems"][0]["text"]
            self.events.put(
                event(
                    "thread/tokenUsage/updated",
                    {
                        "tokenUsage": {
                            "total": {
                                "inputTokens": 90,
                                "outputTokens": 10,
                                "cachedInputTokens": 30,
                                "totalTokens": 100,
                                "reasoningOutputTokens": 0,
                            }
                        }
                    },
                )
            )
            self.events.put(
                event(
                    "item/completed",
                    {"item": {"type": "agentMessage", "phase": "final_answer", "text": text}},
                )
            )
            self.events.put(event("turn/completed", {"turn": {"status": "completed"}}))
            self.stage += 1
        return self.events.get(timeout=3)
