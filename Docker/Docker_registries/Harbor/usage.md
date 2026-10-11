# Harbor: Работа с реестром

**Актуально для:** Harbor 2.15.x, Cosign v3.x, Helm 3.8+ (OCI), Docker Engine 24+

## Определения

* **OCI-артефакт**: Универсальный формат хранения данных в реестре (образы, Helm-чарты, OPA-политики), соответствующий спецификации Open Container Initiative.
* **Digest**: SHA256-хеш манифеста артефакта (`sha256:...`). Неизменяемый идентификатор содержимого: в отличие от тега, digest всегда указывает на один и тот же набор слоёв.
* **Robot Account (робот-аккаунт)**: Сервисный аккаунт, привязанный к проекту, для автоматизации (CI/CD). Имеет ограниченные права, не привязан к личности сотрудника и не может входить в веб-интерфейс Harbor.
* **CLI Secret**: Специальный токен для аутентификации через CLI, используемый вместо основного пароля (особенно актуально для OIDC/LDAP пользователей).
* **Cosign**: Инструмент для создания и верификации цифровых подписей контейнерных образов, интегрированный с Harbor.
* **Referrers (OCI 1.1)**: Механизм спецификации OCI 1.1 для хранения связанных артефактов (подписи, аттестации) без отдельных тегов. Harbor 2.11+ хранит подписи Cosign и Notation как Referrers.
* **Неизменяемый тег (Immutable Tag)**: Настройка проекта, запрещающая перезапись (overwrite) существующего тега. Гарантирует, что под одним и тем же тегом всегда будет находиться один и тот же артефакт.
* **Proxy Cache**: Режим работы проекта, при котором Harbor кэширует образы из внешних реестров (например, Docker Hub), позволяя обходить лимиты на скачивание (Rate Limits).
* **Webhook**: HTTP-уведомление Harbor о событиях в проекте (push, сканирование, репликация) для внешних систем (Slack, Jenkins, ArgoCD).
* **Retention Policy**: Набор правил удаления артефактов в проекте по количеству тегов, возрасту или другим фильтрам.
* **Garbage Collection (GC)**: Процесс физического удаления неиспользуемых данных (слоёв, манифестов) из хранилища. Необходим, потому что удаление артефактов и Retention Policy только помечают данные как неиспользуемые — место на диске освобождается после GC.
* **Quota**: Лимит на количество артефактов или объём хранилища для проекта.
* **Белый список уязвимостей (Vulnerability Whitelist)**: Список CVE, которые игнорируются при проверке политик безопасности проекта (например, если уязвимость признана некритичной для данного окружения).

## Предварительные требования

* **Docker Engine 24+** — для push/pull образов; более старые версии не поддерживают OCI 1.1 Referrers.
* **Helm 3.8+** — для работы с чартами как OCI-артефактами (`oci://` URL-схема).
* **Cosign v3.x** — для подписи образов (keyless и с ключом).
* **skopeo** — для работы с digest при подписи Notation и миграции образов.
* **Harbor 2.15.x** — текущая версия; Referrers API и OCI 1.1 доступны с 2.11+.
* **Доступ к инстансу**: роль `Guest` (pull), `Developer` (push), `Project Admin` (управление). Робот-аккаунты — для CI/CD.
* **Сеть**: порт 443 (TLS) для публичного доступа; внутренние порты и компоненты — см. [installation.md](./installation.md).
* **Сертификат**: внутренний CA или сертификат от доверенного центра; самоподписанный требует установки Root CA на клиентов (см. [certificates.md](./certificates.md)).
* **Сканер (для проверки подписей и сканирования)**: Trivy должен быть установлен (`--with-trivy` при Docker Compose или `trivy.enabled: true` в Helm), если используются Deployment Security и проверка образов.

## Основные концепции

Работа с Harbor включает операции аутентификации, управления доступом и жизненным циклом артефактов. Все артефакты группируются в **Проекты**.

### Способы аутентификации

| Метод | Назначение | Формат логина |
| :--- | :--- | :--- |
| **Пользователь** | Интерактивный доступ | `username` / `password` (или CLI Secret) |
| **Робот-аккаунт** | Автоматизация в CI/CD | `robot$<project>+<имя>` / `<токен>` |

