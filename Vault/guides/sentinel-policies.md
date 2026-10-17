# Sentinel-политики в Vault (RGP и EGP)

> **Актуально для:** Vault Enterprise 2.x (Sentinel)

## Определения

**Sentinel** — язык и движок политик HashiCorp; в Vault Enterprise позволяет писать гибкие правила поверх ACL: условия на данные запроса, Identity, окружение.

**RGP (Role Governing Policy)** — политика, привязанная к **токену** (через Identity entity/group или политику токена), без указания пути: действует на все операции, выполняемые этим токеном.

**EGP (Endpoint Governing Policy)** — политика, привязанная к **пути** (со шаблоном `*`): действует на любой запрос к этому пути, включая **неаутентифицированные** (логины).

**Enforcement level** — уровень применения: `advisory` (провал допустим — только предупреждение), `soft-mandatory` (провал блокируется, кроме явного override), `hard-mandatory` (провал всегда блокирует).

**Override** — явное разрешение обхода `soft-mandatory` политики: флаг CLI `-policy-override` либо HTTP-заголовок `X-Vault-Policy-Override: true`. Каждый override попадает в audit-лог и в server-лог предупреждениями.

**Properties** — встроенные в Sentinel-окружение данные: `request`, `token`, `identity`, `namespace`, `replication` (полный перечень — в документации «Sentinel properties for Vault Enterprise»).

## Основные концепции

### RGP против EGP

| | RGP | EGP |
| :--- | :--- | :--- |
| Привязка | Токен / entity / группа | Путь (глоб-шаблон) |
| Пути в правиле | Не нужны — правило действует везде, где работает токен | Ключевая часть: `paths` при создании |
| Неаутентифицированные запросы (логин) | Нет (нет токена) | Да — `*` покрывает и login-пути |
| Типовой сценарий | «Этот токен не может ничего делать после даты X» | «На путь X вход только с MFA» |

### Порядок оценки запроса

1. Запрос **неаутентифицирован** → ACL не проверяются, сразу оценка EGP на запрошенный путь.
2. Иначе — ACL-политики токена: без capability запрос отклоняется как обычно.
3. Затем — все RGP, привязанные к токену: каждая должна пройти в соответствии со своим enforcement level.
4. Затем — EGP на сам путь и все less-specific префиксы этого пути: каждая должна пройти.
5. Любое непройденное обязательное правило → отказ; из `advisory` — только предупреждение.

Исключения: **root-токены не подчиняются Sentinel** вообще; пути генерации root-токена не поддерживают EGP (это механизм последней надежды, когда, например, EGP сами всех заблокировали).

Производительность: Sentinel-оценка **заметно медленнее** ACL — политики тестируются до продового внедрения, а частотные пути не стоит утяжелять сложными правилами.

### Enforcement level

| Уровень | Поведение | Типичное применение |
| :--- | :--- | :--- |
| `advisory` | Провал разрешён, логируется | Каталог ошибок, «учебный» режим |
| `soft-mandatory` | Провал блокируется, кроме `-policy-override` | Основной рабочий уровень с аварийным обходом |
| `hard-mandatory` | Провал блокируется всегда | Критичные запреты без обхода |

### Свойства, на которые чаще всего пишут правила

* `request.path`, `request.operation` (`read`, `update`, `create`…), `request.data`, `request.connection.remote_addr`, `request.unauthenticated`, `request.policy_override`, `request.wrapping.ttl`.
* `token.creation_time` (RFC3339), `token.creation_time_unix`, `token.type` (`service`/`batch`), `token.policies`, `token.num_uses`, `token.metadata`.
* `identity.entity.id`, `identity.entity.name`, `identity.entity.metadata`; группы — `identity.groups.names`, `identity.groups.by_id` (для ссылок безопаснее **ID**: имена можно пересоздать).
* `namespace.id`/`namespace.path`, `replication.dr.mode`, `replication.performance.mode` — для условий «только на primary/DR».

Импорты, которые используются в примерах документации: `sockaddr` (CIDR), `mfa`, `strings`, `time`.

## Практические сценарии

### Создание политик

