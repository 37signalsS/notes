# Rate limit и lease quotas в Vault

> **Актуально для:** Vault 2.x (latest 2.1.2; ветка 1.21.x поддерживается)

## Определения

**Resource quotas** — лимиты потребления ресурсов Vault: rate limit quotas (RPS-лимиты запросов) и lease count quotas (лимит количества lease).

**Rate limit quota** — лимит запросов в секунду по алгоритму **token bucket**. Доступна в **Vault Community и Enterprise**: одно критичное уточнение — в Community реализован только режим группировки `ip`; все `group_by`-режимы для нескольких клиентов в общую «bucket» — Enterprise.

**Lease count quota** — лимит одновременно существующих lease; защита от **lease explosion**. Только **Vault Enterprise**.

**`block_interval`** — если задан ненулевой, клиент, достигший порога rate quota, блокируется от всех последующих запросов на указанное число секунд.

**Exempt paths** — пути, не подлежащие rate limiting по умолчанию: `sys/health`, `sys/seal-status`, `sys/unseal`, `sys/generate-root/attempt`, `sys/generate-root/update`, `sys/generate-recovery-token/attempt`, `sys/generate-recovery-token/update`. Список переопределяется полем `rate_limit_exempt_paths` в конфиге квот.

**429 Too Many Requests** — статус, который возвращает Vault при нарушении rate limit quota или lease count quota (`rate limit quota exceeded` / `lease count quota exceeded`).

## Основные концепции

### Матрица возможностей

| Возможность | Community | Enterprise |
| :--- | :--- | :--- |
| Rate limit quota (`rate`, `interval`, `block_interval`) | Да | Да |
| `group_by=ip` (по умолчанию) | Да | Да |
| `group_by` `none`, `entity_then_ip`, `entity_then_none` + `secondary_rate` | Нет | Да |
| Lease count quota (`max_leases`) | Нет | Да |
| Namespaces в `path`, `inheritable` | Нет | Да |

### Механика rate limit

* Лимит действует **на каждый узел отдельно** (квоты не реплицируются): фактический суммарный RPS кластера ≈ `rate` × число узлов, пока LB распределяет запросы равномерно.
* По умолчанию bucket ведётся на **уникальный IP клиента** внутри правила квоты.
* Превышение → HTTP 429 с ошибкой `request path "...": rate limit quota exceeded`.
* `interval` (по умолчанию `1s`) — окно, за которое разрешено `rate` запросов; после исчерпания — запросы возвращаются до конца окна либо блокируются на `block_interval`.

### Приоритет квот (самое специфичное выигрывает)

Порядок из документации (от высшего к низшему):

1. Квота по namespace + mount + **role** (логины конкретной роли auth mount — выше всех).
2. Квота по namespace + mount + path.
3. Квота по namespace + mount + длиннейший префикс path с glob (`*`).
4. Квота по namespace + mount.
5. Квота по namespace.
6. Квота по ближайшему родительскому namespace (если у неё `inheritable=true`).
7. Глобальная квота (пустой `path`).

Правила: на любой path действует только одна rate-квота; глобальная квота (пустой path) наследуется всеми mounts/namespace; не-глобальные квоты в дочерние namespace не наследуются.

### Аудит и наблюдаемость отказов

Отклонённые по rate limit запросы **не попадают в audit-лог по умолчанию**. Включение:

```bash
vault write sys/quotas/config enable_rate_limit_audit_logging=true
```

Альтернатива/дополнение — response headers (`enable_rate_limit_response_headers=true`): `X-Ratelimit-Limit`, `X-Ratelimit-Remaining`, `X-Ratelimit-Reset`, `Retry-After`. Есть также quota metrics в telemetry.

### Lease count quota (Enterprise)

```bash
vault write sys/quotas/lease-count/<name> path=<mount> max_leases=<N>
```

* При создании квота заполняется текущим числом lease по пути: если lease уже больше `max_leases`, счётчик стартует «в плюсе» — новые lease будут отклоняться до разгрузки.
* Превышение → 429, ошибка `lease count quota exceeded`; аутентификация и выдача кредитов блокируются до ревоки/истечения lease.
* **С 1.16.0 новые инсталляции Vault Enterprise** получают глобальную квоту с `max_leases=300000` — намеренно низкий предохранитель от runaway-lease.

### Связь с user lockout

