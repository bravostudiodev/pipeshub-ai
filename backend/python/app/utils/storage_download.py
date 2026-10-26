"""Interprets the storage service's `/document/internal/:id/download` response.

The body is either the raw file (local storage) or a `{"signedUrl": ...}` envelope
(S3/Azure). A stored `.json` file has the same Content-Type as the envelope, so the
type alone can't distinguish them.
"""
from collections.abc import Mapping

DELIVERY_HEADER = "X-Storage-Delivery"
DELIVERY_INLINE = "inline"
DELIVERY_SIGNED_URL = "signed-url"


def is_inline_file(headers: Mapping[str, str]) -> bool:
    """True when the response body is the file itself, not a signed-URL envelope."""
    delivery = headers.get(DELIVERY_HEADER)
    if delivery:
        return delivery == DELIVERY_INLINE
    # Storage service predating the explicit header: only the local path sends an attachment.
    return bool(headers.get("Content-Disposition"))
