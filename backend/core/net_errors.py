"""Short reasons for a failed download, in words the owner can act on.

A network filter (a DNS block page, a proxy or antivirus software) answers in
place of Scryfall with its own certificate. The certificate check fails, and
httpx reports it as a ConnectError, the same error as no connection at all.
The real cause is the ssl.SSLCertVerificationError in the exception chain.
"""

import ssl
from typing import Optional

import httpx

MAX_DETAIL = 160  # characters of the certificate error the reason shows


def _chain(error: BaseException):
    """The error, then each error it came from."""
    seen = set()
    while error is not None and id(error) not in seen:
        seen.add(id(error))
        yield error
        error = error.__cause__ or error.__context__


def download_reason(error: BaseException, site: str = "Scryfall") -> Optional[str]:
    """Return why a download from `site` failed, or None for a non-network error."""
    for link in _chain(error):
        if isinstance(link, ssl.SSLCertVerificationError):
            # OpenSSL sets verify_message. truststore raises the error in Python, without it.
            detail = getattr(link, "verify_message", None) or (str(link.args[-1]) if link.args else "")
            text = ("Grimoire could not verify the certificate of %s. A network filter, a proxy "
                    "or antivirus software may block %s." % (site, site))
            return "%s (%s)" % (text, detail[:MAX_DETAIL]) if detail else text
    if isinstance(error, httpx.HTTPStatusError):
        return "%s answered %d. Try again later." % (site, error.response.status_code)
    if any(isinstance(link, httpx.TimeoutException) for link in _chain(error)):
        return "%s did not answer in time. Try again." % site
    if any(isinstance(link, httpx.TransportError) for link in _chain(error)):
        return "Grimoire could not reach %s. Check the internet connection." % site
    return None
