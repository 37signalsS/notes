# vmauth: прокси аутентификации и маршрутизации

## Определения

**vmauth** — лёгкий reverse proxy из экосистемы VictoriaMetrics: аутентифицирует запросы (Basic Auth, Bearer token, JWT, OIDC) и маршрутизирует их на backend-компоненты (vminsert, vmselect, vmsingle, VictoriaLogs, VictoriaTraces и др.) по пути запроса и правам пользователя. По умолчанию слушает порт `8427`.

**url_prefix** — список backend-адресов, на которые vmauth распределяет трафик пользователя (один запрос → один из бекендов).

**url_map / src_paths** — набор правил маршрутизации по префиксам/регекспам пути запроса (например, `/api/v1/query*` → vmselect, `/select/logsql/*` → VictoriaLogs).

**load_balancing_policy** — стратегия выбора бекенда: `least_loaded` (по умолчанию, балансирует по числу активных запросов) или `first_available` (первый здоровый).

## Базовые концепции

### Место в стеке

```
        │
 клиенты (dashboards, vmagent, vmalert, curl)
        │
        ▼
   ┌─────────┐
   │  vmauth │   аутентификация + маршрутизация (8427)
   └────┬────┘
        │ (по путям)
    ┌───┴─────┬────────────┐
    ▼         ▼            ▼
 vmselect   vminsert   VictoriaLogs
 (запросы)  (запись)   (логи/трейсы)
```

Типовые применения: единая точка входа для панелей и агентов без многократного указания адресов, мульти-тенантность (маршрут по `X-Scope-OrgID`/префиксу пути `/select/0/...`), ограничение прав по пользователям, балансировка и фейловер между репликами vmselect/vminsert.

### Конфигурационный файл

```yaml
# /etc/victoriametrics/vmauth.yml
users:
  - username: monitoring      # Basic Auth (или password)
    password: secret
    url_prefix:
      - http://vmselect:8481/select/0/prometheus/
      - http://vmselect-ha2:8481/select/0/prometheus/
    load_balancing_policy: least_loaded
    retry_status_codes: [429, 502, 503]
    headers:
      - "X-Env: prod"

  - username: vmagent         # право писать
    password: write-secret
    url_prefix: http://vminsert:8480/insert/0/prometheus/
    url_map:
      - src_paths: ["/api/v1/write"]
        url_prefix: http://vminsert:8480/insert/0/prometheus/
      - src_paths: ["/api/v1/query", "/api/v1/query_range"]
        url_prefix: http://vmselect:8481/select/0/prometheus/

  - bearer_token: "s3cr3t"    # токен вместо пароля
    url_prefix: http://vmsingle:8428/

  - username: outro
    password: outro
    ip_filters:
      allowlist: [10.0.0.0/8, "172.16.0.0/12"]
      denylist: ["10.0.0.3"]

unauthorized_user:            # доступ «без авторизации» (токен не требуется)
  url_prefix: http://vmselect:8481/select/0/prometheus/
```

- `users[]` — список учётных записей; у каждой может быть `username`/`password`, `bearer_token`, или OIDC-конфигурация; правила применяются по **первому совпадению** с запросом (пользователь + путь).
- `url_map[].src_paths` — регекспы пути запроса; подставляются к `url_prefix` (рекомендуется заканчивать `*`). Только первый совпадающий элемент применяется.
- `drop_src_path_prefix_parts: N` — удаляет N компонентов пути из запроса перед передачей на бекенд (нужно, когда vmauth подставляется внутрь пути, например при маршрутизации `-remoteWrite.url` с суффиксом `.../api/v1/write`).
- `default_url` — маршрут по умолчанию для запросов без совпадения по `url_map` (иначе по умолчанию — запрос отклоняется).
- `headers` — дополнительные заголовки в запросах к бекенду (например, `Authorization` для внутренней авторизации).
- `retry_status_codes` — HTTP-коды ответа, после которых vmauth ретраит запрос на следующем бекенде из `url_prefix`.
- `ip_filters.{allowlist,denylist}` — ограничение по IP (поддерживает CIDR и `<ip>:<port>`).

