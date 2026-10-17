# vmauth: прокси аутентификации и маршрутизации

**Актуально для:** VictoriaMetrics v1.154.x (Community) / v1.148.x (LTS)

## Определения

**vmauth** — лёгкий reverse proxy из экосистемы VictoriaMetrics: аутентифицирует запросы (Basic Auth, Bearer token, JWT, OIDC, mTLS) и маршрутизирует их на backend-компоненты (vminsert, vmselect, vmsingle, VictoriaLogs, VictoriaTraces и др.) по пути запроса и правам пользователя. По умолчанию слушает порт `8427`.

**url_prefix** — список backend-адресов, на которые vmauth распределяет трафик пользователя (один запрос → один из бекендов).

**url_map / src_paths** — набор правил маршрутизации по префиксам/регекспам пути запроса (например, `/api/v1/query*` → vmselect, `/select/logsql/*` → VictoriaLogs).

**load_balancing_policy** — стратегия выбора бекенда: `least_loaded` (по умолчанию, балансирует по числу активных запросов) или `first_available` (первый здоровый).

**url_map** — блок маршрутизации внутри записи пользователя, содержащий `src_paths` и/или другие `src_*` условия, `url_prefix`, а также дополнительные опции (`deny_paths`, `drop_src_path_prefix_parts`, `retry_status_codes`, `load_balancing_policy`).

**unauthorized_user** — верхнеуровневый блок конфигурации для запросов без аутентификации (без `Authorization`-заголовка). Если отсутствует — такие запросы отклоняются с `401 Unauthorized`.

**JWT claim matching** — маршрутизация по заявкам (claims) внутри JWT-токена (доступно с v1.138.0 в Community).

**JWT claim templating** — динамическая подстановка значений из JWT-заявки `vm_access` в URL и заголовки backend-запроса (доступно с v1.137.0 в Community).

**mTLS-based routing** — маршрутизация по полям субъекта клиентского TLS-сертификата (OU, O, CN). Требует Enterprise-версии vmauth.

**ip_filters** — ограничение доступа по IP (CIDR и отдельные адреса). Требует Enterprise-версии vmauth.

## Базовые концепции

### Место в стеке

```
         │
  клиенты (dashboards, vmagent, vmalert, curl, vmselect)
         │
         ▼
    ┌─────────┐
    │  vmauth │   аутентификация + маршрутизация (8427)
    └────┬────┘
         │ (по пути / хосту / заголовку / query arg)
     ┌───┴─────┬────────────┐
     ▼         ▼            ▼
  vmselect   vminsert   VictoriaLogs
  (запросы)  (запись)   (логи/трейсы)
```

Типовые применения:
- **Единая точка входа** — клиенты обращаются к одному адресу `vmauth:8427` вместо прямого доступа к каждому backend-компоненту.
- **Мульти-тенантность** — маршрут по `X-Scope-OrgID` или префиксу пути `/select/0/...`. Tenant = `accountID:projectID`.
- **Ограничение прав** — разные учётные записи получают доступ к разным бекендам и тенантам.
- **Балансировка и фейловер** — `url_prefix` со списком адресов распределяет нагрузку и автоматически переключается на доступные бекенды.

### Принцип работы

vmauth обрабатывает каждый запрос по следующей схеме:

1. **Аутентификация** — извлекает токен из `Authorization`-заголовка или из другого заголовка (через `-httpAuthHeader`). Поддерживаемые методы: Basic Auth (`username`/`password`), Bearer token, `auth_token` (произвольный префикс токена, например `Authorization: Api-Key XXXX`), JWT (RSA/ECDSA + OIDC Discovery), mTLS-сертификат (Enterprise).
2. **Сопоставление пользователя** — перебирает блоки `users[]` до первого совпадения. Для JWT-пользователей дополнительно проверяются `match_claims` (claims в токене). Если ни один пользователь не подошёл — используется блок `unauthorized_user` (если задан).
3. **Маршрутизация** — внутри подходящего блока применяется `url_map` (если есть) или `url_prefix`. Выбирается первый `url_map`-элемент, чьи условия (`src_paths`, `src_hosts`, `src_query_args`, `src_headers`) совпали. Если ни одно правило не совпало — используется `default_url` или запрос отклоняется.
4. **Проксирование** — запрос пересылается на выбранный backend с учётом `drop_src_path_prefix_parts`, `headers`, `response_headers`, `retry_status_codes` и `load_balancing_policy`.