```bash
# RGP: жёсткое правило для токенов/сущностей
vault write sys/policies/rgp/deny-all \
  enforcement_level=hard-mandatory \
  policy=@deny-all.sentinel
# → Success! Data written to: sys/policies/rgp/deny-all

# EGP: правило на набор путей (можно перечислять через запятую или массивом)
vault write sys/policies/egp/breakglass \
  enforcement_level=soft-mandatory \
  paths="kv/data/legacy/*" \
  policy=@breakglass.sentinel
# → Success! Data written to: sys/policies/egp/breakglass

vault list sys/policies/egp      # → keys = ["breakglass", ...]
vault read sys/policies/rgp/deny-all   # → name, policy, enforcement_level
vault delete sys/policies/egp/breakglass
```

`paths` принимает строку через запятую или массив; `*` действует на **все** аутентифицированные и login-запросы.

### Пример 1 — вход по LDAP только с MFA и из сети

```sentinel
import "sockaddr"
import "mfa"
import "strings"

# Только приватный диапазон
cidrcheck = rule {
  sockaddr.is_contained("10.20.0.0/16", request.connection.remote_addr)
}

# Успешный ping-MFA
ping_valid = rule {
  mfa.methods.ping.valid
}

main = rule when strings.has_prefix(request.path, "auth/ldap/login") {
  ping_valid and cidrcheck
}
```

Конструкция `rule when <условие>` важна: политика применяется только при выполнении условия, а во всех остальных случаях — no-op. Так сохраняется default-deny философия Vault: не надо строить правило, которое «по умолчанию пускает».

### Пример 2 — RGP по метаданным Identity

```sentinel
precond = rule {
  identity.entity.metadata.org_id is "A012345X"
}

main = rule when precond {
  false
}
```

Если у entity есть `org_id = A012345X`, запрос отклоняется при `hard-mandatory` — независимо от того, к какому пути идёт запрос: у RGP нет привязки к пути. Симметричный «белый список»:

```sentinel
main = rule {
  identity.entity.name is "jeff" or
  identity.entity.id is "fe2a5bfd-c483-9263-b0d4-f9d345efdf9f" or
  "sysops" in identity.groups.names or
  "14c0940a-5c07-4b97-81ec-0d423accb8e0" in keys(identity.groups.by_id)
}
```

### Пример 3 — break-glass: мгновенно запретить все старые токены

```sentinel
import "time"

main = rule when not request.unauthenticated {
  time.load(token.creation_time).unix >
  time.load("2017-09-17T13:25:29Z").unix
}
```

В качестве EGP на `*` блокирует доступ с любым токеном, созданным **до** указанного времени: не нужно ждать массового отзыва десятков тысяч токенов и рисковать зацепить невиновные — новые токены работают сразу, старые перестают проходить.

### Пример 4 — делегирование управления чужими EGP

```sentinel
import "strings"

data_match = func () {
  if length(request.data else 0) is 0 {
    return false
  }
  if length(request.data.paths else 0) is 0 {
    return false
  }
  for strings.split(request.data.paths, ",") as path {
    sanitizedPath = strings.trim_prefix(path, "/")
    if not strings.has_prefix(sanitizedPath, "dev-kv/teama/") and
       not strings.has_prefix(sanitizedPath, "prod-kv/teama/") {
      return false
    }
  }
  return true
}

precond = rule {
  request.operation in ["create", "update"] and
  strings.has_prefix(request.path, "sys/policies/egp/")
}

main = rule when precond {
  strings.has_prefix(request.path, "sys/policies/egp/teama-") and data_match()
}
```

Так EGP-политика делегирует команде право создавать только `sys/policies/egp/teama-*` и только на пути их пространства `dev-kv/teama/`, `prod-kv/teama/`.

### Обход и тестирование

```bash
# Один запрос с обходом soft-mandatory (видно в audit-логе)
vault write -policy-override sys/policies/egp/... ...
# или HTTP: X-Vault-Policy-Override: true
```

Практика внедрения: выкатить как `advisory` и посмотреть предупреждения в логах/audit, затем `soft-mandatory`, заранее договорившись о процедуре `-policy-override`, и только потом — `hard-mandatory` там, где обход недопустим.

