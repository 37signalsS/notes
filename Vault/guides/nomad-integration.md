# Интеграция Vault с Nomad

> **Актуально для:** Vault 2.x + Nomad 1.10+ / 2.0.x (workload identity)

## Определения

**Workload identity** — уникальный JWT, который Nomad (начиная с 1.10) генерирует на каждую задачу и подписывает собственным ключом; Vault принимает его через JWT auth-метод и выдаёт токен с ACL-политиками задачи.

**JWKS (JSON Web Key Set)** — набор публичных ключей подписчика; Vault забирает его по URL, чтобы проверять подпись workload identity. Nomad публикует JWKS на `/.well-known/jwks.json`.

**`bound_audiences` / `bound_claims`** — фильтры роли JWT auth: аудитория (`aud`) и claims (`nomad_namespace`, `nomad_job_id`, `nomad_task`), которым разрешён вход. Необходимое условие: `bound_audiences` должен пересекаться с `aud` workload identity (рекомендуется ровно одно значение).

**`default_identity`** — блок конфигурации сервера Nomad: identity, который Nomad автоматически добавляет во все задачи с `vault`-блоком, чтобы не объявлять identity в каждом джобе.

**Nomad secrets engine** — секретный движок Vault, порождающий **токены Nomad** (обратное направление): Vault хранит management-токен Nomad и выдаёт короткоживущие Nomad-токены по роли.

**`create_from_role`** (устаревший контур) — параметр клиента Nomad старого workflow: сервер/клиент Nomad сам ходит в Vault с общим токеном и запрашивает токен задачи; после перехода на workload identity этот контур заменяется JWT-обменом.

## Основные концепции

### Два направления интеграции

| Направление | Механизм | Зачем |
| :--- | :--- | :--- |
| **Nomad → Vault** (задачи получают секреты) | Workload identity (Nomad 1.10+): JWT задачи → JWT auth в Vault → токен Vault | Основной современный контур: шаблоны задач читают KV/PKI/БД-секреты |
| **Vault → Nomad** (Vault выдаёт токены Nomad) | Secrets engine `nomad`: management-токен → `nomad/creds/<role>` | Автоматизация, управляющие скрипты, CI, которым нужны токены Nomad |

До Nomad 1.10 первое направление реализовывалось «legacy»-workflow: Nomad-сервер хранил Vault-токен и выпускал токены задач сам. Этот способ не различает batch-токены (см. ниже) и считается устаревшим — при переходе его следует отключить.

### Путь workload identity

1. На Nomad-сервере задан `vault.default_identity` (`aud = ["vault.io"]`, `ttl = "1h"`) либо джоб объявляет identity сам (объявление в джобе перекрывает серверное).
2. При старте аллокации клиент Nomad меняет workload identity задачи на токен Vault через JWT auth-метод, указанный в `jwks_url`.
3. Роль auth-метода (`default_role` в конфиге, либо `vault.role` в джобе, либо `create_from_role` у клиента) определяет политики и тип токена.
4. Токен достаётся задаче через переменную окружения `VAULT_TOKEN` (по умолчанию `env = true`) и/или файл `secrets/vault_token` (`disable_file = false`).
5. Nomad **сам продлевает** service-токен задачи, пока та живёт; шаблоны (`template`) перерисовываются при обновлении.

Чтобы у Vault была причина доверять claims, роль должна ограничивать их `bound_claims`; `claim_mappings` делает выбранные claims доступными остальной конфигурации Vault (политики, audit).

### Тип токена и срок жизни — где ловятся ошибки

* `token_type = "service"` + `token_period` (в примере документации `30m`) — периодическое продление.
* **`token_explicit_max_ttl` должен быть `0`** — иначе токен перестанет продлеваться до конца жизни задачи.
* Batch-токены не продлеваются вообще: допустимы только для одноразового чтения секрета на старте (prestart); для долгих задач с `template` — нет.
* При workload identity Nomad сам определяет «непродлеваемый» токен и неявно ставит `allow_token_expiration = true`; legacy-контур такое определить не может.
* `allow_token_expiration = true` + долгоживущая задача с `template` = токен истекает, template-раннер бессмысленно бьётся в Vault до исчерпания `vault_retry`, задача падает.

