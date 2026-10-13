"""Import for its side effect, before any module that builds an HTTP client.

Services import this first so the proxy variables are exported, and the HTTP libraries
instrumented, before connection pools and SDK clients are created.
"""

from app.utils.outbound_http import install_outbound_http

install_outbound_http()
