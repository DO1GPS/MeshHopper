"""One UI-independent inbox reader, including companion binary channel replies.

The producer/relay must durably store original replies before forwarding them.
This consumer never sends an RF message or changes device configuration.
"""
from __future__ import annotations
import asyncio
from meshcore import EventType

MESSAGE_TYPES = frozenset({EventType.CONTACT_MSG_RECV, EventType.CHANNEL_MSG_RECV,
                           EventType.CHANNEL_DATA_RECV})
REPLY_TYPES = [*MESSAGE_TYPES, EventType.NO_MORE_MSGS, EventType.ERROR]


class InboxFetcher:
    def __init__(self, client):
        self.client = client
        self.wake = asyncio.Event()
        self.task = None
        self.subscription = None
        self.messages = 0
        self.drains = 0

    async def start(self):
        if self.task is not None:
            raise RuntimeError('Inbox reader already started')
        self.subscription = self.client.subscribe(EventType.MESSAGES_WAITING,
                                                   lambda _event: self.wake.set())
        self.wake.set()  # Drain pre-existing inbox independently of a UI.
        self.task = asyncio.create_task(self._run(),name='meshcore-inbox-fetch')
        return self.task

    async def _run(self):
        while True:
            await self.wake.wait()
            self.wake.clear()
            while True:
                event = await self.client.commands.send(b'\x0a',REPLY_TYPES)
                if event is None or event.type not in MESSAGE_TYPES | {EventType.NO_MORE_MSGS}:
                    raise ConnectionError('Inbox GET failed; no retry or following GET')
                if event.type == EventType.NO_MORE_MSGS:
                    self.drains += 1
                    break
                self.messages += 1

    async def stop(self):
        if self.subscription is not None:
            self.subscription.unsubscribe()
            self.subscription = None
        if self.task is not None:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
            finally:
                self.task = None
