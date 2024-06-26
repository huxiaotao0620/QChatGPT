from __future__ import annotations

import typing

import pydantic
import mirai

from ..core import app, entities as core_entities
from . import errors, operator


class CommandReturn(pydantic.BaseModel):
    """命令返回值
    """

    text: typing.Optional[str]
    """文本
    """

    image: typing.Optional[mirai.Image]

    error: typing.Optional[errors.CommandError]= None

    class Config:
        arbitrary_types_allowed = True


class ExecuteContext(pydantic.BaseModel):
    """单次命令执行上下文
    """

    query: core_entities.Query

    session: core_entities.Session

    command_text: str

    command: str

    crt_command: str

    params: list[str]

    crt_params: list[str]

    privilege: int
