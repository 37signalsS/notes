# KV v2 — Versioned Key/Value Secret Engine

> **Актуально для:** Vault 2.x (движок `kv`, версия 2)

## Определения

**KV (key-value)** — простейший секретный движок Vault: хранилище «ключ → значение» без логики динамической генерации. Существует в двух версиях: `kv` версии 1 (v1) и версии 2 (v2).

**Версия (version)** — сохранённый слой данных ключа в KV v2. Каждый `put` создаёт новую версию; старые остаются читаемыми до тех пор, пока не исчерпан лимит `max_versions`.

**Check-and-Set (CAS)** — механизм предотвращения перезаписи «вслепую»: запись принимается только если переданный параметр `cas` совпадает с текущей версией ключа (`cas=0` — ключ ещё не существует).

**Metadata** — запись `secret/metadata/<key>`: история версий, `current_version`, `max_versions`, `cas_required`, `delete_version_after`, пользовательские поля `custom_metadata` (произвольная карта строк).

**Soft delete / Undelete / Destroy** — три стадии удаления: `delete` помечает версию удалённой (данные физически остаются, появляется `deletion_time`), `undelete` возвращает её, `destroy` уничтожает данные версии безвозвратно (`destroyed: true`). Удаление всей записи вместе с историей — `DELETE` по `metadata`.

**Subkeys** — проекция ключа без значений: позволяет прочитать дерево подключей (и, при необходимости, только часть данных), не выгружая весь секрет.

**Patch** — частичное обновление текущей версии (merge по данным) вместо полной перезаписи значением `put`; требует capability `patch` в политике.

## Основные концепции

### KV v1 против KV v2

| Свойство | KV v1 | KV v2 |
| :--- | :--- | :--- |
| История версий | Нет, запись перезаписывается | Да, до `max_versions` версий |
| Check-and-Set | Нет | Да (`cas`, `cas_required`) |
| Soft delete / undelete | Нет | Да |
| Metadata и `custom_metadata` | Нет | Да |
| Patch (частичное обновление) | Нет | Да |
| Путь API данных | `secret/<key>` | `secret/data/<key>` |
| Производительность/объём | Меньше storage-операций | Доп. storage-вызовы и блокировки |

### Модель путей: CLI-путь ≠ путь API

Команда `vault kv` работает с обоими версиями, но в v2 её путь **не равен** реальному пути API — именно поэтому политики пишутся под `data/` и `metadata/`, а не под «голый» ключ:

| Команда | Endpoint в v1 | Endpoint в v2 |
| :--- | :--- | :--- |
| `vault kv get` | `secret/<key>` | `secret/data/<key>` |
| `vault kv put` | `secret/<key>` | `secret/data/<key>` |
| `vault kv list` | `secret/<key>` | `secret/metadata/<key>` |
| `vault kv delete` | `secret/<key>` | `secret/data/<key>` |
| `vault kv patch` | — | `secret/data/<key>` |
| `vault kv rollback` | — | `secret/data/<key>` |
| `vault kv undelete` | — | `secret/undelete/<key>` |
| `vault kv destroy` | — | `secret/destroy/<key>` |
| `vault kv metadata` | — | `secret/metadata/<key>` |

Полный список HTTP-endpoint'ов движка (методы REST): `POST/GET /:mount/config`, `GET/POST/PATCH/DELETE /:mount/data/:path`, `GET /:mount/subkeys/:path`, `POST /:mount/delete/:path`, `POST /:mount/undelete/:path`, `PUT /:mount/destroy/:path`, `LIST/GET/POST/PATCH/DELETE /:mount/metadata/:path`.

CLI-вывод в v2 намеренно печатает реальный путь (`=== Secret Path === secret/data/...`), чтобы оператор не путал политики. Для устранения путаницы есть флаг `-mount`:

```bash
vault kv put -mount=secret web-app api-token="WEOIRJ13895130WENJWEFN"
# → === Secret Path ===
#   secret/data/web-app
#   ======= Metadata =======
#   ... version 1
```

### Конфигурация движка и ключа

Настройки задаются на двух уровнях; настройка ключа перекрывает настройку движка:

| Параметр | Уровень | По умолчанию | Смысл |
| :--- | :--- | :--- | :--- |
| `max_versions` | движок / ключ | `0` | Сколько версий хранить на ключ; **при `0` или неуказанном Vault хранит 10**. При превышении самая старая версия удаляется безвозвратно |
| `cas_required` | движок / ключ | `false` | Требовать `cas` во **всех** записях |
| `delete_version_after` | движок / ключ | `"0s"` | Через сколько времени версия удаляется автоматически (`0s` — отключено) |

