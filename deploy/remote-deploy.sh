#!/usr/bin/env bash
set -Eeuo pipefail

readonly DEPLOY_DIR="${HOME}/apps/telegram-registration-bot"
readonly COMPOSE_FILE="${DEPLOY_DIR}/compose.yaml"
readonly IMAGE_ENV="${DEPLOY_DIR}/image.env"
readonly BOT_ENV="${DEPLOY_DIR}/bot.env"
export DOCKER_CONFIG="${DEPLOY_DIR}/.docker-auth"
unset BOT_ENV_FILE

compose() {
    docker compose --env-file "${IMAGE_ENV}" --file "${COMPOSE_FILE}" "$@"
}

deploy_current() {
    compose config --quiet
    compose pull bot
    compose up --detach --wait --wait-timeout 120 --remove-orphans
}

restore_previous() {
    cp --preserve=mode "${COMPOSE_FILE}.previous" "${COMPOSE_FILE}"
    cp --preserve=mode "${IMAGE_ENV}.previous" "${IMAGE_ENV}"
    cp --preserve=mode "${BOT_ENV}.previous" "${BOT_ENV}"
}

cd "${DEPLOY_DIR}"
umask 077

for staged_file in compose.yaml.next image.env.next bot.env.next; do
    if [[ ! -f "${staged_file}" ]]; then
        echo "Missing staged deployment file: ${staged_file}" >&2
        exit 2
    fi
done

next_image="$(sed -n 's/^BOT_IMAGE=//p' image.env.next)"
if [[ ! "${next_image}" =~ ^ghcr\.io/[a-z0-9._/-]+@sha256:[a-f0-9]{64}$ ]]; then
    echo "The staged image is not an immutable lowercase GHCR digest" >&2
    exit 2
fi

rollback_available=false
if [[ -f "${COMPOSE_FILE}" && -f "${IMAGE_ENV}" && -f "${BOT_ENV}" ]]; then
    cp --preserve=mode "${COMPOSE_FILE}" "${COMPOSE_FILE}.previous"
    cp --preserve=mode "${IMAGE_ENV}" "${IMAGE_ENV}.previous"
    cp --preserve=mode "${BOT_ENV}" "${BOT_ENV}.previous"
    rollback_available=true
fi

mv compose.yaml.next "${COMPOSE_FILE}"
mv image.env.next "${IMAGE_ENV}"
mv bot.env.next "${BOT_ENV}"
chmod 0644 "${COMPOSE_FILE}"
chmod 0600 "${IMAGE_ENV}" "${BOT_ENV}"

if deploy_current; then
    echo "Deployment is healthy: ${next_image}"
    exit 0
fi

echo "Deployment failed; collecting recent bot logs" >&2
compose logs --no-color --tail 100 bot >&2 || true
compose down --remove-orphans || true

if [[ "${rollback_available}" != true ]]; then
    echo "No previous deployment is available to restore" >&2
    exit 1
fi

echo "Restoring the previous deployment" >&2
restore_previous
if deploy_current; then
    echo "Rollback succeeded; the new deployment remains failed" >&2
    exit 1
fi

echo "Rollback also failed; manual intervention is required" >&2
compose logs --no-color --tail 100 bot >&2 || true
exit 1
