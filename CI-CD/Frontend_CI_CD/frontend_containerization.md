**Актуально для:** Docker 27+, Node.js 22 LTS, Nginx 1.27+, Cosign v3.1+, Syft v1.5+, Trivy v0.55+

# Контейнеризация фронтенда

## Определения

- **Multi-stage build** — Dockerfile с несколькими стадиями: сборка в одном образе, финальный — только production-файлы и рантайм.
- **Image Scanning** — статический анализ образа на уязвимости (Trivy, Grype).
- **Registry Security** — защищённый реестр образов (Harbor, Nexus, GitLab Container Registry) с RBAC, репликацией и retention.
- **Cosign/Sigstore** — keyless-подпись образов и аттестаций SBOM/provenance в OCI-реестре.
- **Distroless/Alpine base** — минимальные базовые образы для сокращения поверхности атаки.
- **BuildKit Secrets** — передача секретов в Dockerfile без сохранения в слоях.
- **Non-root user** — запуск процесса в контейнере от непривилегированного пользователя.
- **Layer Caching** — повторное использование слоёв Docker при неизменных зависимостях для ускорения сборки.
- **Read-only filesystem** — запуск контейнера с монтированием корневой ФС только для чтения.
- **Tini** — легковесный init-процесс (PID 1) для корректной обработки сигналов в контейнере.

---

## Предварительные требования

- **Docker:** Docker Engine 27+ или compatible runtime (Podman 4.6+) с включённым BuildKit (`DOCKER_BUILDKIT=1`).
- **Node.js LTS (v22+):** версия зафиксирована в `.nvmrc` и `engines`; совпадает в CI и локально.
- **CI/CD:** GitLab CI 16+ или аналогичный пайплайн с поддержкой Docker-in-Docker или Kaniko/Skopeo.
- **Сеть:** egress от раннеров к registry/Nexus/Harbor; для runtime — доступность registry из среды деплоя.
- **Registry:** внутренний OCI-реестр (Harbor 2.11+, GitLab Container Registry, Nexus) с поддержкой OCI 1.1 Referrers API для аттестаций.
- **Секреты:** CI/CD Variables для registry tokens; долгоживущие ключи хранятся в Vault, а не в проекте.
- **Артефакты:** хранилище CI артефактов с retention policy (минимум 5–10 релизов для отката).
- **Документация:** общие принципы SBOM и подписи описаны в **[Безопасность цепочки поставок](../../Security/Supply_Chain_Security/overview.md)**; детали Cosign — в **[Подпись артефактов](../../Security/Supply_Chain_Security/artifact_signing.md)**; этот файл фокусируется на контейнеризации фронтенда.

---

## Основные концепции

### Зачем контейнеризировать фронтенд

Даже чистая статика выигрывает от контейнера:
- **Воспроизводимость:** тот же образ запускается в preview, staging и prod.
- **Изоляция:** Node.js процесс SSR не видит файлы хоста, ограничен cgroup.
- **Portability:** образ работает на любом хосте с Docker/Kubernetes.
- **Security:** non-root user, read-only filesystem, drop capabilities.
- **Observability:** стандартизированные метрики и логи через Docker driver.

### Multi-stage Dockerfile для фронтенда

Классический паттерн:
1. **Builder stage:** `node:22-bookworm` — `npm ci`, `npm run build`.
2. **Dependencies stage:** копируем `package.json` и `package-lock.json`, `npm ci --production`.
3. **Final stage:** `nginx:alpine` или `node:22-slim` — только production-файлы.

Multi-stage сборка уменьшает размер образа и исключает `node_modules` с devDependencies из финального образа. Для SSR Next.js используйте standalone-режим, который включает только необходимые рантайм-зависимости.

### Оптимизация слоёв и BuildKit

Порядок инструкций Dockerfile критичен для кэширования:
1. `COPY package*.json ./` — меняется редко.
2. `RUN npm ci` — переиспользует кэш при неизменных зависимостях.
3. `COPY . .` — часто меняется.
4. `RUN npm run build` — зависит от исходников.

Для дополнительного ускорения используйте `--mount=type=cache` для кэша пакетов между сборками. Для pnpm (рекомендуемый менеджер 2026) используйте контентно-адресуемое хранилище (`/pnpm/store`).

### Выбор базового образа

| Тип | Пример | Размер | Когда использовать |
| :--- | :--- | :--- | :--- |
| **Alpine** | `node:22-alpine` | ~50 MB | SSR с нативными модулями; требует `apk add` для build-tools |
| **Slim** | `node:22-slim` | ~100 MB | Статика или SSR без нативных зависимостей; Debian-based |
| **Distroless** | `gcr.io/distroless/nodejs22` | ~70 MB | Минимальная поверхность атаки; нет shell, только рантайм |
| **Nginx Alpine** | `nginx:1.27-alpine` | ~20 MB | Статическая выдача; поддержка Brotli/Gzip |