### Конфигурационный файл

Основной файл конфигурации указывается флагом `-auth.config`. Формат — YAML.

```yaml
# /etc/victoriametrics/vmauth.yml
# ── Базовая конфигурация: пользователи с паролями ──
users:
  - username: monitoring      # Basic Auth
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
    url_map:
      - src_paths: ["/api/v1/write"]
        url_prefix: http://vminsert:8480/insert/0/prometheus/
      - src_paths: ["/api/v1/query", "/api/v1/query_range"]
        url_prefix: http://vmselect:8481/select/0/prometheus/

  - bearer_token: "s3cr3t"    # токен вместо пароля
    url_prefix: http://vmsingle:8428/

  - auth_token: "Api-Key 12345"   # произвольный токен (Authorization: Api-Key 12345)
    url_prefix: http://vmsingle:8428/

  - username: outro
    password: outro
    ip_filters:              # Enterprise-сборка
      allow_list: [10.0.0.0/8, "172.16.0.0/12"]
      deny_list: ["10.0.0.3"]
      real_ip_header: X-Forwarded-For   # если vmauth за reverse proxy

# ── Анонимный доступ (без аутентификации) ──
unauthorized_user:
  url_prefix: http://vmselect:8481/select/0/prometheus/
```

**Ключи конфигурации:**

| Ключ | Описание |
| :--- | :--- |
| `users[]` | Список учётных записей. У каждой может быть `username`/`password`, `bearer_token`, `auth_token`, `jwt` или Enterprise-конфигурация `mtls`. Правила применяются по **первому совпадению**. |
| `bearer_token` | Токен для проверки заголовка `Authorization: Bearer <token>`. |
| `auth_token` | Произвольная строка для проверки заголовка `Authorization: <auth_token>`. Позволяет использовать нестандартные схемы (`Api-Key`, `Token` и т.п.). |
| `jwt` | Блок JWT-аутентификации: `public_keys`/`public_key_files` или `oidc.issuer`, необязательно `skip_verify`, `match_claims`, `default_vm_access_claim`, `proxy_cookie_authorization_token`. |
| `url_prefix` | URL или список URL бекендов. При списке — балансировка нагрузки. |
| `url_map[]` | Правила маршрутизации по `src_paths`, `src_hosts`, `src_query_args`, `src_headers`. Только первый совпадающий элемент применяется. |
| `src_paths` | Regex-паттерны пути запроса. |
| `src_hosts` | Regex-паттерны заголовка `Host`. |
| `src_query_args` | Условия на query-параметры: `arg=value` (exact) или `arg=~regex`. |
| `src_headers` | Условия на HTTP-заголовки: `"Header: value"`. |
| `deny_paths` | Regex-пути, которые **отклоняются** (403/401), внутри уже выбранного `url_map` элемента. |
| `drop_src_path_prefix_parts` | Удаляет N компонентов пути (через `/`) перед передачей на бекенд. |
| `default_url` | Маршрут по умолчанию для запросов без совпадения по `url_map`. |
| `headers` | Дополнительные заголовки запроса к бекенду (например, `Authorization`). |
| `response_headers` | Заголовки ответа клиенту (добавление или удаление при пустом значении). |
| `retry_status_codes` | HTTP-коды, после которых vmauth ретраит запрос на следующем бекенде из `url_prefix`. |
| `max_concurrent_requests` | Пер-юзерный лимит одновременных запросов (429 при превышении). |
| `discover_backend_ips` | Автоматически обнаруживает IP за hostname и балансирует по ним. |
| `tls_insecure_skip_verify` | Пропуск проверки TLS сертификата бекенда. |
| `tls_ca_file` / `tls_cert_file` / `tls_key_file` | Пути к CA, клиентскому сертификату и ключу для бекендов. |
| `tls_server_name` | TLS ServerName для бекенда. |
| `access_log` | Логирование запросов пользователя (v1.138.0). Поддерживает `filters.skip_status_codes` и `headers` (v1.153.0). |
| `metric_labels` | Дополнительные метки для per-user метрик (например, `dc: eu`, `team: dev`). |
| `name` | Переопределяет значение `username` в метках метрик. |
| `ip_filters` | Enterprise: `allow_list`/`deny_list` (CIDR), `real_ip_header`. |
| `mtls` | Enterprise: `organizational_unit`/`organization`/`common_name` — маршрутизация по сертификату клиента. |

