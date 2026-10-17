# Авторизация в HashiCorp Vault

В архитектуре Vault аутентификация отвечает за проверку личности (кто вы), а **авторизация** — за управление доступом (что вам разрешено делать). Основным механизмом авторизации являются политики, которые определяют права доступа к путям API.

## Предварительные требования

Перед написанием и применением политик убедитесь, что инфраструктура подготовлена:

- **Vault инициализирован и разблокирован:** Выполнен `vault operator init` с распределением ключей Shamir (рекомендуется минимум 3 из 5) и `vault operator unseal` на каждом узле.
- **Метод аутентификации включен:** Например, `vault auth enable kubernetes`, `vault auth enable approle`, `vault auth enable userpass`. Выполните `vault auth list` для проверки.
- **Движок секретов включен:** Для KV v2 — `vault secrets enable -path=secret -version=2 kv`. Выполните `vault secrets list -detailed` для проверки доступных путей.
- **Identity Store готов:** Сущности, группы и алиасы созданы через `vault write identity/entity ...` или автоматически при аутентификации. Выполните `vault identity list` для просмотра.
- **Аудит включен:** Как минимум один audit device (`file`, `syslog`) для фиксации всех операций авторизации. Без аудита невозможно отследить причину отказа в доступе.
- **Сеть:** Приложения и CI/CD-агенты имеют сетевая доступность до Vault на порту 8200 (или 8201 для Raft-кластера). В air-gapped средах используйте Vault Agent с кэшированием.
- **CLI версии:** Команды проверены на Vault 1.13+ (capability `patch`, параметры `allowed_parameters`/`denied_parameters`/`required_parameters` доступны с 1.13).

## Определения

**Авторизация (Authorization)** — процесс проверки прав доступа аутентифицированного субъекта (Entity) к конкретным путям, операциям и ресурсам в Vault.

**Политика (Policy)** — декларативный набор правил на языке HCL (HashiCorp Configuration Language), определяющий разрешенные возможности (capabilities) для путей в API Vault. Политики реализуют принцип наименьших привилегий и модель управления жизненным циклом безопасности (SLM).

**ACL (Access Control List)** — список контроля доступа, базовая форма политик в Vault, сопоставляющая пути API с разрешенными действиями.

**Capabilities (Возможности)** — набор атомарных операций (create, read, update, patch, delete, list, sudo, deny, subscribe, recover), которые могут быть разрешены или запрещены для конкретного пути.

## Основные механизмы

### 1. ACL-политики и возможности

ACL-политики являются основным инструментом управления доступом. Они работают по принципу **Deny-by-default**: любой доступ, который явно не разрешен, считается запрещенным.

#### Набор возможностей (Capabilities)

| Возможность | HTTP-метод | Описание | Применение |
| :--- | :--- | :--- | :--- |
| `create` | `POST`/`PUT` | Создание новых данных по пути. | Запись нового секрета. |
| `read` | `GET` | Чтение данных. | Получение значения секрета, генерация динамических учетных данных. |
| `update` | `POST`/`PUT` | Изменение существующих данных. | Перезапись секрета целиком. |
| `patch` | `PATCH` | Частичное обновление (Vault 1.13+). | Изменение отдельных полей в KV v2 без чтения всего секрета. |
| `delete` | `DELETE` | Удаление данных. | Удаление версии или ключа. |
| `list` | `LIST` | Просмотр списка ключей. | Навигация по иерархии секретов. |
| `sudo` | — | Доступ к root-protected путям (например, `sys/audit`, `sys/rotate`). | Системные настройки, управление движками. |
| `deny` | — | Явный запрет. | Имеет высший приоритет над любыми разрешениями, включая `sudo`. |
| `subscribe` | — | Подписка на события по пути (Vault Events, 1.15+). | Потребление событий через `/v1/sys/events/subscribe`. |
| `recover` | — | Восстановление данных по пути из снапшота. | Восстановление данных после сбоя/удаления из резервной копии (Snapshot Agent). |

Важные уточнения по возможностям:

*   **`create` vs `update`:** большинство частей Vault не различают эти две возможности, поэтому операции записи обычно требуют **обе**. Исключения явно отмечены в документации.
*   **`list` и безопасность:** ключи, возвращаемые операцией `list`, **не фильтруются** политиками — не закладывайте чувствительную информацию в имена ключей.
*   **Capability ≠ HTTP-метод на 100%:** соответствие приблизительное. Например, генерация динамических учетных данных базы данных выполняется HTTP-методом `GET`, поэтому требует `read`, а не `create`. Для уточнения используйте флаг `-output-policy` у любой CLI-команды.

#### Глобальные и системные политики

*   **`default`:** Автоматически привязывается к каждому токену, но может быть явно исключена при создании (флаг `-no-default-policy`). Содержит базовые права: просмотр собственного токена, использование cubbyhole. Может быть изменена — Vault не перезаписывает ваши модификации; для получения актуального содержимого выполните `vault read sys/policy/default`.
*   **`root`:** Обладает неограниченным доступом. Не может быть изменена, удалена или ограничена. После инициализации кластера существует ровно один root-токен — его следует отозвать (`vault token revoke <token>`) после настройки, а в продуктивных средах использование root-токенов является критическим нарушением безопасности.

### 2. Шаблонизация политик (Policy Templating)

Vault позволяет создавать универсальные политики, используя переменные Identity Store. Это избавляет от необходимости создавать отдельную политику для каждого пользователя. Подстановка выполняется только в **пути** политики, но не в других полях.

**Доступные переменные:**

| Переменная | Описание |
| :--- | :--- |
| `identity.entity.id` | Идентификатор сущности (например, UUID). |
| `identity.entity.name` | Имя сущности. |
| `identity.entity.metadata.<ключ>` | Метаданные сущности для заданного ключа. |
| `identity.entity.aliases.<mount_accessor>.id` | ID алиаса для конкретного метода аутентификации. |
| `identity.entity.aliases.<mount_accessor>.name` | Имя алиаса для конкретного метода аутентификации. |
| `identity.entity.aliases.<mount_accessor>.metadata.<ключ>` | Метаданные алиаса (например, `service_account_namespace` при входе через Kubernetes). |
| `identity.entity.aliases.<mount_accessor>.custom_metadata.<ключ>` | Пользовательские метаданные алиаса. |
| `identity.groups.ids.<group_id>.name` | Имя группы по её ID. |
| `identity.groups.names.<group_name>.id` | ID группы по её имени. |
| `identity.groups.ids.<group_id>.metadata.<ключ>` / `identity.groups.names.<group_name>.metadata.<ключ>` | Метаданные группы. |

**Пример шаблона:**
```hcl
# Доступ к персональному хранилищу на основе имени сущности
path "secret/data/users/{{identity.entity.id}}/*" {
  capabilities = ["create", "read", "update", "patch", "delete", "list"]
}

# Доступ на основе метаданных группы
path "secret/data/teams/{{identity.entity.metadata.team}}/*" {
  capabilities = ["read", "list"]
}
```

**Подходы по работе с шаблонами:**

*   Рекомендуется использовать **ID** (`identity.entity.id`) вместо имен: имена могут меняться со временем и переиспользоваться, тогда как ID уникальны.
*   Символы `*`, `+` и `/`, появившиеся в отрендеренном результате шаблона, приводят к отказу `permission denied`. Поведение для `/` настраивается опцией `deny_slash_in_templated_paths` (используйте опцию схемы `/v1/sys/config`).
*   Значение `mount accessor` для каждого метода аутентификации получают командой `vault auth list` (столбец `Accessor`), которое используется в переменных из семейства `identity.entity.aliases.*`.

### 3. Sentinel и продвинутая авторизация (Enterprise)

Для сложных сценариев комплаенса используются механизмы "Policy as Code":

