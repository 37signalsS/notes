# Миграция в Harbor: из Docker Hub и других реестров

**Актуально для:** Harbor 2.15.x, skopeo v1.14+–v1.23+, cosign v3.x, crane v0.21.x, Docker Hub API 2-beta

## Определения

* **Миграция реестра (Registry Migration)**: Перенос образов из одного реестра в другой (Docker Hub, plain Docker Registry, GitLab Registry, Nexus → Harbor) без пересборки. Гарантия неизменности бинарного кода — перенос по digest.
* **Инвентаризация (Inventory)**: Список репозиториев и тегов в источнике, на основе которого строится план миграции. Для Docker Hub — через Docker Hub API; для OCI-реестров с поддержкой `_catalog` — через `crane catalog` / `regctl repo ls`.
* **Cutover**: Момент переключения всех потребителей (CI/CD, Kubernetes, Docker-демоны) со старого реестра на Harbor.
* **Digest-сверка**: Проверка того, что digest образа в Harbor совпадает с digest в источнике — единственный способ гарантировать, что перенесён именно тот артефакт, который был протестирован.
* **Throttle**: Искусственное снижение скорости миграции (паузы между репозиториями, off-peak окно) для укладывания в rate limits источника.
* **PAT / OAT**: Personal Access Token (пользовательский токен Docker Hub) и Organization Access Token (токен организации для автоматизации) — способы аутентификации в Docker Hub API вместо пароля.

## Основные концепции

### Миграция vs Proxy Cache vs Replication

Три разных способа получить образы Docker Hub в Harbor — выбирайте по цели:

| Механизм | Что делает | Когда применять |
| :--- | :--- | :--- |
| **Миграция** (этот файл) | Копирует образы один раз (или по расписанию), образы живут в Harbor как обычные артефакты проекта | Полный уход с Docker Hub (rate limits, compliance, air-gapped), единый источник истины, контроль RBAC/сканирования |
| **Proxy Cache** ([usage.md, сценарий 6](./usage.md#сценарий-6-настройка-proxy-cache-pull-through-cache)) | Прозрачно кэширует pull из upstream при первом запросе; push в проект-кэш отклонён | Обход rate limits без изменения потребителей; образы не «живут» в Harbor |
| **Replication** ([replication.md, сценарий 3](./replication.md#сценарий-3-pull-based-репликация-по-расписанию)) | Pull-based синхронизация по правилу (фильтры, триггеры, override) | Регулярное затягивание обновлений из внешнего реестра в изолированный контур |

### Фазы миграции

1. **Инвентаризация** — список репозиториев/тегов источника (Docker Hub API).
2. **Планирование** — что мигрировать (все теги или только актуальные), квоты Harbor, окно миграции (SRE: off-peak, error budget).
3. **Пилот** — один образ end-to-end: copy → verify → pull из Harbor.
4. **Массовая миграция** — `skopeo sync` по инвентарю с `--preserve-digests`.
5. **Перенос подписей** — `cosign copy` или переподпись (подписи не переносятся автоматически).
6. **Верификация в масштабе** — сверка digest по всем репозиториям/тегам.
7. **Cutover** — переключение потребителей (SRE: атомарно, с мониторингом по сценарию 8).
8. **Rollback-план** — источник остаётся источником истины до полной верификации.

> **SRE-замечание:** миграция — изменение конфигурации с высоким риском service degradation. Планируйте окно так, чтобы остаточный error budget (SLO 99.9% ≈ 43 минуты деградации в месяц) покрывал миграцию и возможный откат. Мониторинг и алерты — по сценарию 8.

### Инструменты

| Инструмент | Роль в миграции | Особенности |
| :--- | :--- | :--- |
| `skopeo copy` | Один образ (все платформы с `--all`) | `--preserve-digests` — сохраняет digest; `--retry-times`/`--retry-delay` |
| `skopeo sync` | Массовая синхронизация репозитория (все теги) | Источник — **один репозиторий**, не namespace; `--keep-going` не останавливаться на ошибках; `--digestfile` — дайджесты для верификации; `--dry-run` |
| `crane copy` / `crane ls` | Альтернатива copy; `crane ls` — список тегов | Daemonless; `crane catalog` требует поддержки `_catalog` (Docker Hub не поддерживает для произвольных org) |
| `regctl` | Ротация тегов, инспекция манифестов | `regctl repo ls` — каталог (тоже требует `_catalog`) |
| `cosign copy` | Перенос подписей и аттестаций между реестрами | Подписи — OCI 1.1 Referrers; `skopeo sync` старых версий их не копирует |

### Rate limits при миграции

Два независимых лимита Docker Hub ([public_registry_security.md](../public_registry_security.md)):

* **Pull limits**: 100 pull/6h (анонимный, per IPv4 или IPv6 /64), 200 pull/6h (аутентифицированный Personal). При превышении — `429` с развёрнутым сообщением.
* **API limits** (hub.docker.com): заголовки `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset`; при превышении — `429` + `Retry-After` (секунды). Отдельно от pull limits.

Тактика укладывания: аутентифицированные pulls (учётные данные в `skopeo`/YAML-инвентаре), off-peak окно, `--retry-times`/`--retry-delay` (экспоненциальный backoff), `--keep-going`, паузы между репозиториями, мониторинг `X-RateLimit-Remaining`.

## Предварительные требования

| Требование | Проверка | Примечание |
| :--- | :--- | :--- |
| Harbor развёрнут и доступен | `curl -sk https://harbor.corp.local/api/v2.0/health` | TLS и доверие CA — [certificates.md](./certificates.md) |
| Проекты в Harbor созданы | UI или API `/api/v2.0/projects` | Структура `<team>-<env>` ([hardening.md](./hardening.md)) |
| Квоты проектов проверены | `harbor_project_quota_usage_byte` | Массовый push упирается в квоту — проверьте заранее |
| Robot-аккаунт для push | Формат `robot$<project>+<name>` | Права Pull+Push ([usage.md, сценарий 2](./usage.md#сценарий-2-использование-робот-аккаунтов-в-cicd)) |
| Учётные данные Docker Hub | PAT (рекомендуется) или пароль | Для API и для pulls; OAT — для автоматизации org |
| `skopeo`, `cosign`, `jq` | `skopeo --version` | Установлены на хосте миграции |
| Сеть: миграционный хост видит оба реестра | `curl -sI https://registry-1.docker.io/v2/` | Пропускная способность канала |
| Error budget (SRE) | Сравнение SLO registry и ожидаемой деградации | См. [operations.md, сценарий 6](./operations.md#сценарий-6-slo-sli-i-error-budget) |
| Алерты на cutover готовы | `harbor_artifact_pulled`, `ImagePullBackOff`, квота | См. сценарий 8 |

## Практические сценарии

### Сценарий 1: Инвентаризация образов в Docker Hub

Docker Hub не поддерживает `_catalog` для произвольных организаций — инвентаризация через Docker Hub API.

```bash
# 1. Токен (username + PAT; PAT предпочтительнее пароля)
TOKEN=$(curl -s -X POST -H "Content-Type: application/json" \
  -d '{"username":"'"$DOCKER_USER"'","password":"'"$DOCKER_PAT"'"}' \
  https://hub.docker.com/v2/users/login/ | jq -r .token)

# 2. Список репозиториев организации (пагинация: page, page_size; ответ: results, next)
curl -s -H "Authorization: Bearer $TOKEN" \
  "https://hub.docker.com/v2/namespaces/myorg/repositories?page_size=100" | \
  jq -r '.results[].name'
# → myapp
# → web
# → worker

# 3. Теги конкретного репозитория
curl -s -H "Authorization: Bearer $TOKEN" \
  "https://hub.docker.com/v2/namespaces/myorg/repositories/myapp/tags?page_size=100" | \
  jq -r '.results[].name'

# 4. Остаток API-лимита (отдельный от pull-лимита)
curl -sI -H "Authorization: Bearer $TOKEN" \
  "https://hub.docker.com/v2/namespaces/myorg/repositories?page_size=1" | \
  grep -i x-ratelimit
# → X-RateLimit-Limit: ...
# → X-RateLimit-Remaining: ...
```

**YAML-инвентарь для `skopeo sync`** (поддерживает фильтры по тегам и SemVer-диапазоны):

```yaml
# inventory.yaml
docker.io:
  images:
    myorg/myapp: []          # [] — все теги репозитория
    myorg/web:
      - "1.4"
      - "1.5"
  images-by-tag-regex:
    myorg/api: ^v\d+\.\d+\.\d+$     # только SemVer-теги
  images-by-semver:
    myorg/worker: ">= 2.0.0"        # SemVer-диапазон
  credentials:
    username: myorg-ci
    password: "$DOCKER_PAT"
  tls-verify: true
```

> Пагинация API: обходите все страницы по `next` в ответе, пока `next` не станет `null`. Legacy-путь `GET /v2/repositories/{namespace}/` работает с PAT/password, но **отклоняет OAT** с `403 token issued from organization access token is not allowed` — для автоматизации используйте `/v2/namespaces/`.

### Сценарий 2: Пилотная миграция одного образа

Перед массовой миграцией проверьте цикл end-to-end на одном образе:

```bash
# 1. Копирование всех платформ с сохранением digest
skopeo copy --all --preserve-digests \
  docker://docker.io/myorg/myapp:1.4.2 \
  docker://harbor.corp.local/myproject/myapp:1.4.2
# → Copying blob ... Copying config ... Writing manifest to image destination

# 2. Сверка digest (должен совпадать)
skopeo inspect --format '{{.Digest}}' docker://docker.io/myorg/myapp:1.4.2
skopeo inspect --format '{{.Digest}}' docker://harbor.corp.local/myproject/myapp:1.4.2
# → sha256:<одинаковый digest>

# 3. Multi-arch: в Harbor должен быть полный manifest list
skopeo inspect --raw docker://harbor.corp.local/myproject/myapp:1.4.2 | \
  jq '.manifests[].platform'
# → {"architecture":"amd64","os":"linux"}
# → {"architecture":"arm64","os":"linux"}

# 4. Pull из Harbor как конечный потребитель
docker pull harbor.corp.local/myproject/myapp:1.4.2
```

### Сценарий 3: Массовая миграция

```bash
# 1. Dry-run — оценка объёма без копирования
skopeo sync --src yaml --dest docker --dry-run inventory.yaml harbor.corp.local/

# 2. Массовая синхронизация репозитория (все теги, все платформы)
skopeo sync --src docker --dest docker --all --preserve-digests \
  --keep-going --retry-times 5 --retry-delay 30s \
  --digestfile digests-myapp.txt \
  docker://docker.io/myorg/myapp harbor.corp.local/myproject
# → Copying blob ... (для каждого тега)

# 3. Throttle: пауза между репозиториями при цикле по организации
for REPO in $(cat repos.txt); do
  skopeo sync --src docker --dest docker --all --preserve-digests \
    --keep-going --retry-times 5 \
    "docker://docker.io/myorg/$REPO" "harbor.corp.local/myproject"
  sleep 60   # укладываемся в rate limits
done

# 4. Или целым инвентарём из YAML (сценарий 1)
skopeo sync --src yaml --dest docker --all --preserve-digests \
  --keep-going --retry-times 5 --digestfile digests-all.txt \
  inventory.yaml harbor.corp.local/
```

> `skopeo sync` синхронизирует **один репозиторий** (все теги, если тег не указан), а не namespace целиком — для организации нужен цикл по репозиториям или YAML-инвентарь. `--digestfile` записывает дайджесты скопированных образов с их reference — используйте его для верификации (сценарий 6).

### Сценарий 4: Перенос подписей и аттестаций

Подписи Cosign и аттестации (SBOM, SLSA) хранятся как OCI 1.1 Referrers и **не переносятся автоматически** при миграции — ни `skopeo copy`, ни `skopeo sync` не копируют Referrers (в `skopeo` флаг `--all` отвечает за копирование всех платформ multi-arch, а не за Referrers). Подписи, сделанные sigstore-стилем (`.sig`), копируются `skopeo copy` по умолчанию, но Referrers-артефакты (аттестации, SBOM) — нет:

```bash
# 1. Перенос подписей cosign copy (src → dst, включая аттестации)
cosign copy docker.io/myorg/myapp:1.4.2 harbor.corp.local/myproject/myapp:1.4.2

# 2. Проверка подписи в Harbor
cosign verify --key cosign.pub harbor.corp.local/myproject/myapp:1.4.2
# → Verification OK

# 3. Альтернатива — переподпись в Harbor (если копирование недоступно)
cosign sign --yes harbor.corp.local/myproject/myapp:1.4.2
```

> Подписи привязаны к digest образа. При `--preserve-digests` digest не меняется, поэтому подпись, сделанная в источнике, валидна и в Harbor — достаточно перенести саму подпись (`cosign copy`) или переподписать. Аттестации (SBOM, SLSA) требуют отдельного переноса через `cosign copy` или `cosign attest` в Harbor.

### Сценарий 5: Cutover (переключение потребителей)

Переключайте потребителей атомарно, после верификации (сценарий 6):

```bash
# 1. CI/CD: переменные реестра и учётные данные
# GitLab CI: CI_REGISTRY=harbor.corp.local, CI_REGISTRY_USER=robot$myproject+ci
# GitHub Actions: REGISTRY=harbor.corp.local, секрет с robot-аккаунтом

# 2. Kubernetes: imagePullSecrets для Harbor
kubectl create secret docker-registry harbor-pull \
  --docker-server=harbor.corp.local \
  --docker-username='robot$myproject+deploy' \
  --docker-password="$ROBOT_SECRET" \
  -n production
kubectl patch serviceaccount default -n production \
  -p '{"imagePullSecrets":[{"name":"harbor-pull"}]}'

# 3. Образы в манифестах: новый registry (или digest — см. image_versioning_and_tagging.md)
# image: harbor.corp.local/myproject/myapp:1.4.2

# 4. Docker-демоны хостов (если использовался mirror Docker Hub)
# daemon.json: registry-mirrors работает ТОЛЬКО для Docker Hub — для Harbor
# обращайтесь напрямую или маршрутизируйте через hosts.toml containerd

# 5. DNS: за день до cutover снизьте TTL A-записи реестра
```

**Порядок cutover:** dev-проекты → staging → production; после каждого этапа — мониторинг `harbor_artifact_pulled{project_name=...}` и логов kubelet на предмет `ImagePullBackOff`.

### Сценарий 6: Верификация в масштабе

```bash
# 1. Сверка digest по всем тегам репозитория (source vs Harbor)
for TAG in $(skopeo list-tags docker://docker.io/myorg/myapp | jq -r '.Tags[]'); do
  SRC=$(skopeo inspect --format '{{.Digest}}' docker://docker.io/myorg/myapp:$TAG)
  DST=$(skopeo inspect --format '{{.Digest}}' docker://harbor.corp.local/myproject/myapp:$TAG)
  [ "$SRC" = "$DST" ] && echo "OK $TAG" || echo "MISMATCH $TAG: $SRC != $DST"
done

# 2. Сверка по digestfile (выход skopeo sync --digestfile)
# Формат: <digest> <reference>
awk '{print $1}' digests-all.txt | sort | uniq -c | sort -rn | head
# → каждый digest должен встречаться ровно 2 раза (source + target)

# 3. Через Harbor API: число артефактов в проекте vs инвентарь
curl -sk -u "admin:$PASS" \
  "https://harbor.corp.local/api/v2.0/projects/myproject" | \
  jq '.artifact_count'
```

**Критерий успеха:** 100% тегов с совпадающим digest; multi-arch образы — полный manifest list в Harbor; подписи верифицируются.

### Сценарий 7: Rollback-план

1. **До полной верификации Docker Hub остаётся источником истины** — не удаляйте образы из Docker Hub.
2. Rollback = обратное переключение потребителей (сценарий 5 в обратную сторону): CI/CD-переменные, `imagePullSecrets`, манифесты.
3. Если Harbor уже принимает push-ы новых сборок: новые теги есть только в Harbor — перед откатом синхронизируйте их обратно в Docker Hub (`skopeo sync` в обратном направлении) или примите потерю.
4. Фиксируйте результаты: дата cutover, фактическое время, обнаруженные проблемы (по аналогии с DR drill в [upgrade_backup.md, сценарий 7](./upgrade_backup.md#сценарий-7-dr-drill-тренировка-восстановления)).

### Сценарий 8: SRE — мониторинг и алерты во время миграции

Миграция — высокорисковая операция: потребители переключаются мгновенно, а не плавно. Мониторинг строится на метриках Harbor (список и alert-правила — в [operations.md, сценарий 2](./operations.md#сценарий-2-мониторинг-и-алерты-prometheus)):

```bash
# 1. Алерта: падение pull-активности из Harbor (признак cutover-сбоя)
# PromQL: rate(harbor_artifact_pulled[5m]) == 0
# → сработает, если потребители не тянут из Harbor после переключения

# 2. Алерта: рост ImagePullBackOff в кластере (Kubernetes)
# kubectl get pods -A -o wide | grep -i ImagePullBackOff
# → индикация, что где-то манифест содержит старый registry или digest не совпадает

# 3. Алерта: превышение квоты проекта во время массового push
# harbor_project_quota_usage_byte > 0.9 * harbor_project_quota_byte
# → миграция упирает в квоту; увеличьте лимит или мигрируйте по частям

# 4. Burn rate: темп ошибок относительно SLO
# Пример SLO: 99.9% успешных registry-запросов за 30 дней
# → error budget = 0.1% (≈ 43 минуты деградации в месяц)
#   burn rate > 1 означает, что при текущем уровне ошибок SLO на месяц будет violated
# Детали и формула — [operations.md, сценарий 6](./operations.md#сценарий-6-slo-sli-i-error-budget)
```

**Чек-лист мониторинга перед cutover:**
- [ ] Алерты на `harbor_artifact_pulled == 0` (5m) — ловит отсутствие pull-активности после переключения.
- [ ] Алерты на `ImagePullBackOff` в кластере — ловит старые registry/digest в манифестах.
- [ ] Алерты на квоту проекта — ловит mass-push, превышающий лимит.
- [ ] Burn-rate алерты по SLO 99.9% — ловит деградацию registry во время миграции.
- [ ] Мониторинг `X-RateLimit-Remaining` Docker Hub во время инвентаризации — ловит `429` до и во время миграции.

## Валидация

```bash
# 1. Harbor здоров
curl -sk https://harbor.corp.local/api/v2.0/health
# → {"status":"healthy"}

# 2. Образ доступен и digest совпадает с источником
skopeo inspect --format '{{.Digest}}' docker://harbor.corp.local/myproject/myapp:1.4.2
# → sha256:<совпадает с Docker Hub>

# 3. Multi-arch полный
skopeo inspect --raw docker://harbor.corp.local/myproject/myapp:1.4.2 | jq '.manifests | length'
# → 2 (amd64 + arm64)

# 4. Подпись верифицируется
cosign verify --key cosign.pub harbor.corp.local/myproject/myapp:1.4.2 && echo "verified"

# 5. Потребитель тянет из Harbor
docker pull harbor.corp.local/myproject/myapp:1.4.2
# → Status: Downloaded newer image for harbor.corp.local/myproject/myapp:1.4.2
```

## Устранение неполадок

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `429` во время sync | Превышен pull limit или API limit Docker Hub | Аутентифицированные pulls; off-peak окно; `--retry-times`/`--retry-delay`; паузы между репозиториями; мониторинг `X-RateLimit-Remaining` |
| Sync останавливается на первом же образе | Ошибка одного тега без `--keep-going` | Добавьте `--keep-going` — ошибки логируются, sync продолжается, финальный exit code отражает failures |
| `manifest unknown` в Harbor после sync | Тег удалён в источнике во время миграции | Повторите sync для этого репозитория |
| Multi-arch образ в Harbor одноплатформенный | Забыт `--all` | Перезапустите sync/copy с `--all` |
| Подписи не появились в Harbor | `skopeo sync` не копирует Referrers (старые версии) | `cosign copy` или переподпись в Harbor (сценарий 4) |
| Digest не совпадает | `--preserve-digests` не указан или ретегирование | Перенесите с `--preserve-digests`; сверьте digest (сценарий 6) |
| `403 token issued from organization access token is not allowed` | OAT на legacy-пути API `/v2/repositories/` | Используйте `/v2/namespaces/{namespace}/repositories` |
| Windows-образы без базовых слоёв | Foreign layers не копируются по умолчанию | `--download-foreign-layers` |
| Push в Harbor отклонён | Immutable tag в целевом проекте + повторный sync того же тега | Отключите override для правила или удалите тег перед повторным sync |
| Sync не находит репозиторий | Docker Hub требует auth для приватных org | `--src-creds user:pat` или `credentials` в YAML-инвентаре |

## Граничные случаи

* **Namespace целиком не синхронизируется одной командой**: `skopeo sync` работает с одним репозиторием; для организации — цикл по инвентарю или YAML-файл.
* **Теги с `+`** (SemVer build-метаданные `1.0.0+build.5`) недопустимы в Docker-тегах — при инвентаризации такие теги не встретятся, но в фильтрах `images-by-tag-regex` учитывайте это.
* **Immutable tags в Harbor**: повторная миграция того же тега в проект с immutable-тегами отклоняется — планируйте re-sync с учётом override.
* **Квоты Harbor**: массовый push может упереться в квоту проекта (`QUOTA_EXCEED`) — проверьте квоты до миграции.
* **Общие слои дедуплицируются**: при миграции многих образов с общими базовыми слоями Harbor хранит каждый blob один раз — реальный объём меньше суммы размеров образов.
* **Docker Hub как источник после cutover**: пока не удалены образы из Docker Hub, откат дешёвый; удаляйте только после месяца стабильной работы Harbor.

## Лучшие практики

* **Пилот перед массовой миграцией**: один образ end-to-end (copy → verify → pull) перед каждым крупным переносом.
* **`--dry-run` перед реальным sync** — оценка объёма и списка тегов без копирования.
* **Всегда `--preserve-digests`** + сверка digest — гарантия неизменности артефакта.
* **Off-peak окно** для массовой миграции + throttle между репозиториями.
* **Переносите подписи** (`cosign copy`) или переподписывайте в Harbor — иначе Deployment Security и верификация подписей в Harbor не работают для мигрированных образов.
* **Атомарный cutover**: все потребители (CI/CD, K8s, Docker-демоны) переключайте вместе, сразу после верификации.
* **Мониторьте после cutover**: `harbor_artifact_pulled{project_name}`, алерты на `ImagePullBackOff` в кластере (сценарий 8).
* **Документируйте миграцию**: инвентарь, дата, digest-файлы, результаты верификации — пригодится для аудита и отката.
* **Планируйте error budget**: миграция и откат должны укладываться в остаточный budget по SLO registry (99.9% ≈ 43 минуты деградации в месяц).

## См. также

* **[Миграция из других реестров](./upgrade_backup.md#сценарий-6-миграция-из-других-реестров)** — краткий сценарий в upgrade/backup-файле; этот файл — полный runbook.
* **[Работа с Harbor](./usage.md)** — robot-аккаунты, proxy cache (альтернатива миграции), квоты.
* **[Репликация](./replication.md)** — pull-based синхронизация по расписанию (альтернатива разовой миграции).
* **[Версионирование и тегирование](../image_versioning_and_tagging.md)** — digest pinning, immutable tags, `imagePullPolicy`.
* **[Безопасность публичных реестров](../public_registry_security.md)** — rate limits Docker Hub, digest pinning.
* **[Подпись и верификация образов](../../Docker_security/image_signature_and_verification.md)** — Cosign, `cosign copy`, keyless signing.
* **[Skopeo](../../../Podman/skopeo_overview.md)** — daemonless-операции с образами.
* **[Docker Hub API](https://docs.docker.com/docker-hub/api/latest/)** — reference эндпоинтов, пагинация, OAT/PAT.
* **[skopeo sync](https://github.com/containers/skopeo/blob/main/docs/skopeo-sync.1.md)** — флаги `--all`, `--preserve-digests`, `--digestfile`, YAML-инвентарь.