## Установка и настройка

### Требования

- **ОС:** любая, поддерживаемая Go (Linux, FreeBSD, macOS для dev).
- **Архитектура:** amd64, arm64, armv5–v7, 386 (в зависимости от билета).
- **Порт:** 8427 по умолчанию (изменяется `-httpListenAddr`).
- **Доступ к backend-компонентам:** vmauth должен разрешать исходящие соединения к vminsert/vmselect/VictoriaLogs/VictoriaTraces.
- **TLS-сертификаты:** если включён `-tls`, нужны `cert` и `key` файлы.
- **OIDC/JWT:** доступ к OIDC provider (Discovery endpoint) или путь к публичным ключам.
- **IP-фильтры, mTLS:** требуется Enterprise-лицензия.

### Запуск

**Docker / Docker Compose:**

```bash
docker run -d \
  --name vmauth \
  -p 8427:8427 \
  -v /path/to/vmauth.yml:/etc/victoriametrics/vmauth.yml \
  victoriametrics/vmauth:v1.154.0 \
  -auth.config=/etc/victoriametrics/vmauth.yml \
  -maxConcurrentRequests=1000
```

**Бинарник (из vmutils-* архива):**

```bash
# Скачать последний релиз с https://github.com/VictoriaMetrics/VictoriaMetrics/releases
/path/to/vmauth -auth.config=/etc/victoriametrics/vmauth.yml -httpListenAddr=:8427
```

**Самостоятельная сборка:**

```bash
# Требуется Go
make vmauth              # dev-сборка → bin/vmauth
make vmauth-prod         # production-сборка → bin/vmauth-prod
make package-vmauth      # Docker image: victoriametrics/vmauth:<PKG_TAG>
```

### Флаги командной строки

| Флаг | Описание |
| :--- | :--- |
| `-auth.config` | Путь к YAML-файлу конфигурации аутентификации. |
| `-httpListenAddr` | Адрес прослушивания (по умолчанию `:8427`). |
| `-configCheckInterval` | Интервал автоматической проверки обновлений конфига. |
| `-tls` / `-tlsCertFile` / `-tlsKeyFile` | Включение HTTPS на порту vmauth. |
| `-tlsMinVersion` | Минимальная версия TLS (TLS12, TLS13). |
| `-mtls` / `-mtlsCAFile` | Enterprise: включение mTLS на порту vmauth. |
| `-maxConcurrentRequests` | Глобальный лимит одновременных запросов. |
| `-maxConcurrentPerUserRequests` | Лимит одновременных запросов на пользователя. |
| `-retryStatusCodes` | Глобальный список HTTP-кодов для ретраев. |
| `-loadBalancingPolicy` | `least_loaded` (default) или `first_available`. |
| `-backend.tls*` | TLS-настройки для backend-соединений. |
| `-httpAuthHeader` | Заголовок для чтения auth-токена (по умолчанию `Authorization`). |
| `-httpAuth.username` / `-httpAuth.password` | Basic Auth для самого vmauth. |
| `-reloadAuthKey` / `-flagsAuthKey` / `-metricsAuthKey` | AuthKey для защиты `/-/reload`, `/flags`, `/metrics`. |
| `-httpRealIPHeader` | Заголовок с клиентским IP (для IP-фильтров за reverse proxy). |
| `-discoverBackendIPs` | Глобально включить обнаружение IP за hostname. |
| `-requestBufferSize` | Размер буфера тела запроса для буферизации (v1.135.0). |
| `-maxQueueDuration` | Таймаут буферизации тела запроса. |