### Настройка Vault-стороны (workload identity)

Конфиг auth-метода (`POST /auth/jwt/config`):

```json
{
  "jwks_url": "https://nomad.example.com:4646/.well-known/jwks.json",
  "jwt_supported_algs": ["RS256", "EdDSA"],
  "default_role": "nomad-workloads"
}
```

`jwks_url` должен быть достижим со **всех** Vault-серверов и желательно разрешаться в несколько агентов Nomad (и серверы, и клиенты отвечают на этот запрос) — чтобы не выстраивать единую точку отказа.

Роль (`POST /auth/jwt/role/:name`):

```json
{
  "role_type": "jwt",
  "bound_audiences": ["vault.io"],
  "bound_claims": {
    "nomad_namespace": "default",
    "nomad_job_id": "mongo"
  },
  "user_claim": "/nomad_job_id",
  "user_claim_json_pointer": true,
  "claim_mappings": {
    "nomad_namespace": "nomad_namespace",
    "nomad_job_id": "nomad_job_id",
    "nomad_task": "nomad_task"
  },
  "token_type": "service",
  "token_policies": ["nomad-workloads"],
  "token_period": "30m",
  "token_explicit_max_ttl": 0
}
```

### Настройка Nomad-стороны

Агент-сервер:

```hcl
vault {
  enabled = true
  default_identity {
    aud  = ["vault.io"]
    ttl  = "1h"
    extra_claims {
      unique_id = "${job.region}:${job.namespace}:${job.id}"
    }
  }
}
```

Джоб (минимум под Vault):

```hcl
job "mongo" {
  group "db" {
    task "mongo" {
      vault {}

      identity {
        name = "vault_default"
        aud  = ["vault.io"]
        ttl  = "1h"
      }

      template {
        data = <<EOF
{{with secret "kv/data/default/mongo/config"}}
MONGO_INITDB_ROOT_USERNAME=root
MONGO_INITDB_ROOT_PASSWORD={{.Data.data.root_password}}
{{end}}
EOF
        destination = "secrets/env"
        env         = true
      }
    }
  }
}
```

Параметры `vault`-блока джоба: `change_mode` (`restart` по умолчанию; `noop` | `restart` | `signal`), `change_signal` (обязателен при `signal`), `env = true` (экспорт `VAULT_TOKEN`/`VAULT_NAMESPACE`), `disable_file = false` (запись в `secrets/vault_token`; при изоляции chroot/none файл доступен задаче), `allow_token_expiration = false`, `role` (имя роли, иначе клиентский `create_from_role`), `cluster`/`namespace` (Enterprise).

Для нескольких кластеров Vault в Nomad Enterprise объявляется несколько `vault`-блоков с разными именами.

## Практические сценарии

### Сценарий 1 — задачи Nomad читают секреты Vault (workload identity)

1. Включить и настроить JWT auth (команды ниже выполняются с токеном, имеющим права на `auth/`):

```bash
vault auth enable jwt
# → Success! Enabled the jwt auth method at: auth/jwt/

vault write auth/jwt/config - <<'EOF'
{
  "jwks_url": "https://nomad.example.com:4646/.well-known/jwks.json",
  "jwt_supported_algs": ["RS256", "EdDSA"],
  "default_role": "nomad-workloads"
}
EOF
# → Success! Data written to: auth/jwt/config
```

2. Создать политику для задач и роль (payload ролей — см. раздел «Настройка Vault-стороны»):

```hcl
# policy: nomad-workloads.hcl
path "kv/data/default/mongo/*" {
  capabilities = ["read"]
}
path "kv/metadata/default/mongo/*" {
  capabilities = ["read", "list"]
}
```