Формат робот-аккаунта — `<prefix><project>+<account_name>`, где префикс по умолчанию `robot$` (настраивается в `harbor.yml`). Формат `robot$<имя>` без имени проекта — legacy (Harbor < 2.2, JWT), deprecated: для новых аккаунтов не используйте.

### Структура имен артефактов

Имя образа или артефакта в Harbor всегда следует формату:

```bash
<hostname>/<project>/<repository>:<tag>
<hostname>/<project>/<repository>@sha256:<digest>
```

Пример: `harbor.example.com/library/nginx:1.25`

* **hostname**: Доменное имя инстанса Harbor.
* **project**: Имя проекта (логическое пространство имен).
* **repository**: Имя репозитория (обычно название приложения).
* **tag**: Версия или уникальный идентификатор (по умолчанию `latest`). Тег можно перезаписать (если не включён Immutable Tag), поэтому для гарантированной идентификации содержимого используйте **digest**.

### Ролевая модель и доступ

| Тип проекта | Чтение (Pull) | Запись (Push) | Управление |
| :--- | :--- | :--- | :--- |
| **Публичный** | Анонимно | Требуется роль `Developer` | Требуется роль `Project Admin` |
| **Приватный** | Требуется роль `Guest` | Требуется роль `Developer` | Требуется роль `Project Admin` |

## Практические сценарии

### Сценарий 1: Интерактивная аутентификация пользователя

Для работы через Docker CLI необходимо выполнить вход. Если используется внешняя аутентификация (OIDC), используйте **CLI Secret** из профиля пользователя вместо пароля.

```bash
docker login harbor.example.com
# Username: admin
# Password: <YourAdminPassword>

# → Login Succeeded
```

### Сценарий 2: Использование робот-аккаунтов в CI/CD

Робот-аккаунты предпочтительны для автоматизации, так как они имеют ограниченные права и не привязаны к личности сотрудника.

1. В интерфейсе Harbor: **Project → Robot Accounts → New Robot Account**.
2. Укажите имя (в логине оно появится как `robot$<project>+<имя>`) и выберите разрешения (`Pull Artifact`, `Push Artifact`). **Push Artifact требует также включённого Pull Artifact** — без права чтения запись не работает.
3. Задайте срок действия (Expiration) или выберите Never Expired.
4. Скопируйте сгенерированный секрет — **он показывается один раз и не хранится в Harbor**. При утере используйте Refresh Secret: новый секрет немедленно отменяет старый.

```bash
# Логин под робот-аккаунтом
docker login harbor.example.com -u 'robot$production+ci-bot' -p 'SECRET_TOKEN'
# → Login Succeeded
```

Особенности робот-аккаунтов:

* Не могут входить в веб-интерфейс Harbor — только API и CLI.
* Создание через API: `POST /api/v2.0/robots`; получение нового секрета: `GET /api/v2.0/robots/<project>%2F<name>/secret`. Подробная ротация — в [интеграции с GitLab](../../../Kubernetes/Installation/k3s_dev_environment/gitlab_harbor_integration.md) и [Supply Chain Security](../../../Security/Supply_Chain_Security/overview.md).

### Сценарий 3: Публикация и загрузка образа

Подготовка локального образа и его отправка в Harbor:

```bash
# 1. Присвоение тега в соответствии со структурой Harbor
docker tag my-app:latest harbor.example.com/production/my-app:v1.2.0

# 2. Отправка (Push)
docker push harbor.example.com/production/my-app:v1.2.0
# → v1.2.0: digest: sha256:abcd... size: 1024

# 3. Загрузка (Pull) по тегу
docker pull harbor.example.com/production/my-app:v1.2.0

# 4. Загрузка по digest — гарантирует неизменность содержимого
docker pull harbor.example.com/production/my-app@sha256:abcd...
```

### Сценарий 4: Работа через Harbor CLI

