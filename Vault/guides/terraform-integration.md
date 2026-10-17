# Интеграция Vault с Terraform

> **Актуально для:** Vault 2.x + Terraform Vault provider 5.13.x

## Определения

**Terraform provider `hashicorp/vault`** — провайдер, управляющий ресурсами Vault (политики, mounts, секреты, namespaces, auth-бэкенды) декларативно, через HCL-конфигурацию.

**State (состояние)** — файл Terraform с соответствие «объект конфигурации → реальный ресурс». Для Vault-провайдера критично: в него **в открытом виде** попадают значения секретов, поэтому state — защищаемый артефакт.

**Child token (дочерний токен)** — ограниченный токен, который Terraform создаёт сам себе через `auth/token/create` с коротким TTL после входа по `auth_login`: даже утечка токена процесса непродолжительна по времени и ограничена его TTL.

**Drift detection (обнаружение дрейфа)** — сравнение состояния в Vault с state при `terraform plan/apply`; работает, если у токена есть capability `read` на путь (для ряда ресурсов это можно отключить через `disable_read`, пожертвовав обнаружением дрейфа).

**Write-only атрибуты** — поля вида `data_json_wo` (write-only): провайдер записывает их в Vault, но не читает обратно; обновление требует инкремента `data_json_wo_version`.

## Основные концепции

### Как provider аутентифицируется

Минимальная конфигурация — адрес и токен:

```hcl
provider "vault" {
  # По умолчанию берётся из переменных окружения процесса Terraform
  # address = "https://vault.example.com:8200"   # VAULT_ADDR
  # token   = "hvs..."                           # VAULT_TOKEN
  # namespace = "team-a"                         # Vault Enterprise
  token_name = "terraform-prod-ci"               # display_name дочернего токена (VAULT_TOKEN_NAME)
}
```

Основные аргументы провайдера: `address`, `token`, `namespace` (Enterprise), `token_name` (по умолчанию `terraform`; удобно писать сюда commit hash или id джобы CI — токен будет виден в audit-логе), `ca_cert_file`/`ca_cert_dir` (`VAULT_CACERT`/`VAULT_CAPATH`), `tls_server_name`, `skip_tls_verify` (`VAULT_SKIP_VERIFY`, категорически не для прода), `skip_child_token` (отключает создание дочернего токена — **не рекомендуется**: вы увеличиваете время жизни возобновляемого токена в открытом виде).

Даже при входе через `auth_login` Terraform выпускает себе дочерний токен с коротким TTL — это встроенное ограничение воздействия, а не опция.

Блоки входа:

```hcl
# Предпочтительный вариант — типизированный блок под auth-движок:
# auth_login_userpass, auth_login_aws, auth_login_cert, auth_login_gcp,
# auth_login_kerberos, auth_login_radius, auth_login_oci, auth_login_oidc,
# auth_login_jwt, auth_login_azure, auth_login_token_file

# Универсальный path-based блок (для поддерживаемых напрямую движков и кастомных):
auth_login {
  path   = "auth/approle/login"
  parameters = {
    role_id   = var.approle_role_id
    secret_id = var.approle_secret_id
  }
}
```

`auth_login` пытается войти через `auth/<method>/login`; для движков, требующих подписи (например `aws`), задаётся `method = "aws"` — провайдер автоматически подпишет login-запрос. Документация рекомендует типизированные блоки вместо универсального, где это возможно.

### State и секреты: главное предупреждение

Для `vault_generic_secret` и `vault_kv_secret_v2` документация провайдера прямо говорит: **все данные из конфигурации пишутся в открытом виде в state и plan-файлы и выводятся в консоль Terraform**. Следствия:

* бэкенд state — шифруемый (S3 с KMS, GCS, Terraform Cloud с шифрованием), доступ строго ограничен;
* секреты не попадают в VCS и в логи CI;
* ротация ключа после любой смены доступа к state;
* там, где секрет читать не нужно, отключайте чтение (`disable_read = true`), понимая: дрейф обнаруживаться не будет.