## Операции и команды

### Перезагрузка конфига

Конфиг перечитывается без перезапуска:
- Сигнал `kill -HUP $(pidof vmauth)`
- HTTP GET `http://vmauth:8427/-/reload` — рекомендуется защищать флагом `-reloadAuthKey`
- Автоматически через `-configCheckInterval=10s`

### Защита endpoint'ов

Служебные endpoint'ы рекомендуется защищать AuthKey:
- `/-/reload` → `-reloadAuthKey`
- `/flags` → `-flagsAuthKey`
- `/metrics` → `-metricsAuthKey`

## Мониторинг

vmauth экспортирует метрики в формате Prometheus на `/metrics`. Рекомендуется скрейпировать через vmagent или Prometheus.

**Общие метрики:**

| Метрика | Тип | Описание |
| :--- | :--- | :--- |
| `vm_http_request_errors_total` | counter | Ошибки HTTP (с `reason` label). |
| `vmauth_http_request_errors_total` | counter | Ошибки HTTP и аутентификации (с `reason` label: `invalid_auth_token`, `reject_slow_client` и др.). |
| `vmauth_concurrent_requests_current` | gauge | Текущее число одновременных запросов. |
| `vmauth_concurrent_requests_capacity` | gauge | Глобальный лимит одновременных запросов. |
| `vmauth_concurrent_requests_limit_reached_total` | counter | Количество запросов, отклонённых с 429. |
| `vmauth_buffer_request_body_duration_seconds` | summary | Длительность буферизации тела запроса (v1.135.0). |

**Per-user метрики** (метка `username`):

| Метрика | Тип | Описание |
| :--- | :--- | :--- |
| `vmauth_user_requests_total` | counter | Количество запросов для пользователя. |
| `vmauth_user_request_errors_total` | counter | Ошибки запросов для пользователя. |
| `vmauth_user_request_backend_requests_total` | counter | Количество запросов к backend. |
| `vmauth_user_request_backend_errors_total` | counter | Ошибки backend-запросов. |
| `vmauth_user_request_duration_seconds` | summary | Длительность запросов. |
| `vmauth_user_concurrent_requests_capacity` | gauge | Лимит одновременных запросов для пользователя. |
| `vmauth_user_concurrent_requests_current` | gauge | Текущее число одновременных запросов. |
| `vmauth_user_concurrent_requests_limit_reached_total` | counter | Количество запросов с 429 для пользователя. |

**Метрики для unauthorized_user** (префикс `vmauth_unauthorized_user_*`).

Пер-юзерные метрики по умолчанию содержат метку `username` — значение поля `username` из конфигурации. Значение можно переопределить через поле `name`. Дополнительные метки задаются через `metric_labels`.

**Алерты для SRE (PromQL):**

```promql
# Частка запросов с 429 (перегрузка)
rate(vmauth_concurrent_requests_limit_reached_total[5m]) / rate(vmauth_user_requests_total[5m]) > 0.05

# Ошибки маршрутизации выше порога
rate(vmauth_http_request_errors_total[5m]) > 0
```

### Валидация установки

