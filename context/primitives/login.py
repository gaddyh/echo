from pydantic import BaseModel

class LoginResponse(BaseModel):
    qr_image_base64: str
    status: str