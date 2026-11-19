"""照抄这个文件改业务：一个模块 = 一个 router + 一张表 + 一条状态机 + 一组用例。

别删这个文件——它是「新增模块时先抄哪里」的示范。验收对照表里的每一项，
在下面都能找到对应的断言点。
"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.errors import raise_conflict, raise_precondition
from app.db.session import get_session
from app.utils.idempotency import idem

router = APIRouter(prefix="/example", tags=["example"])

# 状态机：允许的流转写死在表里，非法流转一律 412，而不是悄悄放过
ALLOWED = {"draft": {"submitted"}, "submitted": {"approved", "rejected"}, "approved": set(), "rejected": {"draft"}}


class CreateIn(BaseModel):
    biz_key: str = Field(min_length=1, description="业务唯一键，用于幂等")
    title: str = Field(min_length=1)


class TransitionIn(BaseModel):
    target: str


@router.post("", status_code=201)
def create(payload: CreateIn, db: Session = Depends(get_session)):
    with idem("example:create", payload.biz_key) as first:
        if not first:
            raise_conflict("duplicate submit", biz_key=payload.biz_key)
        # TODO: 落库（Base + TimestampMixin + UUIDPkMixin）
        return {"biz_key": payload.biz_key, "title": payload.title, "state": "draft"}


@router.post("/{state}/transition")
def transition(state: str, payload: TransitionIn):
    if state not in ALLOWED:
        raise_precondition("unknown state", state=state)
    if payload.target not in ALLOWED[state]:
        raise_precondition("illegal transition", current=state, target=payload.target)
    return {"from": state, "to": payload.target}
