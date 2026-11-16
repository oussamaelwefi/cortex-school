from prompts.registry import PROMPTS
from prompts.utils import render_template

from ..llm import ainvoke


async def simple_reply(message: str) -> str:
    meta = PROMPTS["workflow_simple_reply"]
    prompt = render_template(meta["template"], {"message": message})
    return await ainvoke(prompt)