```bash
vault policy write nomad-workloads nomad-workloads.hcl
vault write auth/jwt/role/nomad-workloads - < role.json
```

3. На Nomad-сервере — `vault.default_identity` (или `identity` в джобе), в джобе — `vault {}` и `template`.
4. Проверка: запустить джоб, убедиться, что в аллокации появился `VAULT_TOKEN`, а в audit-логе Vault — запись `auth/jwt/login` с claims задачи; `vault token lookup` по этому токену покажет привязанные политики `nomad-workloads`.

### Сценарий 2 — Vault выдаёт токены Nomad (secrets engine)

```bash
vault secrets enable nomad
# → Success! Enabled the nomad secrets engine at: nomad/

vault write nomad/config/access \
  address="http://nomad.example.com:4646" \
  token="< Nomad management token >"
# → Success! Data written to: nomad/config/access

vault write nomad/config/lease ttl=1h max_ttl=24h
# → Success! Data written to: nomad/config/lease
```

Роль описывает **Nomad ACL-политики** (они создаются заранее в Nomad, это не Vault-политики):

```bash
# Клиентский токен с Nomad-политикой readonly
vault write nomad/role/monitoring policies=readonly type=client
# → Success! Data written to: nomad/role/monitoring

# Management-роль — только по явной необходимости
vault write nomad/role/emergency type=management global=true

vault read nomad/creds/monitoring
# → Key                Value
#   ---                -----
#   accessor_id        c834ba40-8d84-b0c1-c084-3a31d3383c03
#   secret_id          65af6f07-7f57-bb24-cdae-a27f86a894ce
#   lease_id           nomad/creds/monitoring/...
#   lease_duration     1h
```

Потребителям достаточно `read` на `nomad/creds/<role>`. Утилиты списка/удаления: `vault list nomad/role`, `vault delete nomad/role/<name>`, `vault delete nomad/config/lease` (сброс настроек lease), API — `LIST/POST/GET/DELETE /nomad/role/:name`, `GET /nomad/creds/:name`.

`max_token_name_length` в `config/access` ограничивает имя генерируемого токена (по умолчанию `0` — берётся максимум Nomad; для Nomad ≥ 0.8.4 это 256).

### Сценарий 3 — «приватный» токен: задача не получает власть Vault

Если задаче нужен только рендеренный файл, а токен, выпускающий **другие** токены/секреты, не должен ей достаться:

```hcl
vault {
  role             = "prod"
  change_mode      = "noop"
  env              = false      # не экспортировать VAULT_TOKEN
  disable_file     = true       # не писать secrets/vault_token
}

template {
  data = <<-EOH
  {{with secret "auth/token/create/nomad-job" "policies=examplepolicy"}}{{.Auth.ClientToken}}{{end}}
  EOH
  destination = "${NOMAD_SECRETS_DIR}/examplepolicy.token"
  change_mode = "noop"
  perms       = "600"
}
```

Такой шаблон создаёт токен задаче, а исходная «сила» (токен, выпустивший другие токены/секреты) остаётся внутри изолированного окружения — для драйверов с image-изоляцией, например Docker.

### Terraform

Nomad-бэкенд и роли кодируются ресурсами `vault_nomad_secret_backend` (в `address`/`token` попадает management-токен Nomad — в открытом виде в state) и `vault_nomad_secret_role`; data source `vault_nomad_access_token` читает готовый токен (`accessor_id`, `secret_id`) с тем же предупреждением про state.

