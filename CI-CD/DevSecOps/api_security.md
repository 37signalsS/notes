# Безопасность API

**Актуально для:** OWASP API Security Top 10 (2023)

## Определения

**API (Application Programming Interface)** — программный интерфейс, через который сервисы обмениваются данными. В современных архитектурах (микросервисы, мобильные бэкенды, партнёрские интеграции) API становится основной поверхностью атаки, поэтому его защита выделяется в отдельный домен DevSecOps.

**OWASP API Security Top 10 (2023)** — актуальный стандарт, описывающий критичные риски именно для API: слабая авторизация на уровне объектов, excessive data exposure, отсутствие throttling, небезопасная работа с ресурсами и др. В продакшене эти риски проверяются отдельно от классического OWASP Top 10 (2021), потому что многие уязвимости проявляются по-другому при отсутствии браузерного контекста.

**BOLA/IDOR (Broken Object Level Authorization / Insecure Direct Object Reference)** — класс уязвимостей, при котором клиент может обратиться к объекту другого пользователя, меняя только идентификатор в пути или теле запроса. В API это самый частый вектор атаки, потому что объекты обычно адресуются через predictable IDs (`/api/orders/1001`, `/api/users/42`).

**BFLA (Broken Function Level Authorization)** — обход проверки прав на уровне функций/операций. Например, обычный пользователь получает доступ к административному эндпоинту `/api/admin/users`, который не был защищён отдельной проверкой.

**OpenAPI Specification (OAS)** — стандартное описание REST/GraphQL API в формате YAML/JSON. Используется как источник истины для автоматического тестирования безопасности, генерации клиентов и сканирования.

## Базовые концепции

### Классы уязвимостей OWASP API Security Top 10 (2023)

| № | Категория | Суть | Типичный последствия |
| :--- | :--- | :--- | :--- |
| **A01:2023** | BOLA/IDOR | Недостаточная проверка прав на уровне объекта | Чтение/изменение чужих данных |
| **A02:2023** | Broken Authentication | Слабые механизмы аутентификации, утечка токенов | Учётная запись злоумышленника, подмена identity |
| **A03:2023** | Broken Object Property Authorization | Слишком широкий доступ к полям объекта | Утечка PII, секретов, бизнес-данных |
| **A04:2023** | Unrestricted Resource Consumption | Отсутствие throttling/quotas | DoS, exhausting пула соединений, рост счёта |
| **A05:2023** | BFLA | Отсутствие проверки прав на уровне функции | Выполнение административных операций |
| **A06:2023** | Unrestricted Access to Sensitive Business Flows | Отсутствие защиты бизнес-логики | Обход лимитов, фрод, массовая выгрузка |
| **A07:2023** | Server-Side Request Forgery (SSRF) | API выполняет произвольные запросы от имени сервера | Доступ к внутренним сервисам, облачным метаданным |
| **A08:2023** | Unsafe Consumption of APIs | Небезопасное взаимодействие с внешними API | Цепочка атак через доверенные интеграции |
| **A09:2023** | Improper Assets Management | Устаревшие/неучтённые версии API | Атака на забытые эндпоинты, exposure данных |
| **A10:2023** | Unsafe API Consumption | Клиенты trust ответ без верификации | MITM, подмена данных, deserialization |

### Модели авторизации для API

**RBAC (Role-Based Access Control)** — доступ по ролям. Просто в использовании, но не покрывает гранулярные сценарии, когда один пользователь имеет доступ только к своим объектам.

**ABAC (Attribute-Based Access Control)** — доступ по атрибутам (пользователь, ресурс, действие, контекст). Покрывает сложные правила: `department == requester.department && resource.sensitivity <= requester.clearance`.

**ReBAC (Relationship-Based Access Control)** — доступ по отношениям между объектами. Например, пользователь может читать заказ только если он является `owner` или `admin` связанного `tenant`.