Для SSR с нативными модулями (`sharp`, `bcrypt`) используйте Alpine и установите build-tools только в builder-стадии. Для максимальной безопасности — distroless, но без возможности входа в контейнер для отладки.

### Security hardening

Минимальный набор:
- **Non-root user:** `USER node` или создание dedicated user с UID >= 1000.
- **Read-only filesystem:** `--read-only` + tmpfs для `/tmp` и `/var/cache/nginx`.
- **Drop capabilities:** `--cap-drop ALL`.
- **Health check:** `HEALTHCHECK` инструкция или `curl http://localhost:3000/healthz`.
- **Resource limits:** cgroup limits для CPU/memory в Kubernetes или `docker run --cpus/--memory`.
- **Tini:** `ENTRYPOINT ["/sbin/tini", "--"]` для корректной обработки `SIGTERM` в SSR.
- **No new privileges:** `--security-opt=no-new-privileges`.

### Package manager в контейнере (2026)

| Менеджер | Рекомендация | Кэширование | Особенности |
| :--- | :--- | :--- | :--- |
| **pnpm** | **Стандарт 2026** | Контентно-адресуемое хранилище (`/pnpm/store`) | Экономит диск, быстрый, workspace-поддержка |
| **npm** | Legacy | `--mount=type=cache,target=/root/.npm` | Стандарт, но медленнее pnpm |
| **yarn (berry)** | Специфичные случаи | `--mount=type=cache,target=/root/.yarn` | PnP-режим, Plug'n'Play |

Используйте `corepack enable && corepack prepare pnpm@latest --activate` в Dockerfile для управления менеджером без глобальной установки.

### Разделение артефактов по окружениям

- **Preview/MR:** изолированные образы от production; retention 1–7 дней.
- **Production:** образы с максимальным TTL, отдельная политика, audit каждого чтения.
- **Static/SSG:** если секреты не нужны в рантайме — исключить их из билда полностью.

### Build-time секреты в Dockerfile

Секреты, необходимые только на этапе сборки:
- **npm registry token:** доступ к приватным пакетам; должен жить только во время `npm ci`.
- **GPG/Cosign ключ:** подпись артефактов; передаётся через Vault и никогда не попадает в слой образа.
- **CDN origin token:** загрузка артефактов в origin-хранилище remote.

Принцип: build-time секреты запрашиваются через BuildKit secrets (`--mount=type=secret`) и не попадают в итоговый слой образа. Общая таблица угроз — в **[Supply Chain Security для фронтенда](./frontend_supply_chain_security.md)**.

---

## Практические сценарии

### Сценарий 1: Multi-stage Dockerfile для SSR (Next.js standalone)

```dockerfile
# syntax=docker/dockerfile:1
FROM node:22-bookworm AS builder
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM node:22-slim
RUN groupadd -r appgroup && useradd -r -g appgroup appuser
WORKDIR /app
COPY --from=builder --chown=appuser:appuser /app/.next/standalone ./
COPY --from=builder --chown=appuser:appuser /app/.next/static ./.next/static
COPY --from=builder --chown=appuser:appuser /app/public ./public
USER appuser
EXPOSE 3000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD curl -f http://localhost:3000/healthz || exit 1
CMD ["node", "server.js"]
```

**Валидация:**
- `docker images frontend:tag` — размер < 200 MB.
- `docker run --rm frontend:tag id -u` — не `0` (non-root).
- `docker run --rm -p 3000:3000 frontend:tag` → `curl http://localhost:3000/healthz` → `200`.

**Troubleshooting:**
- *Обычный пользователь не может читать файлы:* проверьте `--chown` в `COPY --from=builder`.
- *Health check падает:* проверьте `EXPOSE` и путь в `HEALTHCHECK`; убедитесь, что сервер слушает на `0.0.0.0`, а не `127.0.0.1`.
- *Размер образа > 500 MB:* проверьте, что devDependencies не попали в финальный слой; используйте `npm ci --only=production` в отдельной стадии.

### Сценарий 2: Multi-stage для статики + Nginx

```dockerfile
# syntax=docker/dockerfile:1
FROM node:22-bookworm AS builder
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:1.27-alpine
COPY --from=builder /app/dist/ /usr/share/nginx/html/
COPY nginx.conf /etc/nginx/conf.d/default.conf
RUN addgroup -S appgroup && adduser -S appuser -G appgroup
USER appuser
EXPOSE 8080
```

