# Политика свежести образов и управление EOL

**Актуально для:** Docker Engine 29.8.x (актуальный релиз — 29.8.2, сентябрь 2026). Docker Engine 28.x и ранее достигли EOL (май 2026). Trivy 0.75.x, Renovate 44.x, Dependabot. Версионирование и ловушки тегов — SSoT в [image_versioning_and_tagging.md](../Docker_registries/image_versioning_and_tagging.md). Автообновление в Podman — в [podman_auto_update.md](../../Podman/podman_auto_update.md).

## Определения

**EOL / EOSL (End of Life / End of Service Life)** — дата, после которой версия ОС или базового образа перестаёт получать security-патчи. Образ на EOL-ОС накапливает непропатченные CVE.

**Freshness (свежесть)** — актуальность образа относительно upstream security-патчей. Устаревший образ — security-дефект даже при нуле известных CVE в момент сканирования.

**Digest rotation** — ротация pinned digest (`image@sha256:...`) на актуальный при patch-обновлении базового образа. Пининг без ротации фиксирует образ в том числе и на старых патчах.

**Stale image** — образ, который давно не пересобирался: базовый слой устарел, а приложение не получило обновлений транзитивных зависимостей.

**EOL imminent** — образ, находящийся в зоне риска (обычно ≤90 дней до официальной даты EOL). Требует планирования миграции до наступления EOL.

## Предварительные требования

**Инструменты:**
- Docker Engine 29.8.x (29.8.2+); 28.x и ранее — EOL (май 2026).
- Trivy 0.75.x (`--exit-on-eol`, `--format json`, `--severity`).
- Renovate 44.x с пресетом `docker:pinDigests` или Dependabot 2.x с `dockerfile` ecosystem.
- `eol-scanner` (опционально) — сопоставляет Trivy JSON с endoflife.date и генерирует SARIF/HTML.
- `jq`, `yq` — парсинг JSON/YAML отчётов в CI.
- Доступ к upstream registry (Docker Hub, registry.redhat.io и др.) для проверки последних тегов.

**Права и доступ:**
- CI runner: доступ к docker pull (public registry) или registry mirror.
- Git: права на создание PR (Renovate/Dependabot).
- Реестр production: write-доступ для ротации digest и promotion.

## Базовые концепции

### Почему устаревший образ — security risk

1. **EOL-ОС не получает патчи.** После EOL (например, Alpine 3.20 — EOL с 1 апреля 2026; Alpine 3.21 — EOL с 1 ноября 2026; Ubuntu 20.04 standard — EOL с мая 2025; Debian 12 regular support — EOL с 11 июля 2026) новые CVE в пакетах не исправляются.
2. **Ложное «0 уязвимостей».** Trivy может показать 0 CVE на очень старом образе: пакеты удалены из базы уязвимостей или все CVE помечены `unfixed`. Флаг `--exit-on-eol` ловит этот случай явно.
3. **Жизненный цикл базового образа:** upstream release → security patches → EOL → unsupported. Политика свежести отслеживает, на какой фазе находится каждый образ.
4. **Языковые рантаймы внутри образа.** Даже если ОС поддерживается, устаревший Python/Node/Go в образе имеет собственный EOL (например, Python 3.8 — EOL с октября 2024). Trivy выявляет их как `unfixed` или `ignored`, но они остаются эксплуатационным риском.

### Кто отслеживает EOL

| Источник | Механизм |
| :--- | :--- |
| Trivy | Встроенные данные EOL по ОС (Alpine, Debian, Ubuntu, RHEL, SUSE и др.); `--exit-on-eol` |
| endoflife.date | Внешний агрегатор дат EOL для 450+ продуктов; инструмент `eol-scanner` сопоставляет с Trivy JSON |
| GitLab Container Scanning | `CS_REPORT_OS_EOL` (на базе Trivy EOSL-метаданных), severity по умолчанию Medium |
| Renovate / Dependabot | Автообновление `FROM`-образов в Dockerfile |

## Практические сценарии

### Сценарий 1: детекция EOL в CI

```bash
# Fail сборки на EOL-ОС и CRITICAL CVE
trivy image --exit-code 1 --exit-on-eol 1 --severity CRITICAL my-app:v1
# → WARN This OS version is no longer supported by the distribution: alpine 3.20.9
# → ERROR Detected EOL OS: alpine 3.20.9
# → exit code 1

# Для SARIF (GitHub Advanced Security / GitLab):
trivy image --format sarif --exit-on-eol 1 --severity CRITICAL -o trivy.sarif my-app:v1

# Доступно для: trivy image, trivy vm, trivy sbom, trivy rootfs
```

**Правило:** `--exit-on-eol 1` обязателен в CI вместе с `--exit-code 1` — иначе EOL-образ проходит gate при «0 уязвимостей». Для multi-stage сборок прогоняйте каждый финальный stage.

### Сценарий 2: автообновление базовых образов (Renovate)