Для чтения данных из Vault внутри Terraform есть data source `vault_generic_secret`/`vault_kv_secret_v2` — они также кладут прочитанное в state.

### Обзор ресурсов

| Ресурс / data source | Назначение | Особенности |
| :--- | :--- | :--- |
| `vault_policy` | ACL-политика | `allow_overwrite` по умолчанию `true` (в следующем major-релизе поведение изменится на «без перезаписи») |
| `vault_policy_document` (data) | Генерация HCL политики из блоков `rule` | `path`, `capabilities`, `allowed_parameter`/`denied_parameter`, `min/max_wrapping_ttl`, `required_parameters` → выход `.hcl` |
| `vault_mount` | Включение секретного движка | `options = { version = "2" }` для KV v2; `default/max_lease_ttl_seconds`, `seal_wrap`, `local`, `plugin_version`; экспортирует `accessor` |
| `vault_generic_secret` | Запись произвольного секрета | `path`, `data_json`; предупреждение про открытие в state; `delete_all_versions` для KV v2 |
| `vault_kv_secret_v2` | Секрет KV v2 | `mount`+`name`, `cas`, `data_json` либо write-only `data_json_wo` (+`data_json_wo_version`), блок `custom_metadata` (`max_versions`, `cas_required`, `delete_version_after` в секундах, `data`) |
| `vault_namespace` | Namespace (Enterprise) | `path`, `custom_metadata` (Vault 1.12+); экспортирует `id` (полный путь со слешем), `path_fq`, `namespace_id` |
| `vault_rgp_policy` / `vault_egp_policy` | Sentinel RGP/EGP (Enterprise) | `name`, `policy`, `enforcement_level`, для EGP — `paths` |
| `vault_nomad_secret_backend` / `vault_nomad_secret_role`, data `vault_nomad_access_token` | Nomad-токены из Vault | Секреты также попадают в state в открытом виде |

Capabilities, которые нужны токену Terraform: `create`/`update` на создаваемый путь, `delete` — при удалении ресурса, `read` — для дрейфа.

## Практические сценарии

### Политики как код

```hcl
data "vault_policy_document" "app" {
  rule {
    path         = "kv/data/myapp/*"
    capabilities = ["create", "read", "update", "delete", "patch"]
    description  = "read/write myapp secrets"
  }
  rule {
    path         = "kv/metadata/myapp/*"
    capabilities = ["list"]
  }
}

resource "vault_policy" "app" {
  name            = "myapp"
  allow_overwrite = false          # намеренный запрет тихой перезаписи политики из другого apply
  policy          = data.vault_policy_document.app.hcl
}
```

### Mount и секрет KV v2

```hcl
resource "vault_mount" "kvv2" {
  path        = "kv"
  type        = "kv"
  options     = { version = "2" }
  description = "KV v2 application secrets"
}

resource "vault_kv_secret_v2" "app" {
  mount = vault_mount.kvv2.path
  name  = "myapp/db"
  cas   = 1                      # обязателен при cas_required=true на движке/ключе

  data_json = jsonencode({
    username = "app"
    password = var.db_password    # в state будет открытым текстом
  })

  custom_metadata {
    max_versions = 10
    data = {
      owner = "team-a"
    }
  }
}
```

### Namespace (Vault Enterprise)

```hcl
resource "vault_namespace" "parent" {
  path = "team-a"
}

resource "vault_mount" "child_secrets" {
  namespace = vault_namespace.parent.path_fq   # полный путь родителя
  path      = "secrets"
  type      = "kv"
  options   = { version = "2" }
}
```

### Вход в CI через AppRole

```hcl
provider "vault" {
  address = var.vault_addr

  auth_login {
    path = "auth/approle/login"
    parameters = {
      role_id   = var.vault_role_id
      secret_id = var.vault_secret_id
    }
  }

  token_name = "terraform-${var.pipeline_id}"
}
```

