# web/nginx/portal-proxy.inc -- the proxy_pass block, shared by every proxied location.
#
# Mount alongside portal.conf at /etc/nginx/conf.d/portal-proxy.inc. It is a separate
# file rather than a repeated block so the two locations that proxy cannot drift apart
# — and a drifted X-Forwarded-For is a rate limiter that silently stops working.

proxy_pass http://portal;
proxy_http_version 1.1;
proxy_set_header Connection "";

# $http_host, not $host: $host drops the port, so a portal reached on anything but :80
# would hand the browser redirects and url_for() links pointing at the wrong port. The
# app builds its redirects as paths for the same reason, but a wrong Host would still
# corrupt any absolute URL a future page generates.
proxy_set_header Host              $http_host;
proxy_set_header X-Real-IP         $remote_addr;
# The portal reads the RIGHTMOST entry — the one nginx appended, which a client cannot
# forge. $proxy_add_x_forwarded_for appends $remote_addr to whatever the client sent,
# so that property holds even when the request arrives with a fabricated header.
proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
proxy_set_header X-Forwarded-Proto $scheme;

# The portal answers a download with an empty body and a header; it never waits on the
# file itself, so these only need to cover a MySQL round trip.
proxy_connect_timeout 5s;
proxy_send_timeout    30s;
proxy_read_timeout    30s;

# Small HTML pages: buffer them so a slow phone on 3G does not hold a portal worker
# open for the length of the render.
proxy_buffering on;
proxy_buffers 8 16k;
proxy_busy_buffers_size 32k;
