"""角色定妆出图（ComfyUI + LoRA）。"""

from modules.image_gen.profiles import load_visual_profile
from modules.image_gen.service import (
    ImageGenError,
    detect_selfie_request,
    generate_persona_image,
    maybe_attach_selfie,
)

__all__ = [
    "ImageGenError",
    "detect_selfie_request",
    "generate_persona_image",
    "load_visual_profile",
    "maybe_attach_selfie",
]
