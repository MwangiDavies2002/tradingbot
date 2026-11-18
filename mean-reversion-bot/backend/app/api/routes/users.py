import asyncio
import json
import websockets
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel

from app.database.session import get_db
from app.database.models import User
from app.api.security import get_current_user
from app.config import settings

router = APIRouter()

class DerivConnectionRequest(BaseModel):
    api_key: str

async def validate_deriv_key(api_key: str) -> str:
    """Connects to Deriv to validate the API key and returns the account ID."""
    try:
        async with websockets.connect(settings.DERIV_WS_ENDPOINT) as ws:
            # Send authorize request
            await ws.send(json.dumps({"authorize": api_key}))
            response = json.loads(await ws.recv())
            
            if "error" in response:
                raise HTTPException(status_code=400, detail=f"Deriv Error: {response['error'].get('message')}")
            
            return response["authorize"]["loginid"]
    except Exception as e:
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail=f"Failed to connect to Deriv: {str(e)}")

@router.put("/me/deriv-connection")
async def update_deriv_connection(
    req: DerivConnectionRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # Validate the key with Deriv
    account_id = await validate_deriv_key(req.api_key)
    
    # Update user in DB
    current_user.deriv_api_key = req.api_key
    current_user.deriv_account_id = account_id
    
    db.add(current_user)
    await db.commit()
    
    return {"status": "connected", "account_id": account_id}

@router.get("/me")
async def get_my_profile(current_user: User = Depends(get_current_user)):
    return {
        "id": current_user.id,
        "email": current_user.email,
        "deriv_connected": current_user.deriv_api_key is not None,
        "deriv_account_id": current_user.deriv_account_id
    }