## Практические сценарии

### 1. Единая точка входа для метрик, логов и трейсов (vmalert)

Если `vmalert` должен одновременно обслуживать правила метрик (MetricsQL) и логов (LogsQL), `-datasource.url` указывает на vmauth, а маршрут выбирается по пути запроса:

```yaml
users:
  - bearer_token: "vmalert-token"
    url_map:
      - src_paths: ["/api/v1/query", "/api/v1/query_range", "/api/v1/series"]
        url_prefix: http://vmselect:8481/select/0/prometheus/
      - src_paths: ["/select/logsql/*"]
        url_prefix: http://victorialogs:9428/
```

### 2. Мульти-тенантность кластера

Путь `/insert/0/prometheus/...` / `/select/0/prometheus/...` соответствует tenant 0; для tenant 1 — `/insert/1/...`. Через vmauth можно раздать разным пользователям разные тенанты:

```yaml
users:
  - username: team-a
    password: pa
    url_prefix: [http://vminsert:8480/insert/0/, http://vmselect:8481/select/0/]
  - username: team-b
    password: pb
    url_prefix: [http://vminsert:8480/insert/1/, http://vmselect:8481/select/1/]
```

### 3. Живая перезагрузка конфига

- Рестарт не требуется: `kill -HUP <pid>` или флаг `-auth.configCheckInterval=10s` перечитывает конфиг. 
- Универсальные флаги: `-auth.config`, `-httpListenAddr=:8427`, `-httpAuth.username`/`-httpAuth.password` (защита самого vmauth), `-tls`, `-tlsCertFile`, `-tlsKeyFile`, `-tlsMinVersion`.

## Валидация установки

```bash
# Статус и версия
curl -s http://localhost:8427/-/healthy

# Ошибки маршрутизации
curl -s http://localhost:8427/metrics | grep -E "^vmauth_request_errors_total"
# → vmauth_request_errors_total{...} 0

# Счётчики по пользователям
curl -s http://localhost:8427/metrics | grep -E "^vmauth_user_requests_total"
```

## Поиск и устранение неисправностей

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| `401 Unauthorized` | Нет совпадения пользователя/токена | Проверить `users[]` и используемый метод авторизации (Basic/Bearer/OIDC) |
| `404` при попадании на неправильный бекенд | `src_paths` не совпало, нет `default_url` | Добавить `default_url` или скорректировать регекспы путей |
| Слишком длинный путь у бекенда | `url_prefix` задвоил сегменты пути | Использовать `drop_src_path_prefix_parts` |
| Ретраи только на одном бекенде | `retry_status_codes` не настроены | Добавить `[429, 502, 503]` |

## Рекомендации по эксплуатации

- Всегда ставьте vmauth перед vminsert/vmselect, если к ним обращается больше одного клиента: это упрощает управление доступом и балансировку.
- Используйте `load_balancing_policy: least_loaded` по умолчанию; `first_available` — только когда важна предсказуемость при малом числе реплик.
- Настроки ретраев увязывайте с `idempotent`-эндпоинтами (write) — для отказоустойчивой записи включайте ретраи и на стороне vmagent (`-remoteWrite*`).
- Для OIDC и mTLS-сценариев используйте Enterprise-версию vmauth (поддержка mTLS между компонентами кластера).

## Ограничения и особые случаи

- Каждый запрос в `users[]` сравнивается только с первым совпавшим пользователем — порядок важен.
- Без `unauthorized_user` и без совпадения пользователя запрос отклоняется.
- vmauth не является полноценным WAF или токен-хранилищем (не хранит сессии); за OIDC-флоу отвечает отдельный провайдер.

## Дополнительная информация

### См. также

- [VictoriaMetrics: обзор](./overview.md) — компоненты стека и роли vmauth;
- [VictoriaLogs: мульти-тенантность и доступ](./victorialogs_internals.md);
- [vmalert: интеграция источников](./vmalert_overview.md).
# force reindex test