*   **Sentinel:** Декларативный язык политик для проверки сложных условий: время суток, IP-адрес, заголовки HTTP-запроса, требование MFA, параметры API. Политики могут ссылаться на данные Identity (группы, алиасы) через импорт `identity` и на контекст запроса через `request`. Отдельная политика может возвращать `true`/`false` и, при необходимости, выдавать блокирующую ошибку.
*   **Endpoint Governing Policies (EGP):** Применяются ко всему эндпоинту независимо от токена. Переопределяют результат, полученный из ACL-политик токена.
*   **Role Governing Policies (RGP):** Применяются к конкретным токенам, сущностям или ролям — добавляют дополнительные ограничения поверх ACL.

Порядок оценки запросов (ACL → RGP → EGP), enforcement levels, механизм override и рабочие примеры правил — в [Sentinel-политики (RGP/EGP)](./guides/sentinel-policies.md).

### 4. Визуальный редактор и генератор политик (Vault 2.0+)

Начиная с Vault 2.0.0+ доступны два способа создания политик через GUI без ручного написания HCL:

*   **Визуальный редактор ACL-политик (Vault GUI):** Позволяет выбирать пути и возможности в UI, автоматически генерируя корректный HCL-код. Доступен во всех редакциях, требуется версия Vault 2.0.0+.
*   **Визуальный генератор политик (Vault Enterprise):** Интегрированный генератор внутри поддерживаемых движков (KV v2, PKI), который предзаполняет форму правильными путями для существующих секретов и генерирует политику, готовую к сохранению или копированию в Terraform Vault Provider.

Это снижает риск синтаксических ошибок и упрощает онбординг команд.

## Иерархия и приоритеты

При расчете итоговых прав (effective capabilities) для субъекта Vault использует **приоритетное сопоставление путей (priority matching)**, применяя только самое специфичное совпадение. Алгоритм:

1.  **Deny:** Если хотя бы одно правило (в любой политике) содержит `deny` для данного пути, доступ запрещен — `deny` всегда имеет высший приоритет, включая `sudo`.
2.  **Выбор самого специфичного правила:** Vault применяет **только** одно выигрышное правило — точное совпадение или самое длинное префиксное совпадение глоба (`*`). Правило `secret/data/app1/config` приоритетнее, чем `secret/data/app1/*`.
3.  **Union только для идентичных паттернов:** Если одинаковый паттерн пути встречается в нескольких политиках токена, их возможности объединяются (union). Если паттерны в применимых политиках различаются — применяется только правило с наивысшим приоритетом, без слияния.
4.  **Параметры пути:** После определения итоговых возможностей проверяются ограничения запроса (`allowed_parameters`, `denied_parameters`, `required_parameters`) и TTL обертки (`min_wrapping_ttl`, `max_wrapping_ttl`).

При сравнении двух правил `P1` и `P2` выигрывает то, у которого:
1.  Первый wildcard (`+` или `*`) встречается **позже**; если у `P1` wildcard раньше — `P1` ниже приоритетом.
2.  `P1` заканчивается на `*`, а `P2` нет → `P1` ниже приоритетом.
3.  У `P1` больше wildcard-сегментов `+` → `P1` ниже приоритетом.
4.  `P1` короче → `P1` ниже приоритетом.
5.  `P1` лексикографически меньше → `P1` ниже приоритетом.

### Тонкая настройка (Fine-grained control)

Параметры, доступные внутри блока `path`, позволяют ограничивать операции дальше, чем простой список capabilities:

| Параметр | Описание | Примечание |
| :--- | :--- | :--- |
| `allowed_parameters` | Разрешенные параметры запроса и их допустимые значения. Значение `[]` разрешает любое значение параметра; `"*" = []` разрешает любые другие параметры. | **Не поддерживается** для KV v2. |
| `denied_parameters` | Запрещенные параметры запроса. Имеют приоритет над `allowed_parameters`. `"*" = []` запрещает любые параметры. | **Не поддерживается** для KV v2. |
| `required_parameters` | Параметры, которые **обязаны** присутствовать в запросе. | **Не поддерживается** для KV v2. |
| `min_wrapping_ttl` / `max_wrapping_ttl` | Минимальный/максимальный TTL обертки ответа (wrapped token). Если оба заданы, минимальное значение всегда должно быть строго меньше максимального. | Используется для принудительного включения Response Wrapping (например, `min_wrapping_ttl = "1s"`). |
| `controlled_capabilities` | (Enterprise, Control Groups) Указывает, при каких capability срабатывает Control Group. | Дополнительно к `control_group`. |