Отдельные значения версии (`max_versions`, `delete_version_after`, `cas_required`) и `custom_metadata` задаются на уровне ключа через `metadata`.

### Жизненный цикл версии

1. `put` создаёт версию `N` (`deletion_time: n/a`, `destroyed: false`).
2. `delete -versions=` помечает версию удалённой: появляется `deletion_time`, `destroyed` остаётся `false` — версию можно вернуть через `undelete`.
3. `destroy -versions=` уничтожает данные: `destroyed: true`, восстановление невозможно.
4. При росте числа версий сверх `max_versions` самые старые версии удаляются физически.
5. `DELETE /:mount/metadata/:path` стирает все версии и метаданные ключа целиком.

## Практические сценарии

### Включение движка

В dev-режиме Vault сам включает KV **v2** на пути `secret/` (в выводе `sys/mounts` видно `options map[version:2]`, `type kv`). На рабочем кластере включение/апгрейд:

```bash
# Включить KV v2 на пути secret/
vault secrets enable -path=secret kv-v2
# → Success! Enabled the kv-v2 secrets engine at: secret/

# Апгрейд существующего v1 до v2 (история не появляется, данные сохраняются)
vault kv enable-versioning secret/
# → Success! Enabled versioning on the KV secrets engine at: secret/

vault read secret/config
# → Key                  Value
#   ---                  -----
#   cas_required         false
#   delete_version_after 0s
#   max_versions         0
```

### Запись и чтение

```bash
vault kv put secret/customer/acme customer_name="ACME Inc." \
  contact_email="john.smith@acme.com"
# → === Secret Path ===
#   secret/data/customer/acme
#   ======= Metadata =======
#   Key            Value
#   ---            -----
#   created_time   2022-06-15T20:14:17.107852Z
#   custom_metadata <nil>
#   deletion_time  n/a
#   destroyed      false
#   version        1

vault kv get secret/customer/acme
# → ====== Secret Path ======
#   secret/data/customer/acme
#   ======= Metadata =======
#   ... version 1
#   ========== Data ==========
#   Key            Value
#   ---            -----
#   contact_email  john.smith@acme.com
#   customer_name  ACME Inc.
```

**Частичное обновление** (`put` полностью заменяет набор полей, `patch` — только переданные):

```bash
vault kv patch secret/customer/acme contact_email="admin@acme.com"
# → Success! Data written to: secret/data/customer/acme
```

KV v2 различает capabilities `create` (создание ключа) и `update` (полная перезапись), а для `patch` нужна отдельная capability `patch` — движок честно отражает эти различия в ACL.

### Check-and-Set включением по ключу

```bash
vault kv metadata put -cas-required=true secret/partner
# → Success! Data written to: secret/metadata/partner

# Ключа ещё нет — cas=0
vault kv put -cas=0 secret/partner name="Example Co." partner_id="123456789"
# → ... version 1

# Следующая запись должна указать текущую версию (1)
vault kv put -cas=1 secret/partner name="Example Co." partner_id="ABCDEFGHIJKLMN"
# → ... version 2
```

При несовпадении `cas` с текущей версией Vault отвечает ошибкой check-and-set (см. раздел неполадок). Глобальное включение на движке — `POST /:mount/config` с `{"cas_required": true}`.

### Работа с версиями

```bash
# Пометить версии 4 и 5 удалёнными (soft delete)
vault kv delete -versions="4,5" secret/customer/acme
# → Success! Data deleted (if it existed) at: secret/customer/acme

# Вернуть версию 5
vault kv undelete -versions=5 secret/customer/acme
# → Success! Data written to: secret/undelete/customer/acme

# Уничтожить данные версии 4 безвозвратно
vault kv destroy -versions=4 secret/customer/acme
# → Success! Data written to: secret/destroy/customer/acme

vault kv metadata get secret/customer/acme
# → ====== Version 4 ======
#   destroyed true
#   ====== Version 5 ======
#   deletion_time <timestamp>, destroyed false
```

Почитать конкретную версию: `vault kv get -version=3 secret/customer/acme` (API: `GET /secret/data/<key>?version=3`).

### Метаданные, лимиты и автозачистка

```bash
# Ограничить ключ 4 версиями
vault kv metadata put -max-versions=4 secret/customer/acme
# → Success! Data written to: secret/metadata/customer/acme

# Пользовательские метаданные (флаг повторяется)
vault kv metadata put -custom-metadata=Membership="Platinum" \
  -custom-metadata=Region="US West" secret/customer/acme

vault read secret/config          # конфиг движка
vault kv metadata get secret/customer/acme   # метаданные ключа
# → cas_required false, delete_version_after 0s, max_versions 0,
#   current_version 3, oldest_version 0, versions: {1..3}
```

