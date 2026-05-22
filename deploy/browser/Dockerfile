# Build STAC Browser from source.
# The first build takes several minutes (npm install + vite build).
# Subsequent builds are cached unless package.json changes.
#
# Branding / theming
# ------------------
# Place any of these files alongside this Dockerfile to customise the browser;
# they are copied into the source tree before the npm build runs:
#
#   theme/variables.scss  — SCSS variable overrides (colours, fonts, logo size)
#   theme/custom.scss     — arbitrary CSS/SCSS rules (logo, layout tweaks)
#   theme/<name>.png      — logo/image assets; reference in variables.scss as:
#                           $logo-image: '~@/assets/<name>.png';
#
# Copy the *.example files and edit them to get started:
#
#   cp theme/variables.scss.example theme/variables.scss
#   cp theme/custom.scss.example    theme/custom.scss

FROM node:20-alpine AS build

WORKDIR /app

RUN apk add --no-cache git

# Pin to a specific release tag for reproducibility.
# Update STAC_BROWSER_VERSION to upgrade.
ARG STAC_BROWSER_VERSION=v3.3.4
RUN git clone --depth 1 --branch ${STAC_BROWSER_VERSION} \
    https://github.com/radiantearth/stac-browser.git .

RUN npm ci --prefer-offline

# Copy the entire theme directory so all overrides are available in one layer.
COPY theme/ /tmp/theme/

# Merge SCSS overrides.
# variables.scss: APPENDED so our values come last and override upstream non-!default vars.
# custom.scss: replaces upstream entirely (safe — upstream custom.scss is intentionally empty).
RUN if [ -f /tmp/theme/variables.scss ]; then \
        cat src/theme/variables.scss /tmp/theme/variables.scss > /tmp/merged.scss && \
        mv /tmp/merged.scss src/theme/variables.scss; \
    fi
RUN if [ -f /tmp/theme/custom.scss ]; then \
        cp /tmp/theme/custom.scss src/theme/custom.scss; \
    fi

# Copy PNG assets into src/theme/ so webpack can bundle them.
# Reference them in variables.scss as './npl_logo.png' (relative to src/theme/).
RUN find /tmp/theme -maxdepth 1 \( -name '*.png' -o -name '*.jpg' \) -exec cp {} src/theme/ \;

# Build without a hard-coded catalog URL — URL is set at runtime via config.js.
RUN npm run build

# Inject a <script> tag that loads config.js before </head> so the app
# picks up window.STAC_BROWSER_CONFIG at runtime from the volume-mounted file.
RUN sed -i 's|</head>|<script src="/config.js"></script></head>|' /app/dist/index.html

# ---

FROM nginx:alpine

COPY --from=build /app/dist /usr/share/nginx/html

# Health check
HEALTHCHECK --interval=30s --timeout=5s \
    CMD wget -qO- http://localhost/ || exit 1