Рекомендуемый контур: role_id/secret_id — переменные окружения CI (не в VCS), у ролей короткая продолжительность, `secret_id` через AppRole SecretID с TTL, а после apply — отзыв токена; политика CI-роли ограничена именно теми путями, что кодирует конфигурация.

### Импорт и обнаружение дрейфа

```bash
terraform import vault_policy.app myapp
terraform import vault_namespace.example team-a
terraform import vault_kv_secret_v2.example kv/data/myapp/db   # полный путь с data/

terraform plan    # read-capability нужна для сверки; расхождения видны как "changes"
```

Импорт политики идёт по `name`, namespace — по имени, KV-секрета — по полному пути включая `data/`.

## Устранение неполадок

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `Error creating: Unexpected response code: 403` (Permission denied) | У токена нет `create`/`update` на путь (или политика ссылается на несуществующий mount) | Добавить capability в политику CI-роли, сверить пути в `data.vault_policy_document` с реальными mount'ами |
| `Error: ... policy already exists` / конфликт перезаписи | Политика с тем же именем создана вне Terraform либо `allow_overwrite = false` | Импортировать существующий объект либо согласовать единого владельца политики |
| `Error: ... cas parameter did not match` (или ошибка CAS) | `cas_required = true`, а `cas` не задан/устарел | Указать актуальную версию либо снять `cas_required` |
| После apply plan снова показывает изменение секрета | Секрет правится вне Terraform, либо `disable_read = true` (дрейф не читается) | Вернуть источник истины в Terraform или принять изменение `terraform apply` |
| В логах CI/артефактах виден секрет | Значение попало в state/plan/console | Срочно ротировать секрет; включить маскирование переменных в CI; перейти на write-only `data_json_wo` + шифруемый бэкенд state |
| `A flag provided but not defined` / ошибки импорта KV | Импорт по неверному пути (без `data/`) | Использовать полный путь: `kvv2/data/secret` |
| Провайдер не находит namespace | Ресурс создан без `namespace`, а провайдер смотрит в root | Указать `namespace` у ресурса либо алиас провайдера для target-namespace |

## Лучшие практики

* Шифруемый и разграниченно доступный бэкенд state — не обсуждается: там лежат значения секретов.
* `token_name` заполнять идентификатором прогона (commit hash, id пайплайна) — audit-лог покажет, какой именно токен что изменил.
* Короткоживущий вход (AppRole/JWT OIDC) + дочерний токен провайдера; не давать CI-роли прав на `sys/`-администрирование.
* Явный `allow_overwrite = false` там, где политикой владеет другой процесс, — это защищает от взаимного затирания.
* Один владелец на объект: либо Terraform, либо ручное управление; импорт — штатный способ передать объект под управление.
* Для секретов, которые Terraformу не нужны читать, — `disable_read = true` (и смириться с отсутствием дрейфа) либо write-only `data_json_wo`.
* `terraform plan` в CI отдельным read-only токеном: ошибка дрейфа видна до apply.
* Регулярно обновлять провайдер: схемы ресурсов меняются (например, план по умолчанию `allow_overwrite`).

## Дополнительная информация

* [KV v2](./kv-v2.md) — семантика версий, CAS и метаданных, которые кодирует `vault_kv_secret_v2`
* [Sentinel-политики](./sentinel-policies.md) — ресурсы `vault_rgp_policy`/`vault_egp_policy`
* [Интеграция с Nomad](./nomad-integration.md) — бэкенд Nomad и чтение токенов в Terraform
* [AppRole](./vault_auth_approle.md) — настройка CI-роли и secret_id под этот сценарий
* [Авторизация и политики](../authorization.md) — как оцениваются capabilities токена провайдера
* [Антипаттерны](../common_antipatterns.md) — типовые ошибки при управлении Vault как кодом