`delete_version_after` (например `720h`) включает автоматическое удаление старых версий по таймеру; `"0s"` отключает автозачистку.

### Политики

Минимальные capability для типовых операций (проверяются флагом `-output-policy`, который печатает политику вместо выполнения команды):

```bash
vault kv put -output-policy secret/customer/acme customer_name="ACME Inc."
# → path "secret/data/customer/acme" {
#     capabilities = ["create", "update"]
#   }

vault kv get -output-policy secret/customer/acme
# → path "secret/data/customer/acme" {
#     capabilities = ["read"]
#   }
```

Пример рабочей политики на префикс:

```hcl
# Данные секретов: чтение и запись, плюс patch для частичных обновлений
path "secret/data/myapp/*" {
  capabilities = ["create", "read", "update", "delete", "patch"]
}

# История и листинг (list в v2 идёт по metadata)
path "secret/metadata/myapp/*" {
  capabilities = ["list", "read"]
}

# Полное уничтожение выделяется отдельно — capability delete на metadata
# разрешает стереть ключ со всеми версиями
path "secret/metadata/myapp/scratch/*" {
  capabilities = ["delete"]
}
```

Важно: capability `delete` на `metadata` удаляет **все** версии ключа; capability `delete` на `data` — только soft delete перечисленных версий. Листинг (`vault kv list`) требует `list` на `secret/metadata/...`, а не на `data/`.

## Устранение неполадок

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| Ошибка check-and-set при записи с `-cas` | Переданный `cas` ≠ текущей версии (ключ изменён параллельно) либо `cas_required=true`, а параметр не передан | Перечитать секрет (`vault kv get` → `version`), повторить с актуальным `cas`; для нового ключа `cas=0` |
| `A flag provided but not defined: -mount` | Используется старая версия Vault без поддержки синтаксиса `-mount` | Обновить клиент/сервер либо использовать старый path-like синтаксис (для v2 он неудобен: реальный путь — `secret/data/...`) |
| `Permission denied` при `vault kv list` | Политика выдана на `secret/data/...`, а листинг идёт в `secret/metadata/...` | Добавить `list` на `secret/metadata/<prefix>` |
| `Permission denied` на `secret/metadata/...` при чтении секретов | В KV v2 чтение требует доступа к `data/`, а отдельные операции — к `metadata/` | Разести политики по `data/` и `metadata/` (см. пример выше) |
| `unsupported path` при обращении к `metadata/...` | Путь обрабатывается движком KV **v1** | `vault kv enable-versioning <mount>` либо проверить `options map[version:2]` в `sys/mounts` |
| Старые версии исчезли | Достигнут лимит `max_versions` — старые версии удаляются безвозвратно | Поднять `max_versions` (`vault read secret/config`) или задать значение на ключ через `metadata`; восстановить удалённое нельзя |
| Ключ не найден сразу после `destroy` | `destroy` уничтожает данные; `deletion_time` остаётся, `destroyed: true` | Восстановление возможно только из резервной копии (`backup_restore_strategies`) |
| Приложение видит пустой ответ после `DELETE metadata` | Удалена вся запись со всеми версиями | Пересоздать ключ; ограничивать кому выдана capability `delete` на `metadata` |

## Лучшие практики

* Включать CAS (`cas_required`) там, где ключ пишут несколько независимых авторов — это защита от гонки «последний победил»; при однозначном единственном писателе CAS избыточен.
* Задавать осознанный `max_versions` (по умолчанию фактически 10) и при необходимости `delete_version_after` — иначе история растёт бесконечно, а вместе с ней — объём storage.
* Разделять политики: `data/` — работа с секретами, `metadata/` — листинг и управление историей; capability `delete` на `metadata` выдавать только операторам, которым нужно полное уничтожение.
* Использовать `-output-policy` при разработке политик: он показывает точный путь и capabilities, которые реально требует команда.
* Указывать `-mount=` в скриптах — так код читается однозначно и не зависит от устаревшего path-like синтаксиса.
* Не путать версии при апгрейде: `enable-versioning` включает v2 на существующем пути, но данные v1 не получают историю задним числом.
* Для конкурентных CI-процессов (Terraform, миграции) сочетать `-cas` с политикой, ограничивающей запись конкретным префиксом.

## Дополнительная информация

* [Основные концепции](../concepts.md) — токены, lease, модель секретов Vault
* [Авторизация и политики](../authorization.md) — как capabilities оцениваются для путей
* [API-справочник](./vault_api_reference.md) — обращения к `sys/`-эндпоинтам
* [Резервное копирование и восстановление](./backup_restore_strategies.md) — единственный способ вернуть уничтоженные (`destroyed`) версии
* [Интеграция с Terraform](./terraform-integration.md) — управление mount и секретами KV как кодом