**Пример параметров:**
```hcl
# Разрешить создание секрета только с параметрами foo (любое значение)
# и bar (только одно из: zip, zap)
path "secret/restricted" {
  capabilities = ["create"]
  allowed_parameters = {
    "foo" = []
    "bar" = ["zip", "zap"]
  }
}

# Запретить изменение чувствительных параметров у пользователя userpass
path "auth/userpass/users/*" {
  capabilities = ["update"]
  denied_parameters = {
    "token_policies" = []
    "policies"      = []
  }
}
```

**Пример Response wrapping TTL:**
```hcl
# Обернутый ответ при создании SecretID должен жить от 1 до 90 секунд
path "auth/approle/role/my-role/secret-id" {
  capabilities = ["create", "update"]
  min_wrapping_ttl = "1s"
  max_wrapping_ttl = "90s"
}
```

## Практические сценарии

### Настройка политики для приложения с KV v2

Сценарий: приложению нужно обновлять только пароль базы данных в KV v2-секрете, не имея прав на изменение других ключей этого секрета.

Важно: KV v2 **не поддерживает** `allowed_parameters`/`denied_parameters`. Детальное ограничение полей достигается через `path`-уровень (`patch` на конкретный `secret/data/...`) и, при необходимости, разбиение данных на отдельные пути с собственными политиками.

```hcl
# Разрешить чтение и частичное обновление (patch) секрета без прав на delete
path "secret/data/production/db-creds" {
  capabilities = ["read", "patch"]
}
```

`vault kv patch secret/production/db-creds password=...` выполняет HTTP-метод `PATCH` на путь `secret/data/production/db-creds` (внутренний `data/` добавляется автоматически), поэтому требуется именно capability `patch`. Точное ограничение только полем `password` на уровне KV v2 недоступно — для поля-уровня используйте KV v1 (раздел ниже) или отдельный секрет на поле.

### Ограничение параметров запроса (KV v1)

Сценарий: приложение с KV v1 может обновить только поле `password` в секрете, не имея прав на изменение остальных полей. Отметим, что для KV v1 применяется путь без сегмента `data/`.

```hcl
# Разрешить чтение и обновление секрета, но только параметра password
path "secret/production/db-creds" {
  capabilities = ["read", "update"]
  allowed_parameters = {
    "password" = []
  }
}
```

Если политика разрешает `create`/`update` по пути KV с любыми другими полями, `denied_parameters` может дополнительно запрещать их (например, блокировать перезапись `token_policies` у пользователей userpass).

### Управление политиками через CLI

1.  **Создание/Обновление:**
    ```bash
    vault policy write my-app-policy my-app-policy.hcl
    # → Success! Uploaded policy: my-app-policy
    ```
2.  **Просмотр содержимого политики:**
    ```bash
    vault policy read my-app-policy
    # → path "secret/data/app1/*" {
    #     capabilities = ["read"]
    #   }
    ```
3.  **Проверка прав текущего токена:**
    ```bash
    vault token capabilities secret/data/app1/config
    # → read, patch
    ```
4.  **Просмотр списка политик:**
    ```bash
    vault policy list
    # → default
    #   my-app-policy
    ```
5.  **Удаление политики (идемпотентно — ошибки не будет, если политика отсутствует):**
    ```bash
    vault policy delete my-app-policy
    ```
6.  **Форматирование HCL-файла политики:**
    ```bash
    vault policy fmt my-app-policy.hcl
    ```

### Использование Групп контроля (Control Groups)