### Кодирование в Terraform

```hcl
resource "vault_egp_policy" "breakglass" {
  name              = "breakglass"
  paths             = ["*"]
  enforcement_level = "soft-mandatory"
  policy            = file("${path.module}/sentinel/breakglass.sentinel")
}

resource "vault_rgp_policy" "deny_old_tokens" {
  name              = "deny-old-tokens"
  enforcement_level = "hard-mandatory"
  policy            = file("${path.module}/sentinel/deny-old-tokens.sentinel")
}
```

Оба ресурса — только Vault Enterprise; `enforcement_level` обязателен, у EGP обязателен `paths`.

## Устранение неполадок

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| Запрос отклонён, хотя в ACL capability есть | Не прошла RGP/EGP (enforcement `hard-mandatory`/`soft-mandatory`) | Прочитать текст политики (`vault read sys/policies/...`), воспроизвести условие на `request`/`token`/`identity` свойствах |
| Отказ прямо на логине (`auth/.../login`) | EGP на `*` или на login-пути | Проверить EGP на `sys/policies/egp`; либо ограничить `main = rule when ...` |
| «Не срабатывает» на `sys/generate-root` | Этот путь не поддерживает EGP (защита от взаимоблокировки) | Используйте другие механизмы (root-токен держите под замком, [control groups](./control_groups.md)) |
| Запрос прошёл, хотя «политика должна была блокировать» | Токен — root (не подчиняется Sentinel) либо уровень `advisory` | Проверить токен (`vault token lookup`); поднять enforcement level |
| Нужно выполнить операцию под блоком | `soft-mandatory` + явный override | `vault write -policy-override ...` / заголовок `X-Vault-Policy-Override: true`; зафиксировать обход в audit |
| Ошибка компиляции политики при записи | Синтаксис Sentinel, отсутствующий import | Свериться с примерами документации; доступные в Vault импорты: `sockaddr`, `mfa`, `strings`, `time` и др. |
| Рост latency на частых путях | Тяжёлое правило на высокочастотном API | Упростить условие, сузить `paths`, перевести предварительную фильтрацию в ACL, тестировать под нагрузкой |
| MFA-условие не срабатывает на логине | Неправильно указаны method/condition либо правило не охватывает login-путь | Использовать скобку `rule when strings.has_prefix(request.path, "auth/<method>/login")` из официального примера |

## Лучшие практики

* Каталог ошибок: `advisory` → `soft-mandatory` → `hard-mandatory`; на `hard-mandatory` заранее определить, кто и как может дать override.
* `rule when` как основной паттерн: политика описывает, при каких условиях запрос **валиден**, а не «что блокировать» — так сохраняется default-deny.
* В identity-правилах ссылаться на **ID** entity/групп, а не имена (имена пересоздаваемы и обмениваемы).
* Override — редкое осознанное действие: каждое упоминание попадает в audit-лог, поэтому протухшие политики чинят, а не «пере-оверрайдят».
* Не усложнять правила на горячих путях: Sentinel значительно медленнее ACL.
* Помнить про root: вне Sentinel, и отдельно беречь пути генерации root-токена.
* Политики как код (Terraform-ресурсы `vault_rgp_policy`/`vault_egp_policy`) + code review: Sentinel-правила — такой же источник риска, как ACL.
* Для защиты от перебора логинов на EGP-логинах сочетать с rate limits ([квоты](./quotas.md)) и [MFA](./vault-mfa.md): Sentinel решает «кому можно», квоты — «сколько раз можно пытаться».

## Дополнительная информация

* [Авторизация и политики](../authorization.md) — базовый ACL-слой, поверх которого работают RGP/EGP
* [MFA](./vault-mfa.md) — Login MFA и Step-up MFA, которые апеллируют EGP-правила
* [Control groups](./control_groups.md) — Enterprise-механизм согласования доступа (другой, не Sentinel, инструмент)
* [Интеграция с Terraform](./terraform-integration.md) — ресурсы `vault_rgp_policy` / `vault_egp_policy`
* [Инциденты и реагирование](./incident-response.md) — сценарии, ради которых пишутся break-glass политики
