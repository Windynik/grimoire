"""Settings routes of phone access (see backend.core.phone).

These answer only on this machine: the phone listener blocks /api/phone.
"""

import io

import segno
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel

from backend.api.dependencies import get_phone_access
from backend.core.phone import PhoneAccess

router = APIRouter(prefix="/api")


class PhoneSwitch(BaseModel):
    enabled: bool


@router.get("/phone")
async def phone_status(access: PhoneAccess = Depends(get_phone_access)):
    """Whether phone access is on, the addresses, the paired phones and the live code."""
    return access.status()


@router.post("/phone")
async def phone_switch(body: PhoneSwitch, request: Request,
                       access: PhoneAccess = Depends(get_phone_access)):
    """Turn phone access on or off. Turning it on makes a pairing code."""
    await access.set_enabled(request.app, body.enabled)
    if body.enabled and access.running:
        access.new_pair_code()
    return access.status()


@router.post("/phone/pair-code")
async def phone_pair_code(access: PhoneAccess = Depends(get_phone_access)):
    """Make a new pairing code. It replaces the one before."""
    if not access.enabled:
        raise HTTPException(status_code=409, detail="Turn on phone access first.")
    access.new_pair_code()
    return access.status()


@router.get("/phone/qr.svg")
async def phone_qr(access: PhoneAccess = Depends(get_phone_access)):
    """The QR code of the live pairing link, as SVG."""
    pair = access.pair_info()
    if not pair or not pair["url"]:
        raise HTTPException(status_code=404, detail="No live pairing code.")
    # A standalone SVG file needs its XML namespace; segno's "inline" form has none.
    out = io.BytesIO()
    segno.make(pair["url"], error="m").save(out, kind="svg", scale=6, border=2,
                                            dark="#12152a", light="#ffffff", xmldecl=False)
    return Response(content=out.getvalue(), media_type="image/svg+xml",
                    headers={"Cache-Control": "no-store"})


@router.delete("/phone/devices/{device_id}")
async def phone_forget(device_id: str, access: PhoneAccess = Depends(get_phone_access)):
    """Unpair one phone."""
    if not access.forget(device_id):
        raise HTTPException(status_code=404, detail="No paired device with that id.")
    return access.status()


@router.delete("/phone/devices")
async def phone_forget_all(access: PhoneAccess = Depends(get_phone_access)):
    """Unpair every phone."""
    access.forget()
    return access.status()