```nginx
# nginx.conf
server {
    listen 8080;
    root /usr/share/nginx/html;
    index index.html;

    location / {
        try_files $uri $uri/ /index.html;
    }

    location ~* \.(?:js|css|woff2?|png|jpg|jpeg|gif|svg|ico)$ {
        expires 1y;
        add_header Cache-Control "public, no-transform";
        access_log off;
    }
}
```

**Валидация:**
- `docker run --rm -p 8080:8080 frontend:tag` → `curl -I http://localhost:8080/assets/main.abc123.js` → `Cache-Control: public, max-age=31536000, immutable`.
- `curl http://localhost:8080/dashboard` → `200` (SPA-роутинг работает).

**Troubleshooting:**
- *SPA-роутинг возвращает 404:* добавьте `try_files $uri $uri/ /index.html;` в `nginx.conf`.
- *Статические файлы не кэшируются:* проверьте regex в `location` и заголовки `Cache-Control`.
- *Nginx не запускается:* проверьте права на директории; создайте PID-файл и назначьте права пользователю `nginx`.

### Сценарий 3: BuildKit Secrets для CI

```dockerfile
# syntax=docker/dockerfile:1
FROM node:22-bookworm AS builder
WORKDIR /app
COPY package*.json ./
RUN --mount=type=secret,id=npm_token \
    NPM_TOKEN=$(cat /run/secrets/npm_token) && \
    npm ci --registry=https://registry.npmjs.org/
COPY . .
RUN npm run build
```

```bash
# Сборка с передачей секрета
DOCKER_BUILDKIT=1 docker build \
  --secret id=npm_token,src=$NPM_TOKEN \
  -t frontend:${CI_COMMIT_SHORT_SHA} .
```

**Валидация:**
- `docker history frontend:tag` — секрет не попал в слой.
- `docker run --rm frontend:tag env` — `NPM_TOKEN` отсутствует.

**Troubleshooting:**
- *Секрет попадает в слой:* убедитесь, что используется `# syntax=docker/dockerfile:1` и `DOCKER_BUILDKIT=1`.
- *npm ci не видит токен:* проверьте путь `/run/secrets/npm_token` и права.
- *BuildKit отключен:* установите `DOCKER_BUILDKIT=1` в окружении CI.

### Сценарий 4: Image Scanning в пайплайне

```yaml
# .gitlab-ci.yml
scan_image:
  stage: test
  image:
    name: aquasec/trivy:0.74.0
    entrypoint: [""]
  script:
    - trivy image --severity CRITICAL,HIGH \
        --exit-code 1 \
        --format cyclonedx \
        --output trivy-report.cdx.json \
        registry.example.com/frontend:${CI_COMMIT_SHORT_SHA}
  allow_failure: false
  artifacts:
    reports:
      dependency_scanning: trivy-report.cdx.json
    expire_in: 1 week
```

**Валидация:**
- `trivy image` возвращает `0` CRITICAL/HIGH уязвимостей.
- Отчёт CycloneDX сохранён как артефакт CI.

**Troubleshooting:**
- *Trivy падает на large image:* используйте `--skip-db-update` и кэширование `trivy-db`.
- *False positives:* примените VEX-отчёт со статусом `not_affected` для уязвимостей, которые недоступны в коде.
- *Long scan time:* сканируйте только финальный stage (`--image`), а не builder.

### Сценарий 5: Cosign подпись и верификация

```bash
# Подпись образа
cosign sign --yes "registry.example.com/frontend:${CI_COMMIT_SHORT_SHA}"

# Аттестация SBOM
syft dir:. -o cyclonedx-json > sbom.cdx.json
cosign attest --predicate sbom.cdx.json --type cyclonedx \
  "registry.example.com/frontend:${CI_COMMIT_SHORT_SHA}"

# Верификация перед деплоем
cosign verify --certificate-identity-regexp '^https://gitlab\.com/org/frontend' \
  --certificate-oidc-issuer https://gitlab.com \
  "registry.example.com/frontend:${CI_COMMIT_SHORT_SHA}"
```

**Валидация:**
- `cosign verify` проходит для всех production-образов.
- SBOM аттестация прикреплена к образу; видна в registry через Referrers API.

**Troubleshooting:**
- *Cosign verify не проходит:* проверьте identity regex и issuer; убедитесь, что реестр поддерживает Referrers API.
- *Аттестация не прикрепляется:* обновите cosign до v3.1+ и убедитесь, что registry поддерживает OCI 1.1.
- *Attestation not found:* для локальных тестов используйте `docker buildx build --output type=docker` и `cosign attest --allow-insecure-registry`.

