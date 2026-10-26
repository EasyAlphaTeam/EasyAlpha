import json
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException
from sqlmodel import col, desc, select

from app.api.deps import CurrentUser, SessionDep
from app.models import Backtest, BacktestPublic, Factor, FactorPublic

router = APIRouter(prefix="/factors", tags=["factors"])


def _oldest_backtest(session: SessionDep, factor_id: uuid.UUID) -> Backtest | None:
    return session.exec(
        select(Backtest)
        .where(Backtest.factor_id == factor_id)
        .order_by(col(Backtest.created_at).asc())
        .limit(1)
    ).first()


@router.get("", response_model=list[FactorPublic])
def read_factors(session: SessionDep, current_user: CurrentUser) -> Any:
    """
    Retrieve all factors for the current user, each with the oldest backtest's results.
    """
    factors = session.exec(
        select(Factor).where(Factor.user_id == current_user.id).order_by(desc(Factor.created_at))
    ).all()

    result = []
    for factor in factors:
        backtest = _oldest_backtest(session, factor.id)
        result.append(
            FactorPublic(
                id=factor.id,
                user_id=factor.user_id,
                index=factor.index,
                name=factor.name,
                expr=factor.expr,
                created_at=factor.created_at,
                is_deleted=factor.is_deleted,
                backtest_result=backtest.results if backtest else None,
            )
        )
    return result


@router.get("/{factor_id}/backtest", response_model=BacktestPublic)
def read_oldest_backtest(
    session: SessionDep, current_user: CurrentUser, factor_id: uuid.UUID
) -> Any:
    """
    Get the oldest backtest record for a specific factor.
    ic_detail and report_normal are parsed from JSON string if present.
    """
    factor = session.get(Factor, factor_id)
    if not factor:
        raise HTTPException(status_code=404, detail="Factor not found")
    if factor.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not enough permissions")

    backtest = _oldest_backtest(session, factor_id)
    if not backtest:
        raise HTTPException(status_code=404, detail="No backtest found for this factor")

    def _parse_json_field(value: str | None) -> Any:
        if value is None:
            return None
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return value

    return BacktestPublic(
        id=backtest.id,
        factor_id=backtest.factor_id,
        params=backtest.params,
        results=backtest.results,
        ic_detail=_parse_json_field(backtest.ic_detail),
        report_normal=_parse_json_field(backtest.report_normal),
        created_at=backtest.created_at,
    )