Для критических операций (например, экспорт ключей шифрования) настраивается политика, требующая одобрения администратора. В отличие от Sentinel, Control Groups реализуются прямо в ACL-политике через блок `control_group`:

```hcl
path "secret_access/export-keys/encryption" {
  capabilities = ["read"]
  control_group = {
    factor "ops_manager" {
      identity {
        group_names = ["ops"]
        approvals = 2
      }
    }
  }
}
```

При попытке выполнения такой операции Vault не возвращает данные, а выдает ограниченный по времени `wrapping_token`. Его accessor передается членам группы-одобрителя; после накопления требуемого числа одобрений (`approvals`) через API `sys/control-group/authorize` операция завершается, и wrapping-токен можно развернуть для получения данных.

Дополнительно параметр `controlled_capabilities` в блоке `control_group` позволяет требовать одобрение только для конкретных операций (например, `sudo`), оставляя остальные беспрепятственными. Control Groups доступны в Vault Enterprise и HCP Vault Dedicated/Standard.

### Изоляция сред (dev/staging/prod)

Для разделения доступа между средами используйте либо префиксы путей, либо отдельные политики с явным указанием среды. Ниже — подход на основе префиксов, который не требует изменения синтаксиса при добавлении новой среды.

```hcl
# Общая политика для production: только чтение и патч
path "secret/data/production/{{identity.entity.metadata.team}}/*" {
  capabilities = ["read", "patch"]
}

# Staging: полный доступ для команды разработки
path "secret/data/staging/{{identity.entity.metadata.team}}/*" {
  capabilities = ["create", "read", "update", "patch", "delete", "list"]
}

# Dev: доступ по умолчанию для всех сотрудников
path "secret/data/development/*" {
  capabilities = ["read", "list"]
}

# Явный запрет на доступ к production из staging-инструментов
path "secret/data/production/*" {
  capabilities = ["deny"]
}
```

Для более строгой изоляции используйте отдельные mount-точки (`secret-prod`, `secret-staging`) с разными политиками. Это исключает случайный доступ при ошибке в пути.

### Политики для CI/CD пайплайнов

CI/CD-агенты (GitLab Runner, Jenkins, GitHub Actions) должны получать секреты только для своей ветки и проекта. Используйте аутентификацию через AppRole или JWT с привязкой к claims раннера. Пример политики для GitLab CI с AppRole описан в **[CI-CD/DevSecOps/secrets_management.md](../CI-CD/DevSecOps/secrets_management.md)**. Ключевые принципы:

- TTL токена совпадает с длительностью задачи (обычно 10–30 минут).
- Политика ограничивается префиксом `secret/data/ci/<project-id>/*`.
- `token_no_default_policy = true` для отключения политики `default`.
- SecretID передается через Response Wrapping (`-wrap-ttl=60s`), а не в открытом виде.

### Политики для Transit Engine

Transit Engine используется для шифрования/дешифрования данных без доступа к ключам. Политика должна минимизировать возможность выхода ключа за пределы Transit. Примеры и детальные сценарии (ключи с деривацией, ограничение контекста, подпись) описаны в **[Transit Engine — Политики](./guides/transit-encryption-policies.md)**. Минимальная политика для приложения:

```hcl
path "transit/encrypt/{{identity.entity.metadata.key_name}}" {
  capabilities = ["update"]
  allowed_parameters = {
    "context" = []
  }
}

path "transit/decrypt/{{identity.entity.metadata.key_name}}" {
  capabilities = ["update"]
  allowed_parameters = {
    "context" = []
  }
}
```

### Политики для динамических учетных данных баз данных

Динамические учетные данные создаются на лету и автоматически удаляются по истечении TTL. Политика для приложения, подключающегося к PostgreSQL через Vault:

```hcl
# Генерация динамических учетных данных
path "database/creds/{{identity.entity.metadata.db_role}}" {
  capabilities = ["read"]
}

# Обновление конфигурации подключения (опционально)
path "database/config/postgresql/prod" {
  capabilities = ["read"]
}
```

