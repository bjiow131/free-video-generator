# Studio access control

The browser API requires authentication whenever the service is configured with
`RENDER_EXTERNAL_HOSTNAME`, `PUBLIC_HOST`, a non-loopback `HOST`, or
`STUDIO_AUTH_REQUIRED=true`. Local loopback use remains available without a
token.

Before deploying a remotely reachable Studio, set `STUDIO_ACCESS_TOKEN` in the
service environment to a randomly generated value with at least 32 characters.
For example, generate one with `openssl rand -hex 32`. Keep it in the hosting
provider's secret environment settings; do not commit the value to Git.

If remote mode is active and the token is missing or too short, Studio API
requests fail closed with HTTP 503. The web page asks for the token on the first
API request, then stores it in a Secure, HttpOnly, SameSite=Strict cookie for
12 hours. The token is not saved in browser storage. `/health` remains available
for platform health checks, and `/api/provider-image/{token}` remains available
only through its existing short-lived capability URL.

To use a deployed service, configure the token before deploying this change.
Changing the environment variable alone does not activate this code on a
currently deployed version.