**ACL (Access Control List)** — явный список разрешений на объект. Хорошо работает для ресурсов с небольшим числом субъектов, но плохо масштабируется в многопользовательских системах.

### Режимы аутентификации

| Механизм | Применение | Рекомендации |
| :--- | :--- | :--- |
| **API Key** | Сервис-to-сервис, простые интеграции | Никогда не передавать в query string; хранить в заголовке `X-API-Key` или `Authorization: ApiKey` |
| **Bearer JWT** | Микросервисы, мобильные приложения | Короткий TTL access token + refresh token; подпись через RS256; проверка `aud`, `iss`, `exp` |
| **mTLS** | Внутренние сервисы, zero-trust | Взаимная аутентификация на уровне TLS;Rotation сертификатов через Vault/SPIFFE |
| **OAuth 2.0 / OIDC** | Пользовательские приложения, SSO | Authorization Code Flow + PKCE для public clients; scope гранулярные |
| **Basic Auth** | Внутренние tools, мониторинг | Только по HTTPS; запрещён в продакшене для пользовательских потоков |

### Защита на уровнях сети и приложения

**Rate limiting / throttling** — ограничение числа запросов в единицу времени на пользователя, IP или токен. Защищает от DoS, brute force и истощения ресурсов. Реализуется на уровне API Gateway (Kong, Envoy, AWS API Gateway), service mesh (Istio) или приложения (middleware).

**CORS (Cross-Origin Resource Sharing)** — механизм браузера, ограничивающий, с каких origins можно обращаться к API. Небезопасная конфигурация (`Access-Control-Allow-Origin: *` с `credentials: true`) позволяет красть данные через XSS.

**Input validation** — проверка типа, диапазона, длины и формата всех входящих параметров. Покрывает инъекции, oversized payloads и malformed data, которые ломают парсеры.

**Output encoding / filtering** — исключение чувствительных полей из ответа (`password_hash`, `internal_id`, `credit_card`). Поле `fields` или `views` позволяет клиенту запрашивать только нужные атрибуты.

## Архитектура API Security

### Модели защиты API

В продакшене API защищаются на нескольких уровнях defence-in-depth:

| Уровень | Инструмент | Функция |
| :--- | :--- | :--- |
| **Perimeter** | WAF/WAAP, DDoS-фильтры | Блокировка известных векторов на границе; виртуальный патчинг |
| **API Gateway** | Kong, Envoy, Apache APISIX, KrakenD | throttling, аутентификация, валидация контракта, роутинг |
| **Service mesh** | Istio, Linkerd | mTLS, authz на уровне эндпоинта, retry/timeout политики |
| **Application** | Middleware, RASP | Проверка прав на объект/функцию, input validation, output filtering |
| **Runtime** | Falco, eBPF-агенты | Обнаружение аномалий в вызываемом коде и системных вызовах |

### Положительная и отрицательная модели безопасности

**Отрицательная модель (Negative Security)** — блокирует только известные вредоносные паттерны. Реализуется WAF с сигнатурными правилами (ModSecurity CRS, Nuclei templates). Эффективна против массовых атак, но не защищает от Zero-day.

**Положительная модель (Positive Security)** — разрешает только то, что явно описано в OpenAPI-спецификации: методы, параметры, схемы ответов. Все отклонения блокируются. Требует актуальной спецификации, но даёт максимальную защиту от неизвестных угроз.

На практике используется комбинация: Gateway применяет положительную модель по OpenAPI, WAF — отрицательную по сигнатурам, приложение — контекстную авторизацию.

### Жизненный цикл API в контексте безопасности