Renovate обновляет образы в Dockerfile через `dockerfile` manager:

```json
// renovate.json
{
  "extends": ["config:base", "docker:pinDigests"],
  "packageRules": [
    {
      "datasource": "docker",
      "updateTypes": ["patch", "digest"],
      "automerge": true
    },
    {
      "datasource": "docker",
      "updateTypes": ["major", "minor"],
      "automerge": false
    }
  ]
}
```

Что покрывает `dockerfile` manager:
- `FROM <image>` (включая multi-stage сборки)
- `COPY --from=<image>`
- `RUN --mount=from=<image>`
- `syntax=docker/dockerfile:<version>`
- пакеты `apk add` / `apt install` / `apt-get install` (через `apk`/`deb` datasources; поддерживается с Renovate 44.100.0+)

Пресет `docker:pinDigests` автоматически пинит образы по digest; `updateTypes: ["patch", "digest"]` с automerge — безопасная стратегия: patch-обновления базовых образов вливаются автоматически, major/minor требуют ревью.

### Сценарий 3: Dependabot (альтернатива Renovate)

```yaml
# .github/dependabot.yml
version: 2
updates:
  - package-ecosystem: "dockerfile"
    directory: "/"
    schedule:
      interval: "daily"
    open-pull-requests-limit: 10
```

Dependabot отслеживает `FROM`-образы и предлагает PR на обновление тегов; для digest-пининга используйте Renovate (Dependabot не пинит digest автоматически).

### Сценарий 4: политика ротации образов

| Правило | Значение | Обоснование |
| :--- | :--- | :--- |
| Max возраст базового образа | 90 дней | Ограничение накопления непропатченных CVE |
| Rebuild base images | еженедельно | Транситивные обновления безопасности |
| Digest rotation | при каждом patch-обновлении base | Пининг без ротации фиксирует старые патчи |
| EOL-образы в production | 0 | `--exit-on-eol` в CI |
| Stale detection | ежедневно | Образы без пересборки > 90 дней — на ревью |

```bash
# Stale-образы на хосте: возраст с момента сборки
docker images --format '{{.Repository}}:{{.Tag}}\t{{.CreatedSince}}' | sort
# → my-app:v1    3 months ago
# → nginx:1.27    2 weeks ago

# Образы, не использовавшиеся (кандидаты на удаление)
docker image prune -a --filter "until=720h" --dry-run
```

### Сценарий 5: Podman auto-update (для Podman-сред)

В Podman-средах автообновление — через `podman auto-update` с `io.containers.autoupdate` label и systemd-таймером; пошаговая настройка — в [podman_auto_update.md](../../Podman/podman_auto_update.md).

## Устранение неполадок

| Симптом | Вероятная причина | Диагностика и решение |
| :--- | :--- | :--- |
| Trivy показывает 0 CVE на старом образе | EOL-ОС, пакеты вне базы, `--exit-on-eol` отсутствует | Добавить `--exit-on-eol 1`; проверить дату EOL ОС на endoflife.date; Trivy 0.75.x выводит WARN/ERROR при EOL |
| Renovate не обновляет `FROM` | Файл не матчится или manager отключён | Проверить `managerFilePatterns` (по умолчанию `/(^|/|.)([Dd]ocker|[Cc]ontainer)file.../`); включить `dockerfile` manager; обновить до Renovate 44.x |
| Renovate не обновляет `apt install` пакеты | Версия <44.100.0 или нет `registryUrls` | Обновить Renovate до ≥44.103.0; добавить `registryUrls` для нужного дистрибутива в `packageRules` |
| Digest-update ломает сборку | Breaking change в base image или registry mirror не имеет нового digest | Пинить minor-версию (`node:20-slim`, не `node:latest`); проверить доступность digest в corporate mirror; тестировать digest-updates в CI |
| Automerge patch-обновлений падает | Нестабильный base tag или CI failure | Отключить automerge для проблемного образа через `packageRules` по `depName`; проверить CI stability |
| Образ «завис» на старом digest | Ручной пин без ротации или Renovate отключён | Включить `docker:pinDigests` + digest-update PRs; ротировать digest при patch-апдейтах |
| Dependabot не предлагает digest-updates | Ограничение Dependabot | Dependabot не пинит digest; для digest-ротации используйте Renovate |
| EOL-сканер показывает stale data (>30 дней) | Встроенный EOL датасет устарел | Пересобрать eol-scanner: `./scripts/fetch_eol_data.sh && go build -ldflags="-s -w" -o eol-scanner ./cmd/eol-scanner/` |

## Лучшие практики