```bash
# Статус и готовность
curl -s http://localhost:8427/-/healthy
# → OK

# Версия
curl -s http://localhost:8427/build_info
# → {"build_version":"vmauth..."}

# Метрики vmauth
curl -s http://localhost:8427/metrics | grep -E "^vmauth_http_request_errors_total"
# → vmauth_http_request_errors_total{...} 0

curl -s http://localhost:8427/metrics | grep -E "^vmauth_user_requests_total"
# → vmauth_user_requests_total{username="..."} N

# Проверка аутентификации
curl -s -u monitoring:secret http://localhost:8427/api/v1/query?query=1
# → ответ от vmselect
```

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

Путь `/insert/0/prometheus/...` / `/select/0/prometheus/...` соответствует tenant 0 (`accountID=0`, `projectID=0`); для tenant 1 — `/insert/1/...`. Через vmauth можно раздать разным пользователям разные тенанты:

```yaml
users:
  - username: team-a
    password: pa
    url_prefix: [http://vminsert:8480/insert/0/, http://vmselect:8481/select/0/]
  - username: team-b
    password: pb
    url_prefix: [http://vminsert:8480/insert/1/, http://vmselect:8485/select/1/]
```

### 3. JWT с роутингом по claims (RBAC через токен)

Доступно с v1.138.0 в Community. Роутинг по заявкам токена позволяет маппить роли на разные бекенды:

```yaml
users:
  - jwt:
      public_keys:
        - |
          -----BEGIN PUBLIC KEY-----
          MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA...
          -----END PUBLIC KEY-----
      match_claims:
        role: admin
    url_prefix: "http://victoria-metrics-admin:8428/"

  - jwt:
      public_keys:
        - |
          -----BEGIN PUBLIC KEY-----
          MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA...
          -----END PUBLIC KEY-----
      match_claims:
        role: viewer
    url_prefix: "http://victoria-metrics-readonly:8428/"
```

Если несколько пользователей совпадают — выбирается тот, у кого **больше** `match_claims` записей. При равенстве количества записей выбор становится неопределённым — избегайте этого делая условия взаимно-исключающими.

### 4. JWT claim templating (динамическая подстановка tenant)

Доступно с v1.137.0 в Community. Значения из `vm_access` заявки подставляются в URL и заголовки:

```yaml
users:
  - jwt:
      public_keys:
        - |
          -----BEGIN PUBLIC KEY-----
          MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA...
          -----END PUBLIC KEY-----
  url_map:
    - src_paths: ["/api/v1/write"]
      url_prefix: "http://vminsert:8480/insert/{{.MetricsTenant}}/prometheus/"
    - src_paths: ["/api/v1/query", "/api/v1/query_range"]
      url_prefix: "http://vmselect:8481/select/{{.MetricsTenant}}/prometheus/"
```

Поддерживаемые placeholders: `{{.MetricsAccountID}}`, `{{.MetricsProjectID}}`, `{{.MetricsTenant}}`, `{{.MetricsExtraLabels}}`, `{{.MetricsExtraFilters}}`, `{{.LogsAccountID}}`, `{{.LogsProjectID}}`, `{{.LogsExtraFilters}}`, `{{.LogsExtraStreamFilters}}`.

Placeholders работают **только для JWT-пользователей**. Для токенов без `vm_access` можно задать `default_vm_access_claim` (v1.147.0).

### 5. OIDC Discovery (автоматическая ротация ключей)

Доступно с v1.138.0 в Community. vmauth автоматически запрашивает JWKS у OIDC provider и обновляет ключи каждые 5 минут:

```yaml
users:
  - jwt:
      oidc:
        issuer: "https://your-identity-provider.example.com"
      match_claims:
        aud: "theClientID"
    url_prefix: "http://victoria-metrics:8428/"
```

### 6. Single sign-on (SSO)

Доступно с v1.153.0 в Community. Реализует Authorization Code Flow: при запросе без токена показывается страница входа, пользователь перенаправляется к IdP, затем обратно с ID token в cookie-сессии:

```yaml
sso:
  - src_host: 'sso\.example\.com'
    oidc:
      issuer: 'https://identity-provider.com/realms/master'
      client_id: 'sso.example.com'
      client_secret: 'theClientSecret'
      cookie_secret: 'theCookieSecret1234567890'   # ≥16 символов, openssl rand -base64 32
      scopes: ['openid', 'profile', 'email']
      session_duration: '1h'

users:
  - jwt:
      match_claims:
        iss: 'https://identity-provider.com/realms/master'
        aud: 'sso.example.com'
      oidc:
        issuer: 'https://identity-provider.com/realms/master'
    url_map:
      - src_paths: ["/.*"]
        src_hosts: ['sso\.example\.com']
        url_prefix: "http://vmsingle:8428"
```

**Redirect URI в IdP:** `https://<vmauth-host>/_vmauth/sso/callback`. При `-http.pathPrefix=/metrics` → `/metrics/_vmauth/sso/callback`.

### 7. IP-фильтры (Enterprise)

```yaml
users:
  - username: "foobar"
    password: "***"
    url_prefix: "http://localhost:8428"
    ip_filters:
      allow_list: [127.0.0.1]
      real_ip_header: X-Forwarded-For   # за reverse proxy
```

Глобальные IP-фильтры задаются верхнеуровневым блоком `ip_filters`.

### 8. mTLS-based routing (Enterprise)

Маршрутизация по полям клиентского сертификата (OU, O, CN):

```yaml
users:
  - mtls:
      organizational_unit: finance
    url_prefix: "http://victoriametrics-finance:8428"
  - mtls:
      organizational_unit: devops
    url_prefix: "http://victoriametrics-devops:8428"
```

Для включения mTLS на порту vmauth: `./vmauth -tls -mtls -mtlsCAFile=/path/to/ca.pem`.

## Поиск и устранение неисправностей

### Типовые ошибки

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| `401 Unauthorized` | Нет совпадения пользователя/токена | Проверить `users[]` и метод авторизации (Basic/Bearer/JWT/OIDC); убедиться, что `Authorization`-заголовок корректный |
| `404` на бекенде | `src_paths` не совпало, нет `default_url` | Добавить `default_url` или скорректировать регекспы; проверить `drop_src_path_prefix_parts` |
| `403 Forbidden` | `deny_paths` отклонил путь | Проверить `deny_paths` в соответствующем `url_map` элементе |
| Дублирование сегментов пути | `url_prefix` задвоил сегменты пути | Использовать `drop_src_path_prefix_parts: N` |
| Ретраи только на одном бекенде | `retry_status_codes` не настроены | Добавить `[429, 500, 502, 503]`; для глобального — `-retryStatusCodes` |
| `429 Too Many Requests` | Превышен `max_concurrent_requests` или `-maxConcurrentRequests` | Увеличить лимиты; проверить `vmauth_concurrent_requests_limit_reached_total` |
| OIDC-ключи не обновляются | IdP недоступен | vmauth продолжает использовать кеш; проверить сеть к Discovery endpoint |
| Доступ по IP не работает за reverse proxy | IP-фильтр видит IP прокси | Установить `real_ip_header: X-Forwarded-For` или `-httpRealIPHeader` |
| JWT templating не работает | Placeholders в `username`/`password` пользователе (не JWT) | Использовать только в блоках `jwt` |

### Диагностика

```bash
# Логи vmauth (stdout / journalctl)
journalctl -u vmauth -f

# Метрики: ошибки маршрутизации
curl -s http://localhost:8427/metrics | grep -E "vmauth_http_request_errors_total"

# Метрики: нагрузка по пользователям
curl -s http://localhost:8427/metrics | grep -E "vmauth_user_request"

# Метрики: превышение лимитов конкурентности
curl -s http://localhost:8427/metrics | grep -E "limit_reached"

# Debug: логировать неудавшиеся запросы
# dump_request_on_errors: true  в user-конфиге (v1.107.0)
```

