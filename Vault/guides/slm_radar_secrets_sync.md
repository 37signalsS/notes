# SLM, Vault Radar и Secrets Sync

**Актуально для:** Vault 2.x (latest 2.1.2; поддержка Secrets Sync — начиная с 1.16 Enterprise); Vault Radar — HCP SaaS (CLI/`vault-radar`, API `2023-05-01`)

> **Статус продуктов:** [Vault Radar](https://developer.hashicorp.com/hcp/docs/vault-radar/) — управляемый сервис HashiCorp Cloud Platform (SaaS); [Secrets Sync](https://developer.hashicorp.com/vault/docs/sync) — функция Vault Enterprise (1.16+ / 2.x), также доступна на HCP Vault Dedicated.

Это руководство охватывает **операторскую поверхность Vault**: активация, конфигурация источников и назначений, ассоциации, мониторинг статуса, аудит, RBAC и защита SSRF. Настройка IAM сторонних облачных провайдеров (AWS/GCP/Azure/GitHub/Vercel) не входит в объём — Vault не управляет правами доступа во внешних системах.

## Определения

- **Secret Lifecycle Management (SLM)** — концепция HashiCorp «Security Lifecycle Management» (категория продуктов), реализуемая комбинацией **Vault** (хранение, ротация, выпуск) + **Vault Radar** (обнаружение) + **Secrets Sync** (распределение). Выходит за рамки пассивного хранилища: охватывает обнаружение утечек, централизованное управление, ротацию и синхронизацию.
- **Vault Radar** — управляемый сервис HCP для обнаружения встроенных секретов (secrets, PII, non-inclusive language, сертификаты) в исходном коде, чат-сообщениях и прочих источниках. Использует собственный CLI `vault-radar` (распространяется через `releases.hashicorp.com/vault-radar/`) и HTTP API (`api.cloud.hashicorp.com`, версия `2023-05-01`). Не входит в self-hosted open-source Vault.
- **Secrets Sync** — функция Vault Enterprise для односторонной репликации секретов из Vault во внешние хранилища (AWS Secrets Manager, Azure Key Vault, GCP Secret Manager, GitHub Repository Actions, Vercel Projects). События синхронизации — асинхронные и на базе событий: изменение секрета в Vault автоматически распространяется на назначение через несколько секунд.
- **Hub-and-spoke** — архитектура Secrets Sync: Vault выступает центральным хабом (system of record), внешние хранилища — спицами.
- **Continuous Discovery** — непрерывный процесс поиска секретов во всех подключённых источниках.
- **Association (ассоциация)** — связь конкретного секрета Vault (KV v2 mount + secret_name) с конкретным назначением; хранит текущий статус синхронизации.
- **Destination (назначение)** — внешнее хранилище, получающее секреты от Vault.

## Основные концепции

### Жизненный цикл секрета в SLM

```
Обнаружение → Классификация → Хранение → Ротация → Синхронизация → Аудит
     ↑                                                                |
     └────────────────────────────────────────────────────────────────┘
```

1. **Обнаружение:** Vault Radar сканирует репозитории, чаты и другие источники, находит активные (валидные) секреты.
2. **Классификация:** находки приоритизируются по тяжести (`critical`, `high`, `medium`, `low`).
3. **Хранение:** найденный секрет сохраняется в Vault (статус события `SECRET_STORED`) для централизованного доступа и ротации.
4. **Ротация:** автоматическая или полуавтоматическая замена секрета (через движки Vault, напр. `database`).
5. **Синхронизация:** обновлённый секрет рассылается во внешние хранилища через Secrets Sync.
6. **Аудит:** все операции фиксируются в audit-устройстве Vault и в событиях Radar.

### Vault Radar

- **Клиенской утилитой** является отдельный бинарник `vault-radar` (скачать с `https://releases.hashicorp.com/vault-radar/<version>/`). Требует переменных окружения `VAULT_ADDR` и `VAULT_TOKEN`.
- **Обнаружение:** сканирование исходного кода, чат-сообщений, локальных каталогов и CI; глубинный скан (в т.ч. git history) определяет, является ли секрет **активным** (валидным).
- **API:** `https://api.cloud.hashicorp.com/2023-05-01/vault-radar/projects/<project_id>/...`. События имеют severity и статус.
- **Статусы события:** `NEW`, `FALSE_POSITIVE`, `NOT_IMPORTANT`, `IGNORE_RULE`, `NOTIFIED`, `TO_REMEDIATE`, `SECRET_STORED`, `SECRET_REPLACED`, `SECRET_REVOKED`, `RESOLVED`, `DELETED`.
- **Детекторы:** secrets, PII, non-inclusive language (NIL); сертификаты (beta) — PEM-блоки с оценкой алгоритма/размера ключа/срока действия.
- **Источники (документированы):** Git-репозитории, Confluence, локальные каталоги и файлы, CI/CD, чаты/сообщения.

### Secrets Sync

Secrets Sync читает секреты из **источников Vault** и выталкивает их во **назначения**. Источник определяется автоматически по mount:

| Источник | Как Vault читает |
| :--- | :--- |
| KV version 2 | `<mount>/data/<secret_name>` |
| Database (static roles) | `<mount>/static-creds/<role_name>` (обязательный префикс `static-roles/`) |

> Dynamic роли Database **не поддерживаются** — только static roles.

Архитектура:

- **Односторонняя**, event-based синхронизация (`Vault → назначение`); изменение и удаление секрета в Vault автоматически отражаются во внешней системе.
- **Last-write-wins:** если секрет с тем же именем уже существует во внешней системе, он перезаписывается.
- **Granularity:** `secret-path` (вся JSON-запись одним значением; по умолчанию для `aws-sm`/`azure-kv`/`gcp-sm`) и `secret-key` (каждое K/V парой — по умолчанию для `gh`/`vercel-project`).
- **Имена секретов:** шаблон `vault/<MountAccessor>/<SecretPath>` по умолчанию; поддерживает go-шаблоны (`MountPath`, `MountAccessor`, `SecretPath`, `SecretKey` и др.).
- **SSRF-защита:** по умолчанию разрешены только порты 80/443 и публичные IP; блокируются special-purpose адреса. Настраивается через `disable_strict_networking`, `allowed_ipv4_addresses`, `allowed_ipv6_addresses`, `allowed_ports`.
- **Реконсиляция:** автоматические retries с экспоненциальным back-off и периодические сканы для самовосстановления; включена по умолчанию.
- **Доступ:** Vault проверяет `read` на источнике перед синхронизацией.
- **Подсчёт клиентов:** каждый синхронизированный секрет считается отдельным клиентом.

**Поддерживаемые назначения (destination type):** `aws-sm` (AWS Secrets Manager), `azure-kv` (Azure Key Vault), `gcp-sm` (GCP Secret Manager), `gh` (GitHub Repository Actions), `vercel-project` (Vercel Projects).

**Статусы синхронизации:** `UNKNOWN`, `PENDING`, `SYNCED`, `UNSYNCED`, `INTERNAL_VAULT_ERROR`, `CLIENT_SIDE_ERROR`, `EXTERNAL_SERVICE_ERROR`.

### Активация

Secrets Sync требует одноразовой активации (иначе вызовы `/sys/sync/*` возвращают ошибку):

```bash
# Через CLI
vault write -f sys/activation-flags/secrets-sync/activate
# или HTTP
curl -s -X PUT -H "X-Vault-Token: $VAULT_TOKEN" \
    http://127.0.0.1:8200/v1/sys/activation-flags/secrets-sync/activate
# → {"data":null,"warnings":null}
```

Глобальная конфигурация (очередь, отключение):

```bash
curl -s -X PATCH -H "X-Vault-Token: $VAULT_TOKEN" -H "Content-Type: application/json" \
    -d '{"disabled":"false","queue_capacity":1000000}' \
    http://127.0.0.1:8200/v1/sys/sync/config
# → {"data":{"disabled":false,"queue_capacity":1000000},...}
```

## Практические сценарии

### Сценарий 1: Создание назначения и ассоциация (GitHub)

```bash
# 1) Создание назначения GitHub
curl -s -X POST -H "X-Vault-Token: $VAULT_TOKEN" -H "Content-Type: application/json" \
    -d '{"access_token":"github_pat_...","secrets_location":"repository","repository_owner":"my-org","repository_name":"my-repo"}' \
    http://127.0.0.1:8200/v1/sys/sync/destinations/gh/my-gh-dest
# → {"data":{"name":"my-gh-dest","type":"gh",...},...}

# 2) Ассоциация секрета KV v2 с назначением (триггерит sync)
curl -s -X POST -H "X-Vault-Token: $VAULT_TOKEN" -H "Content-Type: application/json" \
    -d '{"mount":"kv","secret_name":"myapp/db"}' \
    http://127.0.0.1:8200/v1/sys/sync/destinations/gh/my-gh-dest/associations/set
# → {"data":{"associated_secrets":{"kv_eb4acbae/myapp/db":{"sync_status":"SYNCED",...}}}}

# 3) Просмотр статуса ассоциаций назначения
curl -s -X GET -H "X-Vault-Token: $VAULT_TOKEN" \
    http://127.0.0.1:8200/v1/sys/sync/destinations/gh/my-gh-dest/associations
# → {"data":{"associated_secrets":{...,"sync_status":"SYNCED"},...}}
```

### Сценарий 2: AWS Secrets Manager (с кастомным именем и тегами)

```bash
curl -s -X POST -H "X-Vault-Token: $VAULT_TOKEN" -H "Content-Type: application/json" \
    -d '{"access_key_id":"AKIA...","secret_access_key":"...","region":"us-east-1","kms_key_id":"arn:aws:kms:us-east-1:123456789012:key/uuid","secret_name_template":"vault/{{ .MountAccessor }}/{{ .SecretPath }}","custom_tags":{"team":"platform"},"allowed_ipv4_addresses":["10.0.0.0/8"]}' \
    http://127.0.0.1:8200/v1/sys/sync/destinations/aws-sm/my-aws-dest
```

### Сценарий 3: Управление ассоциациями и удаление

```bash
# Список всех ассоциированных секретов
curl -s -X LIST -H "X-Vault-Token: $VAULT_TOKEN" \
    http://127.0.0.1:8200/v1/sys/sync/associations
# → {"data":{"key_info":<secrets>,"keys":[...],"total_associations":N,"total_secrets":M}}

# Убрать секрет из назначения (unsync — удаляет запись во внешней системе)
curl -s -X POST -H "X-Vault-Token: $VAULT_TOKEN" -H "Content-Type: application/json" \
    -d '{"mount":"kv","secret_name":"myapp/db"}' \
    http://127.0.0.1:8200/v1/sys/sync/destinations/gh/my-gh-dest/associations/remove
# → ... "sync_status":"UNSYNCED"

# Удалить назначение (purge удаляет секреты во внешней системе и ассоциации)
curl -s -X DELETE -H "X-Vault-Token: $VAULT_TOKEN" \
    "http://127.0.0.1:8200/v1/sys/sync/destinations/gh/my-gh-dest?purge=true"
```

### Сценарий 4: Политика доступа

```hcl
# Доступ к управлению синхронизацией
path "sys/sync/*" {
  capabilities = ["read", "list", "create", "update", "delete"]
}
# Чтение секрета-источника обязательно для ассоциации
path "kv/data/myapp/*" {
  capabilities = ["read"]
}
```

### Сценарий 5: Непрерывное обнаружение через Vault Radar

```bash
# Ежедневный скан Git (результат — JSONL на stdout / HCP)
vault-radar scan repo -u https://github.com/org/repo -f json -o repo-scan.jsonl

# CI: скан tip ветки с порогом severity high
./vault-radar scan ci tip -s high -o scan.jsonl -l scan.log --pretty=gha

# Индекс существующих секретов Vault для корреляции (только AppRole + KV v2)
VAULT_ADDR=https://vault.example.com VAULT_TOKEN=$T vault-radar index vault -o vault.idx.jsonl

# Запрос событий через HCP API (поток результатов)
curl -s -X POST -H "Authorization: Bearer $HCP_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"search":{"filters":[{"id":"severity","op":"EQ","value":["critical","high"]},{"id":"status","op":"EQ","value":["NEW","TO_REMEDIATE"]}],"orderBy":"created","orderDirection":"DESC","limit":100,"page":1}}' \
    https://api.cloud.hashicorp.com/2023-05-01/vault-radar/projects/$PROJECT_ID/events/search
# → {"events":[{"event_id":"...","type":"REPO_SCAN_MATCH","severity":"critical","status":"NEW",...}]}
```

### Сценарий 6: Интеграция с CI/CD (чтение секрета в pipeline)

Синхронизированный секрет появляется во внешнем хранилище и доступен runner-у; Vault остаётся system of record. Пример чтения через Vault CLI в pipeline:

```yaml
# .github/workflows/deploy.yml
jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Read secret from Vault
        env:
          VAULT_ADDR: https://vault.example.com:8200
          VAULT_TOKEN: ${{ secrets.VAULT_TOKEN }}
        run: |
          DB_PASSWORD=$(vault kv get -field=password kv/myapp/db)
          echo "DB_PASSWORD=$DB_PASSWORD" >> $GITHUB_ENV
      - run: ./deploy.sh
```

## Операции и команды

### Vault Radar (CLI / HCP API)

| Команда / эндпоинт | Описание |
| :--- | :--- |
| `vault-radar scan repo -u <URL>` | Сканирует Git-репозиторий (в т.ч. историю) |
| `vault-radar scan folder -p <PATH> -o <OUT>` | Сканирует локальный каталог |
| `vault-radar scan ci pr\|tip -s <severity>` | Скан в CI/CD (PR / tip) |
| `vault-radar scan confluence -u <URL> -s <SPACE>` | Сканирует Confluence |
| `vault-radar index vault -o <OUT>` | Индекс секретов Vault (AppRole + KV v2) |
| `POST …/vault-radar/projects/{project_id}/events/search` | Поиск событий (severity, status, pagination) |

### Secrets Sync (API)

| Метод | Путь | Назначение |
| :--- | :--- | :--- |
| `POST` / `PUT` | `/sys/sync/destinations/:type/:name` | Создать/обновить назначение |
| `GET` | `/sys/sync/destinations/:type/:name` | Прочитать назначение (чувствительные значения → `*****`) |
| `DELETE` | `/sys/sync/destinations/:type/:name?purge=&force_delete=` | Удалить назначение |
| `LIST` | `/sys/sync/destinations` | Список всех назначений по типу |
| `LIST` | `/sys/sync/destinations/:type` | Список назначений типа |
| `PATCH` | `/sys/sync/config` | Глобальная конфигурация (disabled, queue_capacity) |
| `GET` | `/sys/sync/destinations/:type/:name/associations` | Статус ассоциаций назначения |
| `POST` | `/sys/sync/destinations/:type/:name/associations/set` | Связать секрет (mount, secret_name) |
| `POST` | `/sys/sync/destinations/:type/:name/associations/remove` | Отвязать секрет (unsync) |
| `LIST` | `/sys/sync/associations` | Все ассоциированные секреты |
| `GET` | `/sys/sync/associations/:mount/:name` | Назначения, связанные с секретом |
| `GET` | `/sys/sync/associations/destinations?mount=&secret_name=` | Назначения для секрета (форм-вариант) |
| `POST` | `/sys/sync/github-apps/:name` | Кастомное GitHub-приложение (app_id, private_key) |
| `PUT` | `/sys/activation-flags/secrets-sync/activate` | Активация Secrets Sync |

## Устранение неполадок

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| `sync_status`: `CLIENT_SIDE_ERROR` | Неверные учётные данные / права во внешней системе, либо токен без `read` на источник | Проверить policy Vault (`path "sys/sync/*"` + `read` на секрет) и cred’ы назначения |
| `sync_status`: `EXTERNAL_SERVICE_ERROR` | Временная недоступность или ошибка во внешней системе | Автоматически ретраится; при постоянной ошибке проверить статус провайдера |
| секрет не появляется во внешней системе | Ассоциация не создана / `disabled=true` в `/sys/sync/config` | Проверить `sys/sync/associations` и `disabled` в конфиге |
| запрос заблокирован в назначение, хотя IP верный | SSRF-защита блокирует порт или special-purpose IP | Добавить `allowed_ipv4_addresses`/`allowed_ports`, либо `disable_strict_networking=true` |
| `DELETE` назначения не удаляет секреты | `purge=false` (по умолчанию) удаляет только конфиг, секреты остаются | Использовать `?purge=true`; при ошибке ассоциаций — `force_delete=true` (только в крайнем случае — создаёт осиротевшие секреты) |
| `scan ci` не сообщает о пороге | флаг `-s` задаёт минимальный severity; ниже порога скан продолжается | Убедиться, что сканерам доступны `VAULT_ADDR`/`VAULT_TOKEN`/`HCP_*` |
| ложноположительные срабатывания Radar | детектор сработал паттерн в тестовом/документальном коде | Пометить `FALSE_POSITIVE`/`IGNORE_RULE` через событие/HCP |

## Лучшие практики

1. **Continuous Discovery:** регулярно (через CI и по schedule) сканировать Git, Confluence и локальные артефакты через Vault Radar.
2. **Приоритизация:** фокус на `critical`/`high` (пароли, API-ключи); быстрая ротация найденных активных секретов.
3. **Хранилище один — Vault:** перемещать обнаруженные секреты в Vault (`SECRET_STORED`) и ротировать вместо hardcoded-значений.
4. **Hub-and-spoke:** Vault — system of record для всех секретов; внешние системы принимают только синхронизированные копии.
5. **Ограничьте назначения allow-list’ами:** используйте `allowed_ipv4_addresses`/`allowed_ports` вместо `disable_strict_networking`.
6. **Имена и теги:** применяйте `secret_name_template` и `custom_tags` для трассируемости и предотвращения коллизий.
7. **Аудит:** включить `audit` device и отслеживать события Radar + статусы `/sys/sync/.../associations`.
8. **Ротация:** регулярно ротировать imported-секреты и credential, используемые sync-назначениями; для Database-источников используйте dynamic роли.
9. **Last-write-wins:** не храните в назначениях данные, которые меняются вручную вне Vault — они будут перезаписаны.

## Ограничения и известные проблемы

- **Тип лицензии:** Secrets Sync — Vault Enterprise (1.16+) / Vault 2.x; Vault Radar — HCP SaaS (отдельная подписка).
- **Источники Sync:** только KV v2 и Database static roles (dynamic роли Database не поддерживаются).
- **Односторонность:** Sync односторонний (Vault → назначение); коллизии разрешаются по стратегии last-write-wins.
- **Назначения:** конечный список — AWS SM, Azure KV, GCP SM, GitHub Actions, Vercel; IAM во внешних системах управляется оператором, Vault не синхронизирует права.
- **Точность Radar:** возможны ложноположительные результаты; требуется ручная проверка/разметка.
- **SSRF-защита:** по умолчанию только порты 80/443 и публичные IP; в private-сетях может потребоваться настройка allow-list.
- **Vault 2.0 (breaking):** Vault теперь требует canonicalized пути — запросы с `/../`, `/./`, `//` отклоняются [§](https://github.com/hashicorp/vault/blob/main/CHANGELOG.md); для `sys/rekey`, `sys/generate-root`, `sys/replication/dr/secondary/generate-operation-token` теперь требуется токен (обратная совместимость через `enable_unauthenticated_access`).

## Дополнительная информация

- **[Обзор HashiCorp Vault](../overview.md)** — архитектура, SLM и ключевые функции.
- **[Антипаттерны управления секретами](../common_antipatterns.md)** — secret sprawl и почему dynamic secrets важны.
- **[Zero Trust](../zero_trust.md)** — роль SLM в нулевой доверенности.
- **[Vault API Reference](./vault_api_reference.md)** — REST API и endpoint-ы.
- **[Ротация секретов](./secret_rotation.md)** — стратегии и graceful rotation.
- [Документация HCP Vault Radar](https://developer.hashicorp.com/hcp/docs/vault-radar/) · [Vault Radar CLI](https://developer.hashicorp.com/hcp/docs/vault-radar/cli) · [События API](https://developer.hashicorp.com/hcp/docs/vault-radar/api/events)
- [Secrets Sync — обзор](https://developer.hashicorp.com/vault/docs/sync) · [Secrets Sync API](https://developer.hashicorp.com/vault/api-docs/system/secrets-sync)