Важно: приложение не должно иметь прав на `database/config/*` с `create`/`update`/`delete`, иначе злоумышленник может изменить конфигурацию подключения и перенаправить трафик.

### Изоляция по namespace Kubernetes

При использовании Kubernetes auth метод аутентификация передает `service_account_namespace` в метаданные алиаса. Это позволяет создавать политики, автоматически ограничивающие доступ namespace:

```hcl
# Сервис из namespace team-a имеет доступ только к своим секретам
path "secret/data/teams/{{identity.entity.aliases.<kubernetes_mount_accessor>.metadata.service_account_namespace}}/*" {
  capabilities = ["read", "list"]
}
```

Значение `<kubernetes_mount_accessor>` получают командой `vault auth list` (столбец `Accessor` для метода `kubernetes`). Такой подход исключает необходимость создавать отдельную политику для каждого namespace.

### Аудит и мониторинг политик

Включите audit device на старте развертывания Vault:

```bash
# Файловый audit device (локальный)
vault audit enable file file_path=/var/log/vault/audit.log

# Syslog для централизованного сбора логов
vault audit enable syslog tag="vault-audit" facility=AUTH
```

Для мониторинга политик в production экспортируйте метрики:
- `vault.token.count.by_policy` — количество токенов с привязанной политикой.
- `vault.token.creation` — частота создания токенов (всплеск может указывать на компрометацию).
- `vault.request.count` — общее число запросов к путям, покрытым политиками.

Анализируйте лог на наличие `permission denied` с высоким `request.path` — это может быть reconnaissance со стороны скомпрометированного приложения.

## Типичные ошибки и устранение

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `403 Forbidden` / `permission denied` | Политика не покрывает путь или capability | Выполнить `vault token capabilities <path> <token>` для диагностики. Проверить точное совпадение пути, включая сегмент `data/` для KV v2. |
| `permission denied` при `vault policy read` | Токен не имеет `sudo` на `sys/policy/*` | Использовать токен с политикой, содержащей `capabilities = ["sudo", "read"]` на пути `sys/policy/*`, или root-токен. |
| Политика не применяется | Токен создан без политики или `token_no_default_policy=true` без явного указания политик | Проверить `vault token lookup <token>` → поле `policies`. Убедиться, что роль аутентификации привязывает нужную политику. |
| `list` возвращает больше ключей, чем ожидалось | `list` не фильтруется политиками | Не закладывать чувствительные данные в имена ключей. Использовать отдельные пути для разных уровней доступа. |
| Wildcard в шаблоне рендерит `/` | `deny_slash_in_templated_paths` включен по умолчанию | Либо изменить опцию в `/v1/sys/config`, либо переструктурировать Identity metadata, чтобы исключить `/` из значений. |
| `patch` не работает на KV v2 | Указан путь без сегмента `data/` или capability `patch` отсутствует | Проверить: `vault token capabilities secret/data/<path>` → должно содержать `patch`. Путь в CLI: `secret/data/...` (с `data/`). |

## Лучшие практики

1. **Deny-by-default:** Все политики должны явно разрешать только необходимые пути. Никогда не используйте `path "secret/*" { capabilities = ["read"] }` для приложений.
2. **Максимальная детализация путей:** Чем длиннее префикс пути, тем выше приоритет правила. Используйте полные пути вместо глобальных wildcard.
3. **Отдельные политики на приложение:** Одна политика = один сервис/инструмент. Это упрощает аудит и отзыв доступа.
4. **Минимальные capabilities:** Если приложению нужно только читать секрет, не добавляйте `create`/`update`/`delete`.
5. **Шаблонизация вместо индивидуальных политик:** Используйте `identity.entity.metadata.*` и группы, чтобы не поддерживать десятки идентичных политик.
6. **Аудит с первого дня:** Включите audit device до того, как приложения начнут запрашивать секреты. Без логов невозможно расследовать инцидент.
7. **Отказ от root-токенов в production:** После инициализации кластера создайте административные политики и отзовите root-токен. Используйте `sudo` capability на `sys/*` для операций администрирования.
8. **Response Wrapping для передачи секретов:** Вместо общего статического секрета используйте `-wrap-ttl` для передачи временных credential между сервисами.
9. **Регулярный аудит политик:** Выполняйте `vault policy list` и `vault token capabilities` на предмет устаревших правил, особенно после ротации команд и деплоя новых приложений.