Официальный CLI (`goharbor/harbor-cli`) — альтернатива curl и Docker CLI для автоматизации и скриптинга. Хранит конфиг в `$HOME/.config/harbor-cli/config.yaml`; пароль шифруется AES-256 (ключ — `HARBOR_ENCRYPTION_KEY`, base64 от 32-байт строки). Полный список команд — в [Harbor CLI Docs](https://goharbor.io/cli-docs/cli-docs).

```bash
# Установка
curl -sL https://github.com/goharbor/harbor-cli/releases/latest/download/harbor-cli-linux-amd64 -o harbor && chmod +x harbor

# Логин (требует пароля или CLI Secret; для безопасности используйте --password-stdin)
harbor login harbor.corp.local -u "robot$production+ci-bot" --password-stdin <<< "$ROBOT_SECRET"

# Список артефактов репозитория (аргумент в формате <project>/<repository>)
harbor artifact list myproject/my-app

# Информация по артефакту (digest, теги, vuln-счёт)
harbor artifact view myproject/my-app@sha256:abcd...

# Запуск сканирования (scan start не различает тип: vuln или SBOM — тип задаётся в настройках сканера)
harbor artifact scan start myproject/my-app:latest

# Управление квотой проекта
harbor quota view myproject
harbor quota update --project-name myproject --storage 100GiB

# Робот-аккаунты (project robot — создание без интерактивного режима)
harbor project robot list myproject
harbor project robot create --project myproject --name ci-bot --duration 30d --all-permission
```

CLI-команды, которые особенно полезны в SRE/runbook-сценариях:
- `harbor jobservice queues list` / `pause` / `resume` — диагностика загрузки Job Service (важно при «зависании» сканирования и генерации SBOM).
- `harbor scan all run` / `scan all stop` / `scan all view schedule` — массовое сканирование всего реестра по расписанию.
- `harbor schedule list` — все запланированные задания (GC, retention, scan all, preheat).
- `harbor health` — статус компонентов без аутентификации.
- `harbor replication policies list` / `replication start` — управление репликацией из скрипта.

> CLI не поддерживает `--scan-type` для `scan start` — тип сканирования определяется настройками сканера проекта/инстанса. Для запуска именно SBOM-генерации используйте API (`POST .../scan` с `{"scan_type":"sbom"}`), как описано в [sbom.md](./sbom.md#сценарий-5-запуск-генерации-sbom-через-apicli).

### Сценарий 5: Подпись образа с помощью Cosign

Harbor отображает статус подписи в интерфейсе, что позволяет визуально контролировать доверенные образы. Harbor 2.11+ хранит подписи Cosign как OCI 1.1 Referrers — без дополнительных тегов в проекте.

```bash
# 1. Генерация ключей (если нет)
cosign generate-key-pair
# → cosign.key (приватный, защищён паролем) и cosign.pub (публичный)

# 2. Подпись образа в Harbor — по digest, а не по тегу:
#    тег может быть перезаписан, digest всегда указывает на тот же контент
DIGEST=$(docker inspect --format='{{index .RepoDigests 0}}' harbor.example.com/production/my-app:v1.2.0 | cut -d'@' -f2)
cosign sign --key cosign.key harbor.example.com/production/my-app@${DIGEST}
# → запросит пароль ключа; в CI задайте его через COSIGN_PASSWORD

# 3. Проверка подписи
cosign verify --key cosign.pub harbor.example.com/production/my-app:v1.2.0
```

Принудительная проверка подписи: **Project → Configuration → Cosign** (или Notation) — при включении только верифицированные образы можно загружать из проекта. Keyless-подпись (Fulcio/OIDC), аттестации и типичные ошибки `cosign` — в [проверке подписей образов](../../Docker_security/image_signature_and_verification.md).

**Notation** — альтернатива Cosign (стандарт OCI artifact signatures, корпоративный профиль с Trust Stores, интеграция с HSM/Vault):

```bash
# Подпись по digest (аналогично Cosign — подписывать нужно digest, не тег)
DIGEST=$(skopeo inspect --format '{{.Digest}}' docker://harbor.example.com/production/my-app:v1.2.0)
notation sign --key "internal-ca/signing-key" harbor.example.com/production/my-app@${DIGEST}

# Проверка
notation verify harbor.example.com/production/my-app:v1.2.0
```

Полная практика Notation (Trust Stores, HSM, VSA) — в [подписи артефактов](../../../Security/Supply_Chain_Security/artifact_signing.md).

### Сценарий 6: Работа с Helm-чартами как OCI-артефактами

Harbor позволяет использовать единый реестр для образов и чартов.

```bash
# 1. Аутентификация Helm в реестре (-p обязателен: пароль или CLI Secret)
helm registry login harbor.example.com -u admin -p '<password>'

# 2. Публикация чарта
helm push my-chart-1.0.0.tgz oci://harbor.example.com/charts

# 3. Установка из Harbor
helm install my-app oci://harbor.example.com/charts/my-chart --version 1.0.0
```

### Сценарий 7: Настройка Proxy Cache (Pull-through Cache)

Используется для кэширования образов с Docker Hub и обхода лимитов.

1. Создайте **Registries Endpoint** для upstream-реестра (для Docker Hub — `https://registry-1.docker.io`; учётные данные Docker Hub повышают лимиты).
2. Создайте новый проект (например, `docker-hub-proxy`), включите опцию **Proxy Cache** и выберите созданный Endpoint.
3. Загружайте образы через префикс проекта-кэша:

```bash
# Official-образы Docker Hub (namespace library)
docker pull harbor.example.com/docker-hub-proxy/library/nginx:1.25

# Пользовательские образы
docker pull harbor.example.com/docker-hub-proxy/myuser/my-app:v1.0.0
```

Как это работает:

* Проект-кэш — **pull-only**: push в него отклоняется.
* При первом pull Harbor скачивает образ из upstream и хранит локально; при повторных — отдаёт из кэша.
* Перед отдачей из кэша Harbor проверяет upstream **HEAD-запросом** — это не расходует квоту rate limiter Docker Hub.
* Кэшированные артефакты хранятся по retention-политике проекта (по умолчанию 7 дней); настраивается лимит bandwidth (`-1` — без лимита).
* Поддерживаемые upstream: Harbor, Docker Hub, Docker registry, AWS ECR, Azure ACR, GCR, Quay, GitHub Container Registry, JFrog Artifactory.

> **Примечание:** Harbor не документирует использование `registry-mirrors` в Docker Daemon для proxy cache — используйте префиксный метод выше. Конфигурация зеркал на уровне Docker Engine описана в [конфигурации Docker Daemon](../../docker_daemon_config.md).
>
> Альтернатива proxy cache при полном переносе с Docker Hub (а не только кэшировании) — миграция образов в Harbor: runbook в [migration.md](./migration.md).

### Сценарий 7: Webhook-уведомления

Webhook позволяет уведомлять внешние системы о событиях в проекте.

1. **Project → Webhooks → New Webhook**.
2. Укажите endpoint: **HTTP** (URL) или **Slack** (webhook URL).
3. Выберите события: `PUSH_ARTIFACT`, `PULL_ARTIFACT`, `DELETE_ARTIFACT`, `SCANNING_COMPLETED`, `SCANNING_STOPPED`, `SCANNING_FAILED`, `QUOTA_EXCEED`, `QUOTA_WARNING`, `REPLICATION`, `TAG_RETENTION`.
4. Выберите формат payload: **Default** (формат Harbor) или **CloudEvents**.

Количество повторов и таймаут HTTP-клиента настраиваются в `harbor.yml` (параметры `webhook_job_max_retry` — дефолт 10, `webhook_job_http_client_timeout`).

**События и содержимое уведомлений:**

| Событие | Тип | Содержимое |
| :--- | :--- | :--- |
| Push артефакта | `PUSH_ARTIFACT` | namespace, имя репозитория, resource URL, теги, digest, время push, пользователь |
| Pull артефакта | `PULL_ARTIFACT` | namespace, репозиторий, digest, время pull, пользователь |
| Удаление артефакта | `DELETE_ARTIFACT` | namespace, репозиторий, digest, время удаления, пользователь |
| Сканирование завершено | `SCANNING_COMPLETED` | репозиторий, тег, число Critical/Major/Minor, статус, CVE (ID, описание, ссылка, severity, исправление) |
| Сканирование остановлено / не удалось | `SCANNING_STOPPED` / `SCANNING_FAILED` | репозиторий, тег, ошибка, пользователь |
| Квота превышена / near threshold | `QUOTA_EXCEED` / `QUOTA_WARNING` | репозиторий, теги, digest, время push, пользователь |
| Репликация завершена | `REPLICATION` | репозиторий, теги, digest, время, инициатор |
| Retention завершён | `TAG_RETENTION` | репозиторий, теги, digest |

**Пример payload (формат Default, событие PUSH_ARTIFACT):**

```json
{
  "type": "PUSH_ARTIFACT",
  "occur_at": 1586922308,
  "operator": "admin",
  "event_data": {
    "resources": [
      {
        "digest": "sha256:8a9e9863dbb6e10edb5adfe917c00da84e1700fa76e7ed02476aa6e6fb8ee0d8",
        "tag": "latest",
        "resource_url": "harbor.example.com/test-webhook/debian:latest"
      }
    ],
    "repository": {
      "date_created": 1586922308,
      "name": "debian",
      "namespace": "test-webhook",
      "repo_full_name": "test-webhook/debian",
      "repo_type": "private"
    }
  }
}
```

Второй формат — **CloudEvents** (спецификация CloudEvents): выбирается при создании webhook и совместим с современными event-driven инструментами. Endpoint может быть HTTP(S) или Slack (входящий webhook URL); webhook-ов на проект может быть несколько.

**Типичное применение:** webhook `PUSH_ARTIFACT` → CI-система (Jenkins, GitLab CI) запускает тесты; webhook → webhook-receiver ArgoCD Image Updater для немедленной реакции на новый тег (см. [репликацию и автоматизацию обновлений](./replication.md#harbor-и-автоматизация-обновления-образов-argocd-image-updater--flux)).

### Сценарий 8: Управление жизненным циклом (Retention & Immutable)

Для предотвращения переполнения диска и обеспечения стабильности:

* **Retention Policy**: Настройте правила в **Project → Tag Retention**. Например: "Хранить последние 10 тегов для каждого репозитория" или "Удалять артефакты старше 90 дней". Правила помечают артефакты как неиспользуемые — физическое удаление выполняет Garbage Collection (сценарий 10).
* **Immutable Tags**: В **Project → Configuration** добавьте паттерны (например, `v*`, `release-*`), которые будет запрещено перезаписывать.

**Структура правил retention:** фильтры (репозитории, теги, лейблы, подписи) + действие (keep most recently pulled N, keep most recently pushed N, keep days since last pull/push, always retain) + расписание (cron). Выполнение можно запустить вручную (DRY RUN — сначала без удаления) или по расписанию; история выполнений видна в проекте.

**Retention через API** (полный список эндпоинтов — в [API](api.md)):

```bash
# Метаданные (доступные фильтры и действия)
curl -sk -u "admin:$PASS" "https://harbor.corp.local/api/v2.0/retentions/metadatas"

# Создание политики: последние 10 тегов по push в репозитории my-app
curl -sk -u "admin:$PASS" -X POST -H "Content-Type: application/json" \
  -d '{
    "scope": {"project_id": 3},
    "rules": [{
      "disabled": false,
      "template": "latestPushedK",
      "params": {"k": 10},
      "filters": [{"type": "repository", "decoration": "repoMatches", "pattern": "my-app"}]
    }],
    "trigger": {"kind": "Schedule", "settings": {"cron": "0 2 * * *"}}
  }' "https://harbor.corp.local/api/v2.0/retentions"

# Ручной запуск выполнения (dry_run: true — без удаления)
curl -sk -u "admin:$PASS" -X POST -H "Content-Type: application/json" \
  -d '{"dry_run": true}' "https://harbor.corp.local/api/v2.0/retentions/1/executions"
```

Шаблоны: `latestPushedK`, `latestPulledK`, `pushDaysAgo`, `pullDaysAgo`, `alwaysRetain`. Retention не удаляет артефакт физически — помечает неиспользуемым; физическое удаление — Garbage Collection (сценарий 10).

### Сценарий 9: Настройка репликации

Синхронизация образов между разными инстансами Harbor (например, из Dev в Prod контур).

1. Создайте **Registries Endpoint** для удаленного Harbor.
2. В разделе **Replication** создайте правило.
3. Выберите **Push-based** (отправка при появлении нового образа) или **Pull-based** (затягивание по расписанию).
4. Укажите фильтры (по имени проекта или тегам).

Продакшен-конфигурация репликации — поддерживаемые адаптеры, фильтры по лейблам, мониторинг задач и troubleshooting — в [репликации артефактов](./replication.md).

### Сценарий 10: Garbage Collection

GC физически удаляет из хранилища данные, помеченные Retention Policy или удалением артефактов.

1. **Administration → Clean Up → Garbage Collection**.
2. Сначала запустите **DRY RUN** — Harbor покажет, что будет удалено, без фактического удаления.
3. **GC Now** — запуск вручную (не чаще одного раза в минуту).

Особенности:

* GC работает без остановки Harbor.
* Артефакты, загруженные за последние **2 часа**, не удаляются — защита от удаления образов, которые ещё скачиваются.
* Расписание: None / Hourly / Daily / Weekly / Custom (cron).
* Параметр **Workers** задаёт параллелизм; опция **untagged artifacts** разрешает удаление артефактов без тегов.
* Остановка GC **не восстанавливает** уже удалённые артефакты.
* Альтернатива — низкоуровневый CLI `registry garbage-collect` (встроенный в distribution): требует `readonly`-режима registry и ручного переключения. Детали и последовательность — [storage.md, сценарий 8](./storage.md#сценарий-8-управление-слоями-gc-удаление-health-check).

### Сценарий 11: Управление квотами проекта

Квоты ограничивают потребление ресурсов проектом (объём хранилища и/или количество артефактов) — защита от переполнения хранилища одним проектом.

```bash
# Текущие квоты всех проектов
curl -sk -u "admin:$PASS" "https://harbor.corp.local/api/v2.0/quotas" | \
  jq '.[] | {project: .project.project_id, hard: .hard, usage: .usage}'

# Установить лимит хранилища 100 ГБ для проекта (id=3)
curl -sk -u "admin:$PASS" -X PUT -H "Content-Type: application/json" \
  -d '{"hard": {"storage": 107374182400}}' "https://harbor.corp.local/api/v2.0/quotas/3"
```

* Квота настраивается в **Projects → myproject → Configuration → Quota** (UI) или через API (`PUT /api/v2.0/quotas/{id}`, тело `{"hard": {...}}`).
* При превышении: push отклоняется, генерируются события webhook `QUOTA_WARNING` (приближение к порогу) и `QUOTA_EXCEED` (превышение).
* Метрики Prometheus: `harbor_project_quota_usage_byte` (потребление) и `harbor_project_quota_byte` (лимит) — алерты на соотношение usage/hard.
* При массовых push в проекте с квотами — см. рекомендацию `core.quota_update_provider: redis` в [SBOM](./sbom.md#граничные-случаи).

## Валидация

```bash
# Сводный статус сервисов Harbor
curl -sk https://harbor.example.com/api/v2.0/health
# → {"status":"healthy"}

# Версия Harbor (аутентификация не требуется)
curl -sk https://harbor.example.com/api/v2.0/systeminfo | jq .harbor_version
# → "2.15.0"

# Доступ к проекту под робот-аккаунтом
docker pull harbor.example.com/production/my-app:v1.2.0
# → Status: Downloaded newer image for harbor.example.com/production/my-app:v1.2.0

# Проверка подписи Cosign
cosign verify --key cosign.pub harbor.example.com/production/my-app:v1.2.0

# Проверка Referrers API (Harbor 2.11+)
curl -u "robot$production+ci-bot:$ROBOT_SECRET" \
  "https://harbor.example.com/v2/production/manifests/sha256:abcd.../referrers"
# → 200 OK со списком связанных артефактов

# Helm-чарт из Harbor
helm pull oci://harbor.example.com/charts/my-chart --version 1.0.0
```

## Дополнительная информация

### Устранение неполадок

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `unauthorized` | Отсутствует или просрочена сессия | Выполните `docker login` заново |
| `no basic auth credentials` | Не выполнен `docker login` или истёк токен | `docker login`; для робот-аккаунта проверьте формат `robot$<project>+<имя>` |
| `denied` / `requested access to the resource is denied` | Недостаточно прав в проекте | Проверьте роль пользователя или права Robot Account (Push требует Pull) |
| `manifest unknown` | Образ или тег не найден | Проверьте имя проекта и тег; для proxy cache — префикс проекта-кэша и namespace `library` |
| `tls: failed to verify` | Самоподписанный сертификат | Установите Root CA (см. [сертификаты](./certificates.md)) |
| `vulnerability policy` | Образ заблокирован сканером | Проверьте отчет об уязвимостях. Добавьте CVE в белый список, если это безопасно |
| `TOOMANYREQUESTS` (rate limit) | Лимиты upstream-реестра (Docker Hub) | Используйте Proxy Cache (сценарий 6) и учётные данные upstream |
| Секрет robot-аккаунта утерян | Секрет не хранится в Harbor | Сгенерируйте новый через Refresh Secret |
| GC не освобождает место | Retention только помечает артефакты | Запустите Garbage Collection (сценарий 10); проверьте опцию удаления untagged |

### Лучшие практики

* **Изоляция**: Всегда используйте отдельные проекты для разных команд и сред (dev, stage, prod).
* **Структура проектов в enterprise**: именование `<team>-<env>` или `<app>-<env>` (например, `platform-prod`, `payments-stage`) — предсказуемая схема для RBAC, квот и репликации; отдельные проекты для библиотек/base-образов (`base-images`) и артефактов CI (`ci-tools`); репликация Dev→Prod вместо общего проекта; приватные проекты для production (анонимный доступ — read-only к публичным, см. [hardening](./hardening.md#сценарий-3-безопасная-структура-проектов)).
* **Безопасность**: Включите **Automatically scan images on push** и настройте блокировку `pull` для образов с критическими уязвимостями.
* **Автоматизация**: Используйте **Webhook** в Harbor для уведомления внешних систем (Slack, Jenkins, ArgoCD) о загрузке новых образов.
* **Идентификация**: Ссылайтесь на образы по digest в манифестах деплоя — теги изменяемы.
* **Очистка**: Регулярно запускайте **Garbage Collection** (рекомендуется в часы минимальной нагрузки), чтобы физически удалить данные с диска после срабатывания Retention политик.
* **Ротация**: Ротируйте робот-аккаунты по расписанию (см. [интеграцию с GitLab](../../../Kubernetes/Installation/k3s_dev_environment/gitlab_harbor_integration.md)).

### Граничные случаи

* Робот-аккаунт не может войти в веб-интерфейс — только API и CLI.
* Push в проект с Proxy Cache отклоняется: проект работает только на чтение.
* GC не удаляет артефакты, загруженные за последние 2 часа, и не восстанавливает уже удалённые при остановке.
* Подпись по тегу ненадёжна без Immutable Tag: тег можно перезаписать, а подпись останется на старом манифесте. Подписывайте по digest.
* Legacy-формат `robot$<имя>` (Harbor < 2.2) использует JWT и deprecated — существующие аккаунты продолжат работать, но новые создавайте в текущем формате.

### Откат изменений и очистка

```bash
# Разлогиниться из реестра
docker logout harbor.example.com
```

* Удаление робот-аккаунта: **Project → Robot Accounts → Delete** — токен немедленно перестаёт работать.
* Отключение Proxy Cache: **Project → Configuration** — снятие флага; кэшированные артефакты остаются до срабатывания Retention/GC.
* Удаление webhook: **Project → Webhooks → Delete**.

### Связанные документы

* **[Обзор Harbor](./overview.md)** — архитектура и ключевые возможности.
* **[Установка Harbor](./installation.md)** — развертывание через Docker Compose и Helm.
* **[Создание сертификатов](./certificates.md)** — настройка TLS.
* **[Лейблы](./labels.md)** — организация артефактов и фильтры (дополняет сценарии 8–9).
* **[SBOM](./sbom.md)** — генерация и экспорт SBOM (дополняет сценарий 4).
* **[Multi-arch артефакты](./multi_arch.md)** — OCI image index, per-platform сканирование (дополняет сценарий 1).
* **[P2P Preheat](./p2p_preheat.md)** — прогрев образов в Dragonfly/Kraken (дополняет сценарий 9).
* **[Распределённая трассировка](./tracing.md)** — Jaeger/OTel-экспорт трейсов.
* **[Hardening](./hardening.md)** — защита инстанса, структура проектов (дополняет лучшие практики).
* **[Проверка подписей образов](../../Docker_security/image_signature_and_verification.md)** — keyless-подпись, аттестации, Kyverno, troubleshooting Cosign (дополняет сценарий 4).
* **[Конфигурация Docker Daemon](../../docker_daemon_config.md)** — настройка зеркал на уровне Docker Engine (дополняет сценарий 6).
* **[Интеграция GitLab и Harbor](../../../Kubernetes/Installation/k3s_dev_environment/gitlab_harbor_integration.md)** — ротация робот-аккаунтов, квоты и GC через API (дополняет сценарии 2 и 10).
* **[Air-gapped установка](../../../Kubernetes/Troubleshooting/Common_Errors/PodImagePullErrors/airgapped.md)** — мониторинг Harbor API в изолированных средах (дополняет секцию валидации).