---

## Операционные команды

| Команда / Инструмент | Назначение | Ожидаемый результат |
| :--- | :--- | :--- |
| `docker build --progress=plain -t frontend:tag .` | Сборка образа | # → успешная сборка, слои кэшированы |
| `docker buildx build --platform linux/amd64,linux/arm64 -t frontend:tag .` | Multi-platform сборка | # → manifest list с архитектурами |
| `docker images frontend:tag` | Проверка размера образа | # → размер < 200 MB для SSR, < 50 MB для статики |
| `docker history frontend:tag` | Анализ слоёв | # → нет секретов в слоях, нет devDependencies |
| `docker run --rm frontend:tag id -u` | Проверка non-root | # → UID >= 1000, не `0` |
| `docker run --rm -p 8080:8080 frontend:tag` | Запуск контейнера | # → контейнер слушает на 8080 |
| `docker inspect --format='{{.State.Health.Status}}' frontend` | Проверка health check | # → `healthy` |
| `trivy image --severity CRITICAL,HIGH --exit-code 1 frontend:tag` | Сканирование образа | # → exit code 0 при отсутствии критических уязвимостей |
| `syft frontend:tag -o cyclonedx-json > sbom.json` | SBOM образа | # → файл `sbom.json` со всеми компонентами |
| `cosign sign --yes registry.example.com/frontend:tag` | Подпись образа | # → подтверждение подписи |
| `cosign verify --identity ... registry.example.com/frontend:tag` | Верификация подписи | # → Verification succeeded |
| `docker buildx build --sbom=true --push -t registry/...` | Сборка с SBOM | # → SBOM прикреплён к образу |
| `docker scout cves frontend:tag` | Анализ уязвимостей | # → отчёт CVE с рекомендациями |
| `docker login registry.example.com` | Аутентификация в registry | # → Login Succeeded |
| `docker tag frontend:tag registry.example.com/frontend:tag` | Тегирование образа | # → тег создан |
| `docker push registry.example.com/frontend:tag` | Публикация в registry | # → изображение опубликовано |

---

## Валидация

- **Размер образа:** `docker images frontend:tag` — ожидается < 200 MB для SSR, < 50 MB для статики.
- **Layer cache:** повторный build без изменения `package*.json` использует кэш (`docker build --progress=plain`).
- **Security scan:** `trivy image` возвращает `0` CRITICAL/HIGH уязвимостей.
- **Non-root:** `docker run --rm frontend:tag id -u` — не `0`.
- **Health check:** `docker inspect --format='{{.State.Health.Status}}' frontend` → `healthy`.
- **Подпись:** `cosign verify` проходит для production-образа.
- **SBOM:** файл содержит все компоненты; прикреплён к образу через Referrers API.
- **Reproducibility:** `docker build` с одинаковым Dockerfile и контекстом даёт идентичный digest на разных хостах.
- **Secrets:** `docker history frontend:tag` — секреты не попали в слои.

---

## Типичные проблемы

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| Размер образа > 1 GB | Dev dependencies в финальном слое | Multi-stage build, `npm ci --only=production` |
| Секрет в слое Dockerfile | `ENV NPM_TOKEN=...` или `ARG` без `--secret` | BuildKit secrets; проверьте `docker history` |
| Обычный пользователь не может читать файлы | Нет `--chown` в `COPY --from=builder` | Добавить `--chown=appuser:appuser` |
| Не работает health check | Неверный endpoint/порт | Проверить `EXPOSE` и путь в `HEALTHCHECK` |
| Уязвимости в базовом образе | Старый `node:22` или `nginx:1.25` | Регулярно обновлять base image, использовать `docker scout` |
| Cosign verify не проходит | Реестр не поддерживает Referrers API | Включить referrers в Harbor, обновить cosign |
| SBOM не прикрепляется | Registry не поддерживает OCI 1.1 | Обновить Harbor до v2.11+ или использовать `docker buildx --sbom` |
| Long build time | Нет кэширования слоёв | Копировать `package*.json` до `COPY . .` |
| Trivy scan очень долгий | Полный scan monorepo на каждый PR | Incremental scan, кэширование trivy-db, only changed packages |
| Разные бинарники на arm64/amd64 | Нет multi-platform manifest | `docker buildx build --platform linux/amd64,linux/arm64` |
| Nginx не запускается | Нет прав на директории | `chown -R nginx:nginx /var/run/nginx.pid /var/cache/nginx` |
| Контейнер не завершается по SIGTERM | Node.js SSR не обрабатывает сигналы | Добавить tini: `ENTRYPOINT ["/sbin/tini", "--"]` |
| npm ci падает в CI | Отсутствует `package-lock.json` | Убедитесь, что lock-файл зафиксирован в git |
| Cache poisoning в CI | Общий ключ кэша между ветками | Используйте `cache:key:files` по lock-файлу |