1. **Design:** Threat Modeling для каждого эндпоинта (указание чувствительных полей, rate limit, scope).
2. **Contract:** OpenAPI-спецификация как источник истины для Gateway, DAST и клиентских SDK.
3. **Build:** SAST на BOLA/SSRF/unsafe deserialization; SCA зависимостей фреймворка.
4. **Deploy:** WAF/WAAP правила, mTLS между сервисами, Network Policies.
5. **Runtime:** DAST на staging, audit logging, аномалийный мониторинг, Falco/Tetragon для eBPF-обнаружения.
6. **Deprecate:** Удаление забытых версий API; обновление OpenAPI; перевыпуск клиентских credential'ов.

## Практические сценарии

### Пример 1: Сканирование API по спецификации OpenAPI в GitLab CI

```yaml
api_security_scan:
  stage: security
  image: ghcr.io/zaproxy/zaproxy-stable:latest
  variables:
    TARGET_API: "https://staging-api.example.com"
  script:
    # Сканирование на основе OpenAPI-спецификации
    - zap-api-scan.py -t $TARGET_API/openapi.yaml -f openapi \
        -r reports/zap-api.html -x reports/zap-api.xml -J reports/zap-api.json
    # Или через curl-спецификацию
    # - zap-api-scan.py -t $TARGET_API -f openapi30 -d openapi.json ...
  artifacts:
    paths: [reports/zap-api.html, reports/zap-api.xml, reports/zap-api.json]
    reports:
      sast: reports/zap-api.json
```

**Validation:** `zap-api.json` содержит список алертов по категориям; в консоли печатается сводка `high/medium/low`. При отсутствии уязвимостей — пустой или минимальный отчёт.

**Troubleshooting:**
- *Сканер не находит эндпоинты:* проверьте, что `servers` в OpenAPI совпадает с `TARGET_API`; для приватных сетей используйте флаг `-z "-config httpsender.useUnsafeSSLCertificates=true"` в доверенном контуре.
- *Аутентификация:* добавьте заголовок `-z "-config header.Authorization=Bearer $API_TOKEN"` или используйте `zap-hud.py` с session cookie.
- *Ложные срабатывания на бизнес-логику:* supplement DAST ручными сценариями или перейдите на IAST для точности.

### Пример 2: Авторское правило Semgrep для BOLA/IDOR

```yaml
rules:
  - id: api-bola-idor
    severity: ERROR
    languages: [python]
    message: "Прямой доступ к объекту по ID из запроса без проверки ownership"
    pattern: |
      def get_$X($request, $id):
        $obj = $Model.objects.get(id=$id)
        return $obj
    metadata:
      cwe: "CWE-639"
      category: security
      owasp: "A01:2023"
```

**Validation:** `semgrep scan --config rules/api-bola.yaml --sarif -o api.sarif` находит все эндпоинты, где объект загружается по ID из запроса без проверки `owner_id == request.user.id`.

### Пример 3: Rate limiting в Istio для API Gateway

```yaml
apiVersion: networking.istio.io/v1alpha3
kind: EnvoyFilter
metadata:
  name: api-rate-limit
  namespace: api-gateway
spec:
  workloadSelector:
    labels:
      app: api-gateway
  configPatches:
    - applyTo: HTTP_FILTER
      match:
        context: GATEWAY
        listener:
          filterChain:
            filter:
              name: "envoy.filters.network.http_connection_manager"
      patch:
        operation: INSERT_BEFORE
        value:
          name: envoy.filters.http.ratelimit
          typed_config:
            "@type": type.googleapis.com/ratelimit.solo.io.RateLimitConfig
            domain: api-gateway
            descriptors:
              - key: "remote_address"
                rate_limit:
                  unit: minute
                  requests: 100
```

**Validation:** `kubectl apply -f rate-limit.yaml`; проверка через `ab` или `wrk`: при превышении 100 запросов/минуту с одного IP возвращается `429 Too Many Requests`.

### Пример 4: Проверка безопасности GraphQL introspection

