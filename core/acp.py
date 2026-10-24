from __future__ import annotations

import os
import sys

from uagents import Agent, Context, Protocol
from uagents_core.contrib.protocols.chat import (
    ChatAcknowledgement,
    ChatMessage,
    EndSessionContent,
    StartSessionContent,
    TextContent,
    chat_protocol_spec,
)

from core.cards import card_message
from core.state import Turn


def text_msg(text: str, end_session: bool = False) -> ChatMessage:
    content = [TextContent(type="text", text=text)]
    if end_session:
        content.append(EndSessionContent(type="end-session"))
    return ChatMessage(content=content)


def turn_to_message(turn: Turn) -> ChatMessage:
    if turn.card_kind and turn.card_payload is not None:
        return card_message(turn.text, turn.card_kind, turn.card_payload)
    return text_msg(turn.text)


def attach_chat(agent: Agent, on_text):
    chat_proto = Protocol(spec=chat_protocol_spec)

    @chat_proto.on_message(ChatMessage)
    async def handle_message(ctx: Context, sender: str, msg: ChatMessage) -> None:
        await ctx.send(sender, ChatAcknowledgement(acknowledged_msg_id=msg.msg_id))
        seen = ctx.storage.get("seen") or []
        msg_id = str(msg.msg_id)
        if msg_id in seen:
            return
        ctx.storage.set("seen", seen[-200:] + [msg_id])
        for item in msg.content:
            if isinstance(item, StartSessionContent):
                ctx.logger.info("Session started with %s", sender)
            elif isinstance(item, EndSessionContent):
                ctx.logger.info("Session ended with %s", sender)
        text = msg.text().strip()
        if not text:
            return
        reply = await on_text(ctx, sender, text)
        if reply is None:
            return
        if isinstance(reply, Turn):
            await ctx.send(sender, turn_to_message(reply))
        elif isinstance(reply, ChatMessage):
            await ctx.send(sender, reply)
        else:
            await ctx.send(sender, text_msg(str(reply)))

    @chat_proto.on_message(ChatAcknowledgement)
    async def handle_ack(ctx: Context, sender: str, msg: ChatAcknowledgement) -> None:
        ctx.logger.info("Ack from %s for %s", sender, msg.acknowledged_msg_id)

    is_test = "pytest" in sys.modules or bool(os.getenv("PYTEST_CURRENT_TEST"))
    agent.include(chat_proto, publish_manifest=False if is_test else True)
    return chat_proto
