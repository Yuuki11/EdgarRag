"""Company catalog route for the web UI."""

from fastapi import APIRouter

from ..schemas import CompaniesResponse
from ..services.companies import load_companies

router = APIRouter()


@router.get("/api/companies", response_model=CompaniesResponse)
def companies() -> CompaniesResponse:
    return CompaniesResponse(companies=load_companies())