```bash
# 1. Отключить introspection в продакшене
curl -X POST https://api.example.com/graphql \
  -H "Content-Type: application/json" \
  -d '{"query": "{ __schema { types { name } } }"}'
# → ожидается: ошибка или пустой результат в продакшене

# 2. Сканирование через GraphQL-specific DAST
docker run --rm -v $PWD/reports:/zap/wrk owasp/zap2docker-stable \
  zap-api-scan.py -t https://api.example.com/graphql -f graphql \
  -z "-config graphql.introspection=true" \
  -r api-graphql.html -x api-graphql.xml
```

**Validation:** в продакшене introspection endpoint возвращает `400 Bad Request` или пустой результат; в staging полный скан выявляет информационные утечки через замыкания (N+1 queries, depth limit bypass).

### Пример 5: Защита API на хостовом уровне (Nginx + fail2ban)

На bare metal или VPS API-сервис часто exposed напрямую через Nginx. Базовый харденинг включает rate limiting на уровне ядра, валидацию размера тела и защиту от брутфорса.

```nginx
# /etc/nginx/conf.d/api-hardening.conf

# Ограничение соединений с одного IP
limit_conn_zone $binary_remote_addr zone=api_conn:10m;

# Ограничение запросов (token bucket: 10r/s с burst=20)
limit_req_zone $binary_remote_addr zone=api_limit:10m rate=10r/s;

# Ограничение размера тела (защита от oversized payloads)
client_max_body_size 1M;
client_body_timeout 10s;
client_header_timeout 10s;

server {
    listen 443 ssl http2;
    server_name api.example.com;

    # Security headers
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-Frame-Options "DENY" always;
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;

    location / {
        limit_conn api_conn 20;
        limit_req zone=api_limit burst=20 nodelay;
        limit_req_status 429;

        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

```bash
# fail2ban: защита от brute force на /auth/* эндпоинтах
# /etc/fail2ban/jail.local
[api-auth]
enabled = true
port = https
filter = api-auth
logpath = /var/log/nginx/api-access.log
maxretry = 5
bantime = 3600
findtime = 600

# /etc/fail2ban/filter.d/api-auth.conf
[Init]
failregex = ^<HOST> .* "(POST|GET) /api/v1/auth.*" (401|403) .*$
ignoreregex =
```

**Validation:** `nginx -t` — синтаксис корректен; `fail2ban-client status api-auth` показывает активные баны; при 6 запросах с `401` за 10 минут IP попадает в `iptables -L` с `REJECT`.

### Пример 6: Валидация OpenAPI-спецификации и contract testing

Спецификация должна быть валидна до использования в сканировании или Gateway:

```bash
# 1. Валидация через swagger-cli
npm install -g @apidevtools/swagger-cli
swagger-cli validate openapi.yaml
# → { "schema": "openapi-3.0.3", "valid": true }

# 2. Contract testing через Pact (Python пример)
# Установка: pip install pact-python
# Генерация consumer-теста:
from pact import Consumer, Provider

pact = Consumer('MobileApp').has_pact_with(Provider('API'))
pact.start_service()
(headers, body) = pact.given('user exists').upon_receiving(
    'a request for user'
).with_request('GET', '/api/v1/users/42').will_respond_with(
    200, body={'id': 42, 'email': pact.matcher.something()}
).verify()

pact.stop_service()
# → contract сохранён в pact/consumer-MobileApp-provider-API.json
```

**Validation:** `swagger-cli validate` возвращает `valid: true`; Pact-тест падает при несоответствии контракта (например, если бэкенд удаляет поле `email`).

## Установка и настройка инструментов

### Установка OWASP ZAP для локального сканирования API

```bash
# macOS (Homebrew)
brew install --cask owasp-zap

# Linux (Debian/Ubuntu)
sudo apt update && sudo apt install -y zaproxy

