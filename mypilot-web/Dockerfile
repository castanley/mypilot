# MyPilot Web (SvelteKit, adapter-node). Build context is the repo root.
#   podman build -f mypilot-web/Dockerfile -t mypilot-web .
FROM node:20-slim AS build
WORKDIR /app
ENV NODE_ENV=development
COPY mypilot-web/package.json /app/
RUN npm install
COPY mypilot-web/ /app/
RUN npm run build

FROM node:20-slim AS run
WORKDIR /app
ENV NODE_ENV=production \
    PORT=3000 \
    HOST=0.0.0.0 \
    MYPILOT_DOCS_DIR=/app/docs
COPY --from=build /app/build ./build
COPY --from=build /app/node_modules ./node_modules
COPY --from=build /app/package.json ./package.json
# The docs wiki renders the repo's markdown at runtime. Bake it in so the image is
# self-contained; compose can bind-mount ./docs over this for live editing.
COPY docs/ ./docs/
EXPOSE 3000
CMD ["node", "build"]
