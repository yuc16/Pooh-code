from __future__ import annotations

import hashlib
from dataclasses import dataclass

from .config import AgentConfig
from .context import render_transcript


EXPLORE_SYSTEM_PROMPT = """你是一个只读代码探索子代理，专门负责快速搜索和分析代码库。

严格限制：
- 只能做搜索、读取、分析
- 不能创建、修改、删除、移动任何文件
- 如果使用 bash，只能做只读命令，例如 ls、find、rg、grep、cat、head、tail、git status、git log、git diff
- 最终输出必须是精炼结论，优先给出答案、证据文件、关键片段和建议的下一步搜索点
"""


GENERAL_SUBAGENT_PROMPT = """你是一个子代理。

目标：
- 独立处理一个局部任务
- 只把高价值结论返回给主代理
- 结果要压缩，不要把完整思考过程或无关上下文返回
"""


@dataclass
class SubAgentRequest:
    agent_type: str
    description: str
    prompt: str


def build_subagent_session_key(parent_session_key: str, request: SubAgentRequest) -> str:
    digest = hashlib.sha1(
        f"{parent_session_key}|{request.agent_type}|{request.description}|{request.prompt}".encode(
            "utf-8"
        )
    ).hexdigest()[:12]
    return f"subagent:{request.agent_type}:{digest}"


def build_subagent_prompt(parent_transcript: list[dict], request: SubAgentRequest) -> str:
    transcript = render_transcript(parent_transcript[-12:])
    return (
        f"子任务描述：{request.description}\n\n"
        f"用户要求：{request.prompt}\n\n"
        "下面是主会话最近的上下文，只用于帮助你快速进入状态。"
        "不要重复复述整段上下文，只返回完成这个子任务所需的结论。\n\n"
        f"{transcript}"
    )


def build_subagent_system_prompt(config: AgentConfig, agent_type: str) -> str:
    if agent_type == "explorer":
        return EXPLORE_SYSTEM_PROMPT
    return GENERAL_SUBAGENT_PROMPT + f"\n当前模型：{config.model}\n"