1. **`--exit-on-eol` в CI** — EOL-образ не должен проходить gate даже при 0 CVE. Используйте Trivy 0.75.x с `--exit-on-eol 1 --exit-code 1 --severity CRITICAL,HIGH`.
2. **Автоматизировать обновления** — Renovate 44.x (`docker:pinDigests` + automerge patch/digest) или Dependabot 2.x (`dockerfile` ecosystem). Для apt/apk пакетов внутри Dockerfile — только Renovate.
3. **Пинить по digest и ротировать** — пининг без ротации фиксирует и уязвимости; ротация digest — часть patch-процесса. Renovate генерирует PR при каждом digest-update.
4. **Max age policy** — 90 дней для базовых образов; stale-образы — на ревью. Используйте `docker image prune -a --filter "until=720h"` в maintenance-окне.
5. **Отслеживать upstream EOL** — endoflife.date для ОС и языковых рантаймов; даты EOL — вход в план миграции. Для CI — `eol-scanner` с endoflife.date embedded data (Stale data detection >30 дней).
6. **Не использовать `:latest` в production** — ловушки мутабельных тегов — в [image_versioning_and_tagging.md](../Docker_registries/image_versioning_and_tagging.md).
7. **Отслеживать не только ОС, но и рантаймы.** EOL Python 3.8 (октябрь 2024), Node 16 (сентябрь 2023) — Trivy помечает как `unfixed`, но образ остаётся risk. Добавьте SCA-скан (Grype, OSV-Scanner) в CI.
8. **Хранить evidence EOL-compliance.** Для регуляторных требований (PCI DSS v4.0.1, EU CRA, SOC 2 2026) — сохранять Trivy SARIF/JSON и eol-scanner отчёты ≥12 месяцев.
9. **Air-gapped среды.** Обновляйте EOL-db endoflife.date вручную (eol-scanner `--force`), синхронизируйте upstream registry через mirror (Harbor, Nexus).
10. **Digest pinning в production требует ротации.** Пресет `docker:pinDigests` генерирует PR при каждом digest-update; отключайте automerge только для major-версий. Для private registry — настройте `registryUrls` и `registryAuth` в Renovate.

### Ограничения и граничные случаи

- **Private registry без upstream доступа.** Renovate/Dependabot не могут проверить актуальность тегов, если registry приватный и не имеет внешнего индекса. Используйте `registryUrls` в packageRules или Renovate Datasource `docker-hub` с mirror.
- **Multi-stage образы с несколькими базовыми образами.** Каждый `FROM` stage требует отдельного контроля. Renovate покрывает multi-stage, но Trivy сканирует только финальный stage по умолчанию; прогоняйте `trivy image --target` для промежуточных.
- **Digest pinning без доступа к registry mirror.** В air-gapped окружениях pinned digest может ссылаться на artifact, который отсутствует в corporate mirror. Включите `--registry-config` в Trivy и `registryUrls` в Renovate.
- **Языковые рантаймы EOL vs ОС EOL.** Образ на поддерживаемом Alpine 3.22 может содержать Python 3.9 (EOL октябрь 2025). Trivy 0.75.x выявляет такие зависимости через `purl`/`cpe`, но `--exit-on-eol` фокусируется на ОС. Добавьте SCA-скан (Grype, OSV-Scanner) для рантаймов.
- **Distroless / Wolfi / Chainguard образы.** Образы без apk/apt менеджеров не имеют встроенного EOL-индикатора в Trivy. Используйте `eol-scanner` с endoflife.date + ручную политику пересборки.
- **Registry retention policies.** Автоматическое удаление ( Harbor `retention.filters`, GCR expiration, ECR lifecycle) может удалить нужный digest до пересборки. Синхронизируйте retention policy с image freshness policy (min 90 дней).
- **Dependabot ограничения.** Dependabot не пинит digest автоматически и не обновляет `apt install` пакеты в Dockerfile; для этих случаев используйте Renovate 44.x.
- **GitLab Container Scanning `CS_REPORT_OS_EOL`.** Доступно только в GitLab Premium/Ultimate с `container_scanning` job; severity по умолчанию Medium — может не блокировать merge request. Используйте `rules` или `only/except` для обязательного EOL-check.

## Дополнительная информация

**Связанные документы:**

- [Версионирование и теги образов](../Docker_registries/image_versioning_and_tagging.md) — immutable tags, ловушки `:latest`.
- [Сканирование уязвимостей](./vulnerability_scanning.md) — Trivy в CI.
- [Метрики безопасности](./security_metrics.md) — EOL-метрика и SLO.
- [Автообновление Podman](../../Podman/podman_auto_update.md) — `podman auto-update`.
- [Python-образы](../Dockerfile/Docker_best_practices/python.md) — обновление базовых образов Python.
- [Безопасность цепочки поставок](../../Security/Supply_Chain_Security/overview.md) — общая методология.

**Инструменты:** `trivy` 0.75.x (`--exit-on-eol`, `--format sarif`), Renovate 44.x (`docker:pinDigests`, `registryUrls`), Dependabot 2.x (`dockerfile`), `eol-scanner` (endoflife.date), `docker image prune`, `jq`, `yq`, `grype` (SCA), `osv-scanner` (SCA).