## Границы применимости и ограничения

- **KV v2 не поддерживает тонкую фильтрацию полей:** `allowed_parameters`/`denied_parameters`/`required_parameters` работают только для KV v1 и не-движков. Для KV v2 используйте отдельные пути или `patch` capability.
- **Шаблонизация только в путях:** Переменные Identity Store подставляются только в блоке `path`, но не в значения параметров или capabilities.
- **Control Groups и Sentinel — Enterprise:** Control Groups, EGP и RGP требуют Vault Enterprise или HCP Vault Dedicated/Standard. В OSS используйте ACL-политики с явными `deny` и разделением путей.
- **Аудит не фильтрует чувствительные данные по умолчанию:** Включите audit device осторожно — он записывает все запросы и ответы (включая секреты) в лог. Обеспечьте защиту лога аудита (доступ по `sudo`, ротация, шифрование).
- **Сетевой доступ обязателен:** Приложения должны достигать Vault API. В air-gapped средах используйте Vault Agent с `auto-auth` и кэшированием, но учтите, что политики по-прежнему применяются на стороне Vault.
- **Токены имеют фиксированный TTL:** Даже с `renew` политика не продлевает бесконечно. Убедитесь, что TTL токена покрывает максимальное время работы приложения, либо используйте Vault Agent для автоматического продления.

## Дополнительная информация

*   **[Архитектура и концепции](./concepts.md)** — детали работы токенов и Identity Store.
*   **[Подход Zero Trust](./zero_trust.md)** — роль авторизации в архитектуре нулевого доверия.
*   **[Интеграция Vault с Kubernetes](./guides/vault_kubernetes_integration.md)** — примеры Kubernetes auth, VSO и CSI Driver.
*   **[Авторизация через AppRole](./guides/vault_auth_approle.md)** — практическое руководство по настройке AppRole для CI/CD и приложений.
*   **[Политики Transit Engine](./guides/transit-encryption-policies.md)** — сценарии ограничения encrypt/decrypt и деривации ключей.
*   **[Control Groups](./control_groups.md)** — multi-approval для критических операций (Enterprise).
*   **[SSH Secrets Engine](./guides/ssh_secrets_engine.md)** — динамические SSH-ключи и сертификаты.
*   **[Database Secrets Engine](./guides/database_secrets_engine.md)** — динамические учетные данные баз данных.
*   **[PKI/CA продвинутые сценарии](./guides/pki_ca_advanced.md)** — Intermediate CA, ACME, CRL/OCSP.
*   **[Производительность и репликация](./performance_and_replication.md)** — Performance Standby, DR Replication.
*   **[Мониторинг и алертинг](./monitoring_and_alerting.md)** — Prometheus, Grafana, SLO/SLI.
*   **[Анализ audit логов](./audit_log_analysis.md)** — SIEM, forensic, compliance.
*   **[Ротация секретов](./secret_rotation.md)** — стратегии ротации.
*   **[Namespaces](./namespaces.md)** — изоляция сред (Enterprise).
*   **[SLM, Vault Radar, Secrets Sync](./slm_radar_secrets_sync.md)** — Security Lifecycle Management.
*   **[Производительность и тюнинг](./performance_tuning.md)** — оптимизация для high-load.
*   **[Vault API Reference](./vault_api_reference.md)** — REST API и endpoints.
*   **[Cubbyhole и Response Wrapping](./guides/cubbyhole_response_wrapping.md)** — безопасная доставка секретов.
*   **[Стратегии бэкапов и восстановления](./backup_restore_strategies.md)** — RPO/RTO, disaster recovery.
*   **[Официальная документация по политикам](https://developer.hashicorp.com/vault/docs/concepts/policies)**