## Рекомендации по эксплуатации

- **Ставьте vmauth перед vminsert/vmselect**, если к ним обращается более одного клиента: упрощает управление доступом и балансировку.
- **Используйте `load_balancing_policy: least_loaded`** по умолчанию; `first_available` — только для предсказуемого failover при малом числе реплик.
- **Ретраи для записи:** настраивайте `retry_status_codes` на idempotent-эндпоинтах (write); для отказоустойчивой записи также включайте ретраи на стороне vmagent (`-remoteWrite*`).
- **Per-user лимиты:** задавайте `max_concurrent_requests` для тяжёлых тенантов, чтобы защитить остальных пользователей от «пиратской» нагрузки.
- **IP-фильтры за reverse proxy:** используйте `real_ip_header` и `-httpRealIPHeader`, иначе фильтры видят IP proxy, а не клиента.
- **TLS на периметре:** всегда включайте `-tls` наружу; для mTLS между vmauth и backend используйте `-backend.tls*`.
- **Не храните пароли в конфиге в plaintext в продакшене:** используйте JWT/OIDC или секреты через `auth_token`.
- **Access log:** включайте для аудита (v1.138.0+); используйте `skip_status_codes` для фильтрации шума.
- **Скейлинг:** vmauth stateless — множите реплики за L4-LB без согласования состояния.
- **JWT vs vmgateway:** vmauth поддерживает JWT/OIDC в Community; для tenant-ACL и rate limiting (RPS) используйте vmgateway (Enterprise).

## Ограничения и особые случаи

- **Порядок пользователей важен:** каждый запрос сравнивается только с первым совпавшим пользователем.
- **Без `unauthorized_user` запрос без токена отклоняется** с `401`.
- **JWT authentication не комбинируется** с другими методами (bearer_token, username, password) в одном пользователе.
- **JWT templating работает только для JWT-пользователей**; использование placeholders в `username`/`password` вызовет ошибку конфигурации.
- **vmauth — не WAF:** не хранит пароли пользователей, не выполняет deep inspection payload. За выдачу JWT отвечает внешний IdP (OIDC); начиная с v1.153.0 страница входа и cookie-сессия реализованы внутри vmauth (SSO).
- **IP-фильтры (`ip_filters`), mTLS-based routing, mTLS protection** — Только Enterprise.
- **RPS rate limiting отсутствует** в vmauth — для этого используется vmgateway (Enterprise).
- **Глобальный retry `-retryStatusCodes`** применяется ко всем запросам, включая небезопасные; используйте per-user `retry_status_codes` для точного контроля.
- **Conflict resolution при JWT matching:** если несколько пользователей имеют одинаковое число `match_claims`-записей и оба совпадают — выбор неопределён.

## Дополнительная информация

### См. также

- [VictoriaMetrics: обзор](./overview.md) — компоненты стека и роли vmauth (кратко);
- [VictoriaMetrics: безопасность](./security.md) — модель угроз, exposure matrix, флаги защиты;
- [VictoriaMetrics: Enterprise-функции](./enterprise_features.md) — mTLS, vmgateway, rate limiting;
- [VictoriaLogs: мульти-тенантность и доступ](./victorialogs_internals.md) — vmauth перед VictoriaLogs;
- [vmalert: обзор](./vmalert_overview.md) — интеграция источников через vmauth;
- [Управление правилами vmalert в Kubernetes](./vmalert_rules_management_with_manifests.md) — VMUser CRD с `routes`/`path_prefix` (формат Operator, отличный от raw `vmauth.yml`).

**Примечание:** в `vmalert_rules_management_with_manifests.md` используется формат `routes`/`path_prefix`/`url` — это синтаксис CRD `VMUser` оператора VictoriaMetrics, который автоматически транслируется в `users`/`url_map`/`src_paths` конфиг vmauth.