---

## Особые случаи

- **Stale Service Worker после обновления:** Откат на старый релиз не обновляет SW. Решения: инвалидировать `sw.js` в CDN, добавить баннер обновления, использовать `skipWaiting` + `clients.claim`. Детали — в **[Service Worker и PWA](./service_worker_pwa_cicd.md)**.
- **Race condition: деплой до загрузки ассетов:** Сначала `rsync`/загрузка ассетов, затем `ln -sfn`/инвалидация, затем HTML. Никогда не инвалидируйте до загрузки ассетов.
- **Partial deploy на multi-DC:** Если деплой идёт на несколько дата-центров, откат должен быть синхронным. Проверяйте `readlink` на каждом хосте; используйте orchestration (Ansible, Fleet) вместо ручного `ssh` в цикле.
- **Nginx `try_files` и SPA-маршруты с query-параметрами:** `try_files $uri $uri/ /index.html` не передаёт query string к бэкенду при SSR. Если приложение использует query для маршрутизации, добавьте `$is_args$args` или перейдите на path-based routing.
- **Multi-arch образы:** `docker buildx build` создаёт image index, а не единый манифест. Подписи и аттестации должны генерироваться для каждого архитектурного варианта отдельно.
- **Large SBOM для monorepo:** Генерация SBOM для 100+ пакетов замедляет пайплайн. Решения: инкрементальный SBOM (только изменённые пакеты), кэширование SBOM артефакта, отключение `syft` для preview-сред.
- **Nginx на read-only ФС:** Для read-only контейнера перенаправьте логи и PID в tmpfs: `--tmpfs /var/cache/nginx:rw,size=10m --tmpfs /var/run:rw,size=1m --tmpfs /tmp:rw,size=10m`.
- **Эфемерные раннеры без remote cache:** При каждом pipeline создаётся новый runner, локальный кэш не сохраняется. Без remote cache каждый прогон собирает всё с нуля. Решение: настройте S3-совместимый бакет (MinIO) или self-hosted Nx cache server.

---

## Инцидент: compromised container image

1. **Немедленный отзыв:** отозвать скомпрометированный образ из registry; удалить тег или пометить digest как удалённый.
2. **Ротация:** сгенерировать новые registry tokens в Vault; обновить CI/CD Variables.
3. **Аудит:** проверить registry audit logs и логи CI на предмет подозрительной активности.
4. **Очистка:** удалить скомпрометированные слои из registry; опубликовать исправление.
5. **Постмортем:** blameless postmortem, обновление политик доступа и правил сканеров.

Полный runbook — в **[Supply Chain Incident Response](../../Security/Supply_Chain_Security/supply_chain_incident_response.md)**.

---

## Лучшие практики

1. Используйте multi-stage build: SDK для сборки, alpine/slim/distroless для рантайма.
2. Запускайте процесс от non-root пользователя с UID >= 1000.
3. Используйте `HEALTHCHECK` для оркестратора (Kubernetes, Docker Swarm).
4. Храните секреты во внешней системе (Vault), используйте BuildKit secrets, не передавайте через `ARG`/`ENV`.
5. Сканируйте образ Trivy/Grype перед push в registry.
6. Подписывайте production-образы Cosign; проверяйте подпись при деплое.
7. Используйте Distroless или Alpine base для минимальной поверхности атаки.
8. Для SSR-контейнеров добавляйте `tini` как PID 1, чтобы `SIGTERM` доходил до Node.
9. Копируйте lock-файл (`package*.json`) до исходного кода для эффективного кэширования слоёв.
10. Используйте `npm ci` (а не `npm install`) для детерминированной сборки в CI.
11. Для read-only контейнеров используйте tmpfs для временных директорий (`/tmp`, `/var/cache/nginx`, `/var/run`).
12. Для monorepo используйте incremental SBOM и кэширование Trivy DB.

---

## Дополнительная информация

### См. также

- **[Безопасность цепочки поставок](../../Security/Supply_Chain_Security/overview.md)** — общие концепции SLSA, SBOM, threat model.
- **[Подпись артефактов](../../Security/Supply_Chain_Security/artifact_signing.md)** — Cosign, Notation, VSA и проверка подписей.
- **[Dockerfile: Лучшие практики для Frontend](../../Docker/Dockerfile/Docker_best_practices/frontend.md)** — детальные Dockerfile-паттерны для SPA/SSR.
