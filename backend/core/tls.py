"""The TLS settings of every download (card data, images, prices).

Python ships its own list of certificate authorities (certifi), so it does
not trust an authority that only the operating system knows, such as the
one a company network installs to inspect HTTPS. Browsers and curl use the
system trust store and work on such a network, while Python fails with
"unable to get local issuer certificate".

truststore makes Python check certificates against the system trust store,
the same store the browser uses. Every certificate is still verified. When
truststore is not installed, the downloads use certifi as before.
"""

import ssl

import certifi

try:
    import truststore
except ImportError:  # pragma: no cover - the fallback runs without the package
    truststore = None


def tls_context() -> ssl.SSLContext:
    """An SSL context that verifies certificates against the system trust store."""
    if truststore is not None:
        return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    return ssl.create_default_context(cafile=certifi.where())