## Устранение неполадок

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `login failed` / 403 при `auth/jwt/login` | Vault не может получить JWKS (`jwks_url` недоступен с сервера Vault), несовпадение `jwt_supported_algs`, истёкший/неподписанный JWT | Проверить доступность `https://<nomad>:4646/.well-known/jwks.json` **с каждого** Vault-узла; сверить алгоритмы подписи |
| Отказ роли: audience mismatch | `bound_audiences` не пересекается с `aud` identity (чаще: в джобе/дефолте `aud=["vault.io"]`, в роли другое) | Привести оба значения к одному; рекомендуется единственная аудитория |
| Отказ роли: не проходят `bound_claims` | Записаны не те claims или не тот namespace/джоб | Сверить `nomad_namespace`/`nomad_job_id` из токена (`vault token lookup`) с `bound_claims` |
| Задача не видит Vault-секреты, но `vault {}` объявлен | Не объявлена identity для Vault: по умолчанию Nomad генерирует identity только для доступа к Nomad | Добавить `identity { aud = ["vault.io"] }` в джоб либо задать `vault.default_identity` на сервере |
| Токен задачи протухает, шаблоны падают с `permission denied` | `token_explicit_max_ttl > 0` либо batch-токен в долгоживущей задаче, либо `allow_token_expiration = true` | Роль: `token_type=service`, `token_period`, `token_explicit_max_ttl=0`; batch — только для prestart-чтения |
| Токен не продлевается, ожидаясь от legacy-контура | Старый workflow не умеет распознавать непродлеваемые токены | Перейти на workload identity (Nomad 1.10+) |
| Ошибки рендеринга «не тот секрет» | Роль/политика не ограничены claims — задача получает общий токен | Сузить роль через `bound_claims` + отдельные политики на джоб/namespace |
| Аллокация перезапускается при каждом обновлении секрета | `change_mode = "restart"` (значение по умолчанию) на `vault`/`template` | Для обновления конфига без рестарта — `change_mode = "signal"` + `change_signal` |
| Роли/квоты «появляются сами», кластер перегружен токенами Nomad | Management-роль выдаётся задачам либо `nomad/creds` читается без need-to-know | Типы ролей `client` + минимальные Nomad ACL-политики; management — только break-glass (см. [инциденты](./incident-response.md)) |

## Лучшие практики

* Основной контур «задача → Vault» — только workload identity; legacy-хранилище токена на Nomad-сервере отключить после миграции.
* Одна аудитория (`vault.io`), роль через `bound_claims` на уровне `nomad_namespace`/`nomad_job_id` — минимальные привилегии вместо общей роли на весь кластер.
* `jwks_url` — за балансировщиком/на нескольких агентах Nomad: недоступность URL блокирует вход **всех** задач.
* Тип токена задач — `service` с `token_period` и `token_explicit_max_ttl = 0`; batch-токены — исключительно для одноразового чтения на старте.
* Management-токен Nomad в `nomad/config/access` — эквивалент root-прав на Nomad: минимальный набор прав на токен, выдачу отдельной политикой, ротация; в Terraform он уходит в state.
* Роли `nomad/role` — с типом `client` и заранее созданными Nomad ACL-политиками; `type=management` только для аварийного доступа с последующим отзывом.
* `change_mode` сигналом/`noop` для конфиг-файлов, `restart` — только когда действительно нужен перезапуск процесса.
* Мониторить lease на `nomad/creds/*` и токены задач (квоты и алерты — в [квотах](./quotas.md) и [мониторинге](./monitoring_and_alerting.md)).

## Дополнительная информация

* [Nomad: шаблонизация и интеграция с Vault](../../Nomad/advanced_topics.md) — Nomad-сторона: `template`, `change_mode`, синтаксис Consul Template
* [consul-template](./consul-template.md) — тот же синтаксис шаблонов вне Nomad
* [Vault Kubernetes integration](./vault_kubernetes_integration.md) — аналогичный для Kubernetes обмен workload identity (SA-токен → JWT auth)
* [Интеграция с Terraform](./terraform-integration.md) — ресурсы Nomad-бэкенда и предупреждение про state
* [Инциденты и реагирование](./incident-response.md) — отзыв токена Nomad при компрометации management-токена