# Запуск в режиме демона с API
zap.sh -daemon -port 8080 -host 0.0.0.0 -config api.key=$ZAP_API_KEY
# → ZAP API доступен на http://localhost:8080
```

**Предусловия:** Java 11+; 2 ГБ RAM для головного сканирования; при активном сканировании API с аутентификацией — сессионные токены.

### Настройка fail2ban для защиты API

```bash
# 1. Установка
sudo apt install -y fail2ban

# 2. Создание фильтра для API
cat <<'EOF' | sudo tee /etc/fail2ban/filter.d/api-auth.conf
[Init]
failregex = ^<HOST> .* "(POST|GET) /api/.*" (401|403) .*$
ignoreregex =
EOF

# 3. Добавление jail
cat <<'EOF' | sudo tee -a /etc/fail2ban/jail.local
[api-bruteforce]
enabled = true
port = https
filter = api-auth
logpath = /var/log/nginx/api-access.log
maxretry = 5
bantime = 3600
findtime = 600
EOF

# 4. Перезапуск
sudo systemctl restart fail2ban
sudo fail2ban-client status api-bruteforce
# → Status: active, Currently banned: 0
```

**Validation:** `fail2ban-client status api-bruteforce` показывает jail активен; в `iptables -L` появляется цепочка `f2b-api-bruteforce`.

### ModSecurity для API на Nginx

```bash
# Debian/Ubuntu
sudo apt install -y libmodsecurity3 nginx-modsecurity