User lockout (отдельный механизм: блокировка учётки при серии неудачных логинов, включён по умолчанию для AppRole/LDAP и др. с 1.13) живёт на уровне auth mount (`auth tune`), а не в quotas. Это разные уровни защиты: lockout — на конкретного пользователя, rate limit — на поток запросов, lease count — на объём выданных lease. Подробнее lockout — в [AppRole](./vault_auth_approle.md) и [LDAP](./vault-auth-ldap.md).

## Практические сценарии

### Глобальный rate limit

```bash
vault write sys/quotas/rate-limit/global-rate \
    path="" \
    rate=1000 \
    interval=1s

vault read sys/quotas/rate-limit/global-rate
```

Пустой `path` — глобальная квота на весь API.

### Лимит на уязвимый mount (защита от перебора MFA/логинов)

```bash
# Rate limit на login-путь конкретного auth method
vault write sys/quotas/rate-limit/ldap-login \
    path="auth/ldap/login/" \
    rate=10 \
    interval=1s \
    block_interval=60
```

Документация прямо рекомендует такие лимиты на login и `/sys/mfa/validate` пути против перебора TOTP (см. [MFA](./vault-mfa.md)).

### Лимит на выдачу сертификатов PKI

```bash
vault write sys/quotas/rate-limit/pki-issue \
    path="pki/issue/" \
    rate=50 \
    interval=1s
```

### Rate limit по роли AppRole (самый высокий приоритет)

```bash
vault write sys/quotas/rate-limit/approle-ci \
    path="auth/approle/" \
    role="ci" \
    rate=20 \
    interval=1s
```

### Lease count quota (Enterprise)

```bash
vault write sys/quotas/lease-count/db-lease-guard \
    path="database/creds/" \
    max_leases=5000

vault read sys/quotas/lease-count/db-lease-guard
```

### Диагностика и включение аудита отказов

```bash
vault list sys/quotas/rate-limit
vault list sys/quotas/lease-count

vault write sys/quotas/config \
    enable_rate_limit_audit_logging=true \
    enable_rate_limit_response_headers=true
```

## Устранение неполадок

| Симптом | Причина | Действия |
| :--- | :--- | :--- |
| 429 `rate limit quota exceeded` | Достигнут лимит (клиент, mount или глобальный) | Определить сработавшую квоту (`list`/`read`), поднять `rate`/`interval` либо усечь клиента |
| 429 `lease count quota exceeded` при логине | Lease explosion или лимит слишком низок | Mass revoke утечки ([incident-response](./incident-response.md)) либо поднять `max_leases` |
| Отклонённых запросов нет в audit | Аудит отказов выключен по умолчанию | `sys/quotas/config enable_rate_limit_audit_logging=true` |
| Ожидали лимит на весь кластер, а он «вдвое» | Rate limit действует per-node | Учитывать множитель узлов либо ограничивать на стороне LB |
| Квота не действует на `sys/health` и подобные | Exempt paths по умолчанию | Переопределить `rate_limit_exempt_paths`, если это действительно нужно |
| Квота в namespace не применяется к дочерним | Не-глобальные квоты не наследуются | Задать `inheritable=true` (Enterprise) либо квоту в дочернем namespace |
| Ошибка при создании role-квоты | `path` не auth mount либо у mount нет roles | Проверить `path` (`auth/approle/` и т.п.) |

## Лучшие практики

* Всегда иметь хотя бы одну lease count quota (Enterprise) — документация называет это защитой от lease explosions; для Community — минимальные TTL и мониторинг числа lease.
* Rate limit на login-пути и `/sys/mfa/validate` — обязательная мера против перебора паролей/TOTP.
* Гранулярность: низкие лимиты на namespace/проблемном path, не глобальные «one size» — глобальная `group_by=none`-квота делает кластер уязвимым к одному дурному клиенту.
* Аудит отказов включить на проде: без него 429 не оставляют следа, и инциденты с throttling не диагностируются.
* При планируемых всплесках (маркетинг, релиз) временно поднимать квоты заранее — не в момент 429.
* Квоты настраивать через Terraform (рекомендация документации) для воспроизводимости.

## Дополнительная информация

* [MFA](./vault-mfa.md) — rate limits как защита TOTP от перебора
* [AppRole](./vault_auth_approle.md), [LDAP](./vault-auth-ldap.md) — user lockout на уровне auth mount
* [Инциденты и реагирование](./incident-response.md) — lease explosion, массовый отзыв
* [Мониторинг и алертинг](./monitoring_and_alerting.md) — метрики квот и 429
* [Основные концепции](../concepts.md) — lease, токены