# Включение в серверном блоке:
server {
    listen 443 ssl;
    server_name api.example.com;

    modsecurity on;
    modsecurity_rules_file /etc/nginx/modsecurity/modsecurity.conf;
    modsecurity_rules_file /etc/nginx/modsecurity/crs-setup.conf;
    modsecurity_rules_file /etc/nginx/modsecurity/rules/*.conf;

    location / {
        proxy_pass http://127.0.0.1:8080;
    }
}
```

**Validation:** `nginx -t` — синтаксис корректен; при запросе с payload `../../etc/passwd` в параметре возвращается `403 Forbidden`; audit log в `/var/log/modsecurity/audit.log`.

## Граничные случаи и ограничения

### Внутренние API без OpenAPI-спецификации

Microservice-to-microservice эндпоинты внутри кластера часто не описаны в публичном OpenAPI. Для их защиты:
- Используйте **mTLS** на уровне service mesh (Istio PeerAuthentication) вместо Gateway throttling.
- Применяйте **Network Policies** для ограничения доступа к порту сервиса только определённым неймспейсам.
- Валидируйте внутренние контракты через **Pact** или **Schemathesis** в dedicated staging.

### Устаревшие версии API (API Sunset)

Забытые версии (`/v1/`, `/v2/`) часто остаются без защиты и мониторинга. Практики:
- В OpenAPI указывайте `deprecated: true` для устаревших операций.
- Настройте алерты на трафик к deprecated-версиям (Prometheus-метрика `http_requests_total{version="v1"}`).
- Ведите инвентаризацию API в API Catalog (Kong, Apigee, или внутренних spreadsheets).

### gRPC и WebSocket API

Классические DAST-сканеры работают с REST/JSON. Для gRPC и WebSocket:
- **gRPC:** используйте [ghz](https://ghz.sh/) для нагрузочного тестирования и [protostuff](https://github.com/protostuff) для фаззинга; валидируйте `.proto`-файлы через `buf lint`.
- **WebSocket:** ZAP поддерживает WebSocket через встроенный spider; Nuclei имеет шаблоны для WebSocket upgrade.
- Оба протокола требуют кастомных правил WAF, так как сигнатуры CRS ориентированы на HTTP-запросы.

### BOLA: ограничения автоматического детектирования

BOLA/IDOR — самая частая API-уязвимость, но автоматические сканеры (DAST, Semgrep) детектируют её не всегда:
- Требуется **минимум два аккаунта** (user A и user B) для перебора ID.
- Сложные Ownership-логики (tenant, department, status) не покрываются паттернами.
- **Рекомендация:** дополняйте SAST/DAST **ручными сценариями** или IAST (eBPF), который видит контекст запроса в рантайме.

## Оперативные команды

| Команда / Инструмент | Назначение | Ожидаемый результат |
| :--- | :--- | :--- |
| `zap-api-scan.py -t openapi.yaml -f openapi -r report.html` | Сканирование API по спецификации | HTML-отчёт с находками по OWASP API Top 10 |
| `zap-baseline.py -t https://api -r report.html` | Пассивный базовый скан | Быстрый отчёт по конфигурации и заголовкам |
| `nuclei -u https://api -severity critical,high -o nuclei.json` | Сканирование по шаблонам | JSON с CVE и misconfigurations |
| `semgrep scan --config p/api-security . --sarif -o api.sarif` | SAST для API-эндпоинтов | SARIF с BOLA/IDOR, SSRF, unsafe deserialization |
| `curl -I https://api` | Проверка заголовков безопасности | Наличие `Content-Security-Policy`, `X-Content-Type-Options`, отсутствие `X-Powered-By` |
| `jq '.Results[].Vulnerabilities[] | select(.Severity=="CRITICAL")' trivy-report.json` | Фильтрация критичных CVE в зависимостях API | Список критичных уязвимостей с фиксацией |

## Устранение неисправностей

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `zap-api-scan` не находит эндпоинты | OpenAPI-спецификация невалидна или `servers` не совпадает с target | Валидировать OAS через `swagger-cli validate`; явно передать target URL |
| CORS блокирует запросы из фронтенда | Неправильные `Access-Control-Allow-Origin` / `Allow-Credentials` | Настроить явный allowlist origins; запретить `*` с credentials |
| BOLA не детектируется сканерами | Требуется два разных аккаунта (user A и user B) | Запускать DAST с сессией обычного пользователя, затем с привилегированным |
| GraphQL introspection работает в продакшене | introspection отключен только на уровне фабрики запросов, но не на уровне сервера | Отключить на уровне `graphql-engine` (HashiCorp) или `Apollo Server` (`introspection: false`) |
| Rate limiting не срабатывает | Правила применяются к ingress, а запросы идут через другой порт/путь | Проверить `VirtualService` / `Gateway` в Istio; убедиться, что запросы проходят через Envoy |
| SSRF через API к внутренним сервисам | API выполняет пользовательские URL без валидации | Внедрить allowlist доменов; блокировать `http://169.254.169.254` и внутренние IP |

## Рекомендации

### Security by design для API

- **Авторизация по умолчанию:** каждый эндпоинт должен требовать явную проверку прав, а не inherit от родительского ресурса.
- **Гранулярные scope в OAuth:** `read:orders`, `write:profile`, а не общий `api` scope.
- **Обязательные заголовки:**
  - `Content-Security-Policy: default-src 'none'` для JSON-API
  - `X-Content-Type-Options: nosniff`
  - `Strict-Transport-Security: max-age=31536000; includeSubDomains`
  - `Cache-Control: no-store` для ответов с чувствительными данными
- **Правило минимального ответа:** API возвращает только запрошенные поля (`fields[]`) или предопределённые views; никогда — полный объект со всеми атрибутами.
- **Версионирование:** каждый breaking change в контракте безопасности — новая версия API (`/v2/`), чтобы не ломать существующих клиентов при изменении полей или авторизации.

### Тестирование безопасности API

- **Contract testing (Pact):** проверка контрактов между сервисами на предмет небезопасных полей.
- **DAST на каждом merge в main** для веток, затрагивающих auth/API surface.
- **SAST для контрактов:** Semgrep/CodeQL правила для BOLA/IDOR, SSRF, unsafe deserialization.
- **Fuzzing API:** параметрический фаззинг (ffuf, Postman/Newman + fuzzer) для неожиданных значений ID, headers, formats.
- **Penetration testing:** регулярные пентесты API на предмет бизнес-логики уязвимостей, которые не находят автоматические сканеры.

### Мониторинг и observability

- **Audit log:** каждый запрос фиксируется с `user_id`, `method`, `path`, `status`, `latency`, `user_agent`. Хранится 90–365 дней в зависимости от compliance.
- **Алерты на аномалии:** всплеск 401/403 (brute force), единовременный доступ к >1000 объектам (mass scraping), запросы к `/admin/*` из нестандартных источников.
- **Rate limit metrics:**Prometheus-метрики `rate_limit_hits_total`, `rate_limit_remaining`, экспортированные в Grafana.

### Чек-лист минимальной защищённости (Quick Reference)

- [ ] OpenAPI-спецификация валидна и актуальна
- [ ] Все эндпоинты требуют аутентификации по умолчанию
- [ ] RBAC/ABAC проверяется на уровне каждого объекта и функции
- [ ] Rate limiting настроен на уровне API Gateway / service mesh
- [ ] CORS настроен явным allowlist origins, без `*` с credentials
- [ ] Чувствительные поля исключаются из ответов по умолчанию
- [ ] Входные данные валидируются (тип, диапазон, длина)
- [ ] GraphQL introspection отключён в продакшене
- [ ] Заголовки безопасности установлены на все ответы
- [ ] Audit log включает user_id, method, path, status
- [ ] Алерты на 401/403 burst, массовый доступ к объектам, admin-пути из нестандартных источников

## Эксплуатация API с точки зрения Sysadmin/SRE

### Host-level защита API (Linux)

На хосте, где работает API-сервис (Nginx/Apache/приложение), критичны базовые механизмы Linux:

**iptables/nftables — rate limiting на уровне ядра:**

```bash
# iptables: ограничение 50 новых соединений в секунду с одного IP
iptables -A INPUT -p tcp --dport 443 -m state --state NEW \
  -m limit --limit 50/second --limit-burst 100 -j ACCEPT
iptables -A INPUT -p tcp --dport 443 -j DROP
```

```bash
# nftables (современная замена iptables):
table inet filter {
  chain input {
    type filter hook input priority 0; policy accept;
    tcp dport 443 limit rate 50/second burst 100 packets accept
    tcp dport 443 drop
  }
}
```

**SYN cookies и защита от SYN flood:**

```bash
# Включение SYN cookies
sysctl -w net.ipv4.tcp_syncookies=1
sysctl -w net.ipv4.tcp_synack_retries=2
sysctl -w net.ipv4.tcp_syn_retries=2

# Постоянное применение
echo "net.ipv4.tcp_syncookies = 1" >> /etc/sysctl.d/99-api-hardening.conf
sysctl -p /etc/sysctl.d/99-api-hardening.conf
```

### fail2ban для защиты API от brute force

fail2ban работает с логами Nginx/Apache и добавляет атакующие IP в `iptables`/`nftables`:

```bash
# /etc/fail2ban/jail.local
[api-auth]
enabled = true
port = https
filter = api-auth
logpath = /var/log/nginx/api-access.log
maxretry = 5
bantime = 3600
findtime = 600
```

```bash
# /etc/fail2ban/filter.d/api-auth.conf
[Init]
failregex = ^<HOST> .* "(POST|GET|PUT|DELETE) /api/.*" (401|403) .*$
ignoreregex =
```

**Validation:** `fail2ban-client status api-auth` показывает jail активен; при 6 неудачных попытках за 10 минут IP банится.

### Аудит API на уровне ОС

**auditd (Linux Audit):** фиксирует все обращения к API-файлам, сокетам и процессам:

```bash
# Установка правил для API-сервиса
auditctl -w /etc/nginx/conf.d/ -p wa -k api_config
auditctl -w /usr/local/bin/api-server -p x -k api_exec
auditctl -w /var/log/nginx/ -p r -k api_logs

# Просмотр событий
ausearch -k api_exec -i --start recent
# → type=EXECVE msg=audit(1698310000.000:123): argc=3 a0="api-server" ...
```

**Журнал доступа Nginx:** стандартный источник для корреляции:

```bash
# Формат лога с user_id (если API передаёт его в заголовке после аутентификации)
log_format api_access '$remote_addr - $remote_user [$time_local] '
                      '"$request" $status $body_bytes_sent '
                      '"$http_x_user_id" "$http_referer" "$http_user_agent"';

# Ротация через logrotate (7 дней)
/var/log/nginx/api-access.log {
    daily
    rotate 7
    compress
    missingok
    notifempty
}
```

### Управление сертификатами для API

Для production API обязателен TLS 1.2+ с валидными сертификатами:

```bash
# Получение через Let's Encrypt (certbot)
certbot certonly --nginx -d api.example.com --non-interactive --agree-tos -m admin@example.com
# → /etc/letsencrypt/live/api.example.com/fullchain.pem

# Автопродление
systemctl enable --now certbot.timer
journalctl -u certbot.timer -f
```

**Проверка сертификата:**
```bash
openssl s_client -connect api.example.com:443 -servername api.example.com </dev/null 2>/dev/null | openssl x509 -noout -dates -subject -issuer
# → notBefore=..., notAfter=..., subject=CN = api.example.com
```

### Мониторинг здоровья API на хосте

```bash
# systemd: статус API-сервиса
systemctl status api-server
journalctl -u api-server -f --since "10 minutes ago"

# Проверка открытых портов
ss -tlnp | grep :8080
# → LISTEN 0 128 127.0.0.1:8080 users:(("api-server",pid=1234,fd=5))

# Проверка файлового дескриптора (ulimit)
cat /proc/$(pgrep -f api-server)/limits | grep "open files"
# → Max open files 65536 65536 files
```

## Дополнительная информация

### Связь с другими доменами

- **SCA и SBOM:** анализ зависимостей API-фреймворков (Express, FastAPI, Spring Boot) на уязвимости — в **[Анализ зависимостей и SBOM](../../Security/Supply_Chain_Security/dependency_and_sbom_analysis.md)**.
- **Container security:** API, работающий в контейнере, должен проходить image scanning и runtime monitoring — в **[Безопасность контейнеров](../../Docker/Docker_security/vulnerability_scanning.md)**.
- **DAST/IAST:** динамическое тестирование API — в **[DAST — обзор](./dast_overview.md)**.
- **SAST:** статический анализ API-кода на BOLA/SSRF — в **[SAST — обзор](./sast_overview.md)**.
- **Compliance:** PCI DSS, SOC 2, ISO 27001 требуют аудита доступа к API — в **[Audit and compliance overview](../../Security/audit_and_compliance_overview.md)**.
- **Service mesh:** Istio/Envoy предоставляют встроенные rate limiting, mTLS и authz — в **[Istio rate limiting](../../Service_Mesh/istio_rate_limiting.md)**, **[Service mesh security](../../Service_Mesh/istio-sidecar-configuration.md)**.

### Метрики эффективности

- **API Security Score:** процент эндпоинтов, прошедших security review и имеющих покрытие тестами.
- **BOLA/IDOR escape rate:** уязвимости авторизации, обнаруженные в продакшене, хотя должны были быть пойманы на этапе тестирования.
- **Rate limit effectiveness:** доля запросов, отклонённых rate limiter'ом, относительно общего трафика; аномалии — сигнал к настройке порогов.
- **Authz failure rate:** доля `403 Forbidden` от общего числа запросов; всплеск может указывать на атаку или сломанный клиент.

## См. также

- **[DAST — обзор](./dast_overview.md)**
- **[HTTP security hardening](../../Networking/Protocols/HTTP/http_security_hardening.md)**
- **[WAF/WAAP](../../Security/ApplicationSecurity/waf.md)**
