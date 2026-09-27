**Актуально для:** Nginx 1.25+, HAProxy 2.8+, Kubernetes 1.29+, ModSecurity 3.0.12+, Coraza 0.4+

# WAF, DDoS и Rate Limiting для фронтенда

## Определения

- **WAF (Web Application Firewall)** — фильтр L7, блокирующий SQL injection, XSS, path traversal и другие атаки на прикладной уровень.
- **DDoS Protection** — многоуровневая защита от volumetric (L3/L4), protocol и application-layer (L7) атак.
- **Rate Limiting** — ограничение количества запросов за единицу времени по ключу (IP, cookie, API-key, гео).
- **Bot Management** — идентификация и управление трафиком ботов: легитимные поисковики, скреперы, сканеры, fraud-боты.
- **Edge Rules** — правила на CDN/reverse proxy, выполняемые до попадания запроса на origin.
- **Challenge Page (CAPTCHA/JS challenge)** — проверка браузера перед допуском к ресурсу.
- **Anycast Network** — сеть с распределёнными точками присутствия для амортизации DDoS и снижения latency.
- **Virtual Patching** — оперативное закрытие уязвимостей на уровне WAF до исправления кода приложения.
- **False Positive (FP)** — легитимный запрос, ошибочно заблокированный WAF.
- **False Negative (FN)** — вредоносный запрос, пропущенный WAF.
- **Token Bucket** — алгоритм rate limiting с фиксированным бюджетом запросов и пополнением со временем.
- **Sliding Window** — алгоритм rate limiting с плавным окном, предотвращающий burst-обход.
- **Origin Shielding** — архитектура, в которой CDN/edge защищает origin от прямого доступа и DDoS.
- **Connection Limiting** — ограничение количества одновременных соединений с одного источника.
- **IP Reputation** — база IP-адресов с репутацией (tor-exit, хостинг, известные ботнеты).
- **Geo-blocking** — блокировка или ограничение трафика по географическому признаку.

---

## Предварительные требования

- **WAF/Reverse Proxy:** Nginx 1.25+ с ModSecurity 3.0.12+ или Coraza 0.4+, или HAProxy 2.8+.
- **Kubernetes:** кластер v1.29+ с Ingress Controller (NGINX Ingress Controller 1.9+ или Gateway API controller) и поддержкой NetworkPolicy.
- **Мониторинг:** Prometheus + Alertmanager с экспортёром метрик WAF/nginx/haproxy; Loki или ELK для логов.
- **Автоматизация блокировок:** fail2ban 0.11+ или аналог для автоматического ban IP по логам WAF.
- **CI/CD:** пайплайн (GitLab CI 16+), deployющий WAF-правила через configuration management (Ansible, Puppet) или GitOps.
- **Тестовое окружение:** стенд с браузерной автоматизацией (Playwright/Puppeteer) для проверки challenge pages и WAF false positives.
- **Сеть:** CNI-плагин, поддерживающий NetworkPolicy; egress к external reputation/geo-IP базам разрешён.
- **Vault:** HashiCorp Vault 1.15+ или аналогичный для хранения CDN/WAF API-токенов и секретов.

---

## Основные концепции

### Defense in Depth для фронтенда

Защита фронтенд-сервиса строится из нескольких слоёв:

```
Пользователь
    │
    ▼
Anycast CDN / Edge ── health checks ──► Origin Pool
    │                                        │
    │                                        ▼
    │                                  Reverse Proxy
    │                                  (Nginx / HAProxy)
    │                                        │
    │                                        ▼
    │                                  WAF
    │                                  (ModSecurity / Coraza / NAXSI)
    │                                        │
    │                                        ▼
    │                                  Rate Limiting
    │                                  (limit_req / stick-rate-sessions)
    │                                        │
    │                                        ▼
    │                                  Connection Limiting
    │                                  (limit_conn / stick-table)
    │                                        │
    ├──► Static assets (fingerprinted, immutable)
    │         │
    │         ├── CDN cache (stale-if-error, stale-while-revalidate)
    │         └── Origin shielding
    │
    └──► SSR/SSG контент
              │
              ├── Edge cache (TTL + revalidate)
              └── Origin cache (Vary: Cookie)
```

Каждый слой независим; отказ одного не должен обходить остальные.

### WAF: типы развёртывания

| Тип | Примеры | Особенности |
| :--- | :--- | :--- |
| **Host-based** | ModSecurity для Nginx/Apache, Coraza, NAXSI | Полный контроль, минимальная latency, нагружает CPU origin |
| **Kubernetes Ingress** | NGINX Ingress Controller + ModSecurity annotations, Envoy Gateway + Coraza Wasm | Нативная интеграция в K8s, масштабируемость через pods |
| **Reverse Proxy** | Nginx, HAProxy, Angie standalone | Универсальность, подходит для bare metal и VM |
| **Edge / CDN** | Любой CDN с WAF-возможностями | Amortзация volumetric DDoS, Anycast, но зависимость от внешнего сервиса |

Для фронтенда оптимально сочетание edge WAF (L7 DDoS amortization) + host-based WAF (глубокий инспект, virtual patching). Generic theory deployment types, modes и comparison ModSecurity/NAXSI/Coraza описаны в **[WAF — обзор](../../Security/ApplicationSecurity/waf.md)**.

### Rate Limiting: алгоритмы и уровни

| Алгоритм | Принцип | Пример использования |
| :--- | :--- | :--- |
| **Token Bucket** | Фиксированный бюджет с пополнением | Nginx `limit_req` по умолчанию |
| **Sliding Window** | Плавное окно без резкого сброса | HAProxy `stick-rate-sessions` |
| **Leaky Bucket** | Очередь с постоянным выводом | Прикладной rate limit в коде |
| **Fixed Window** | Жёсткое окно по часам/минутам | API tier лимиты |

Generic теория rate limiting, алгоритмы и сравнение на разных уровнях — в **[Rate Limiting и устойчивость HTTP-сервисов](../../Networking/Protocols/HTTP/http_rate_limiting_circuit_breakers.md)**.

### DDoS: taxonomy

- **L3/L4 (Volumetric):** flood запросами, исчерпание bandwidth origin. Защита: Anycast, scrubbing center, nftables rate limit.
- **L7 (Application-layer):** медленные запросы (Slowloris), flood на auth-эндпоинты, cache busting. Защита: WAF, rate limiting, challenge.
- **Protocol:** SYN flood, ACK flood, фрагментация. Защита: kernel parameters, SYN cookies, conntrack limits.

Для фронтенда критичен L7 DDoS: SSR/SSG эндпоинты потребляют много CPU/памяти на запрос, поэтому даже умеренный flood может вывести origin.

### Боты и их влияние на фронтенд

| Тип бота | Влияние на фронтенд | Стратегия |
| :--- | :--- | :--- |
| **Поисковики** (Googlebot, Yandex) | Нужны для SEO; блокировка ломает индексацию | Whitelist по verified IP ranges и User-Agent |
| **Скреперы** (ценовые агрегаторы) | Нагрузка на SSR/CDN; steal контента | Challenge page, rate limit по User-Agent + fingerprint |
| **Сканеры** (Nessus, Nikto) | Поиск уязвимостей в статике/API | WAF rules, block по signature |
| **Fraud-боты** (credential stuffing) | Brute-force на auth-эндпоинты | Rate limit + 2FA, account lockout, WAF anomaly detection |

### Взаимодействие WAF/CDN и кэша фронтенда

- **Cache stampede:** массовая инвалидация CDN создаёт всплеск запросов к origin. Решение: теговая инвалидация, Origin-level rate limiting.
- **Stale cache после WAF false positive:** WAF блокирует запрос, но CDN кэширует 403. Поток легитимных пользователей получает stale-403. Решение: `Cache-Control: no-store` для 4xx/5xx, разделение кэша по `Vary: X-Cache-Status`.
- **Challenge page и SEO:** поисковики должны получать контент, а не challenge. Решение: verified bot allowlist на L7.

### IP Reputation и Geo-blocking

- **IP Reputation:** интеграция с базами (tor-exit, хостинг-провайдеры, известные ботнеты) для preemptive блокировки.
- **Geo-blocking:** ограничение или блокировка регионов с высоким уровнем ботов. Для frontend важно не блокировать CDN-nodes в этих регионах — блокировка должна быть на L7 после Anycast.

---

## Практические сценарии

### Сценарий 1: Nginx + ModSecurity + Rate Limiting

```nginx
# /etc/nginx/conf.d/frontend-waf.conf

# --- Rate limiting зоны ---
limit_req_zone $binary_remote_addr zone=api:10m rate=10r/s;
limit_req_zone $http_cookie zone=auth:10m rate=5r/s;
limit_req_zone $binary_remote_addr zone=static:10m rate=30r/s;

# --- Connection limiting ---
limit_conn_zone $binary_remote_addr zone=addr:10m;

# --- WAF: блокировка подозриных запросов ---
map $request_uri $blocked {
    default 0;
    "~*(union|select|insert|delete|drop|script|iframe)" 1;
    "~*\.\./" 1;
}

server {
    listen 443 ssl http2;
    server_name example.com;

    # TLS
    ssl_certificate /etc/nginx/ssl/example.com.crt;
    ssl_certificate_key /etc/nginx/ssl/example.com.key;
    ssl_protocols TLSv1.2 TLSv1.3;

    # WAF: блокировка
    if ($blocked) {
        return 403;
    }

    # API rate limiting
    location /api/ {
        limit_req zone=api burst=20 nodelay;
        limit_req_status 429;
        limit_conn addr 20;
        proxy_pass http://ssr_upstream;
    }

    # Auth endpoints: строгий лимит
    location /api/auth/ {
        limit_req zone=auth burst=5 nodelay;
        limit_req_status 429;
        limit_conn addr 10;
        proxy_pass http://ssr_upstream;
    }

    # Статика: мягкий лимит
    location / {
        limit_req zone=static burst=50 nodelay;
        limit_req_status 429;
        limit_conn addr 50;
        root /var/www/frontend;
        try_files $uri $uri/ /index.html;
    }
}
```

**Валидация:**
- **WAF:** `curl -X POST https://example.com/api/search?q=../etc/passwd` → `403`.
- **Rate limit:** `ab -n 200 -c 20 https://example.com/api/` → `429` после превышения 10r/s.
- **Connection limit:** `hey -c 100 -n 10000 https://example.com/` → `503` при превышении 50 соединений.
- **Auth endpoint:** `ab -n 50 -c 10 https://example.com/api/auth/login` → `429` после 5r/s.
- **Static:** fingerprint-файлы кэшируются; rate limit не срабатывает на нормальную навигацию.

**Troubleshooting:**
| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| Legit users получают 429 | Слишком строгий rate limit | Использовать cookie-based или token-based limiting; увеличить burst |
| WAF не блокирует SQLi | `map $request_uri` не охватывает паттерн | Добавить правило в `map` или использовать ModSecurity CRS |
| Connection limit не работает | `limit_conn_zone` не определён | Проверить порядок загрузки конфигов: `nginx -t` |
| Static кэшируется с 403 | Нет `Vary: X-Cache-Status` или `no-store` на 4xx | Добавить `add_header Cache-Control no-store always;` для 4xx/5xx |
| Auth endpoint уязвим к brute-force | Rate limit только по IP, боты ротируют IP | Добавить account lockout на бэкенде; WAF anomaly detection |

---

### Сценарий 2: HAProxy + stick-rate-sessions + Connection Limiting

```haproxy
# /etc/haproxy/haproxy.cfg

backend frontend_api
    balance roundrobin
    stick-table type ip size 100k expire 30s store http_req_rate(10s)
    stick-match src
    http-request track-sc0 src
    http-request deny if { sc_http_req_rate(10s) gt 100 }
    
    # Connection limiting per source
    server s1 10.0.0.10:3000 check maxconn 50
    server s2 10.0.0.11:3000 check maxconn 50

frontend frontend_https
    bind *:443 ssl crt /etc/haproxy/ssl/example.com.pem
    default_backend frontend_api
    option http-server-close
```

**Валидация:**
- **Rate limit:** `ab -n 200 -c 50 https://example.com/api/` → `403` после 100 req/10s с одного IP.
- **Connection limit:** `hey -c 200 -n 10000 https://example.com/api/` → `503` при превышении `maxconn 50` на бэкенде.
- **Stick-table:** `echo "show table frontend_api" | socat stdio /var/run/haproxy.sock` — просмотр активных ключей и их RPS.

**Troubleshooting:**
| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| stick-table не ограничивает | `stick-match` и `track-sc0` не совпадают | Проверить порядок директив; `stick-match` должен идти перед `track-sc0` |
| maxconn не работает | `maxconn` установлен на frontend, а не backend | Установить `maxconn` на `server` строку в backend |
| HAProxy роняет соединения при spike | `timeout connect` или `timeout server` слишком низкие | Увеличить `timeout connect 5s`, `timeout server 30s` |

---

### Сценарий 3: Kubernetes Ingress + WAF annotations

```yaml
# ingress-frontend.yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: frontend-ingress
  namespace: production
  annotations:
    nginx.ingress.kubernetes.io/limit-rps: "10"
    nginx.ingress.kubernetes.io/limit-connections: "20"
    nginx.ingress.kubernetes.io/limit-rpm: "300"
    nginx.ingress.kubernetes.io/server-snippets: |
      # WAF: блокировка path traversal
      if ($request_uri ~* "\.\.") {
          return 403;
      }
    nginx.ingress.kubernetes.io/configuration-snippet: |
      # Auth endpoints: строгий лимит
      if ($request_uri ~ "^/api/auth") {
          return 429;
      }
spec:
  ingressClassName: nginx
  tls:
    - hosts:
        - example.com
      secretName: example.com-tls
  rules:
    - host: example.com
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: frontend-service
                port:
                  number: 80
```

**Валидация:**
- **Rate limit:** `ab -n 200 -c 50 https://example.com/` → `503` при превышении 10 RPS.
- **WAF:** `curl -X POST https://example.com/api/search?q=../etc/passwd` → `403`.
- **TLS:** `openssl s_client -connect example.com:443 -servername example.com` — проверка сертификата и SNI.
- **Health:** `kubectl get ingress frontend-ingress -n production` — адрес и порт назначены.

**Troubleshooting:**
| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| Annotations не применяются | Контроллер перезапущен без ConfigMap | Проверить `kubectl describe ingress`, проверить ConfigMap NGINX Controller |
| WAF snippet не работает | Синтаксис ошибка в `configuration-snippet` | `kubectl describe pod <nginx-pod>` — логи ошибок конфига |
| Rate limit слишком строгий | `limit-rps` глобальный для всех путей | Разделить на отдельные Ingress для `/api/*` и `/` с разными annotations |
| TLS handshake падает | `server-snippets` конфликтует с `ssl` directives | Перенести TLS-специфичные директивы в ConfigMap Controller |

---

### Сценарий 4: Geographic Rate Limiting + IP Reputation + fail2ban

```nginx
# /etc/nginx/conf.d/geo-rate-limit.conf

geo $rate_limit {
    default 100r/m;
    RU 20r/m;
    CN 30r/m;
    US 200r/m;
    EU 150r/m;
}

geo $blocked_country {
    default 0;
    CN 1;  # высокий уровень ботов
    RU 1;
}

map $blocked_country $blocked {
    1 1;
    0 0;
}

limit_req_zone $binary_remote_addr zone=geo:10m rate=$rate_limit;

server {
    location / {
        limit_req zone=geo burst=20 nodelay;
        limit_req_status 429;
        
        if ($blocked) {
            return 403;
        }
        
        proxy_pass http://ssr_upstream;
    }
}
```

```bash
# /etc/fail2ban/jail.local — автоматическая блокировка по логам WAF
[nginx-waf]
enabled = true
filter = nginx-waf
logpath = /var/log/nginx/access.log
maxretry = 5
findtime = 60
bantime = 3600
action = iptables-multiport[name=nginx-waf, port="http,https", protocol=tcp]
```

**Валидация:**
- **Geo-block:** запрос из blocked geo → `403`.
- **Rate limit:** запрос из blocked geo → `429` после 20r/m (срабатывает раньше block).
- **fail2ban:** `fail2ban-client status nginx-waf` — просмотр banned IP.
- **Legitimate traffic:** запрос из whitelisted geo → проходит без ограничений.

**Troubleshooting:**
| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| Geo IP база устарела | MaxMind db не обновляется | Настроить `cron` для `geoipupdate`; проверять `geoiplookup` |
| CDN nodes в blocked geo блокируются | Geo-block на L3, CDN не проходит | Блокировать на L7 после Anycast, whitelist CDN IP ranges |
| fail2ban банит CDN IP | CDN NAT видится как один источник | Whitelist CDN IP ranges в `ignoreip`; использовать `X-Forwarded-For` с валидацией |
| NAT клиенты получают 429 | Несколько клиентов за NAT share IP | Использовать cookie-based или token-based limiting |

---

### Сценарий 5: Automated DDoS response playbook

```bash
#!/bin/bash
# /usr/local/bin/ddos-response.sh
# Запускается через cron (*/1 * * * *) или systemd timer

set -euo pipefail

PROMETHEUS_URL="http://prometheus:9090"
THRESHOLD_RPS=5000
THRESHOLD_SLOW=1000
WEBHOOK_URL="${SLACK_WEBHOOK}"

# 1. Получаем текущий RPS
CURRENT_RPS=$(curl -s "${PROMETHEUS_URL}/api/v1/query?query=rate(nginx_http_requests_total[1m])" | jq '.data.result[0].value[1] | tonumber')

# 2. Проверяем долю 5xx
ERROR_RATE=$(curl -s "${PROMETHEUS_URL}/api/v1/query?query=rate(nginx_http_requests_total{status=~\"5..\"}[5m])" | jq '.data.result[0].value[1] | tonumber')

if (( $(echo "$CURRENT_RPS > $THRESHOLD_RPS" | bc -l) )); then
    # 3. Активируем Global Rate Limit
    echo "DDoS detected: ${CURRENT_RPS} RPS. Activating global rate limit."
    curl -X POST "http://localhost:9141/rate-limit/global?rps=1000" || true
    
    # 4. Включаем challenge для подозрительных путей
    echo "Enabling JS challenge for /api/*"
    curl -X POST "http://localhost:9141/challenge/enable?path=/api/*" || true
    
    # 5. Отправляем алерт
    curl -X POST "$WEBHOOK_URL" \
        -H "Content-Type: application/json" \
        -d "{\"text\":\"DDoS detected: ${CURRENT_RPS} RPS. Global rate limit activated.\"}"
fi

if (( $(echo "$ERROR_RATE > 0.1" | bc -l) )); then
    echo "High error rate: ${ERROR_RATE}. Check origin health."
    curl -X POST "$WEBHOOK_URL" \
        -H "Content-Type: application/json" \
        -d "{\"text\":\"High 5xx rate: ${ERROR_RATE}. Check origin health.\"}"
fi
```

**Валидация:**
- **Simulation:** `hey -c 1000 -n 100000 https://example.com/` → global rate limit срабатывает; origin не получает flood.
- **Metrics:** `rate(nginx_http_requests_total[1m])` показывает spike; алерт отправлен.
- **Challenge:** запрос без JS → challenge page; браузер с JS проходит.
- **Origin health:** `curl -I https://example.com/healthz` → `200`; origin не перегружен.

**Troubleshooting:**
| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| Playbook не срабатывает | Cron/systemd timer не активен | `systemctl status ddos-response.timer`; проверить логи `/var/log/syslog` |
| Global rate limit ломает легитимных | Порог слишком низкий | Настроить порог по baseline + 3σ; мониторить в нерабочее время |
| Challenge page ломает API клиенты | API получает challenge вместо JSON | Исключить `/api/v1/*` из challenge; использовать token-based auth |
| Origin всё равно падает | Rate limit на edge, но origin получает через CDN | Включить Origin Shielding; CDN должен аутентифицироваться на origin |

---

## Операционные команды

```bash
# --- ModSecurity / Coraza ---
# Проверка статуса ModSecurity
curl -s http://localhost/nginx_status | grep -i modsecurity

# Просмотр audit.log за последний час
journalctl -u nginx --since "1 hour ago" | grep "ModSecurity" | tail -100

# Анализ нарушений по правилу
grep "Message: " /var/log/modsecurity/audit.log | awk '{print $NF}' | sort | uniq -c | sort -rn | head -20

# Проверка конфигурации
nginx -t && systemctl reload nginx

# --- Nginx Rate Limiting ---
# Проверка зон rate limit
curl -s http://localhost/nginx_status | grep -i "zone"
# Или через stub_status
curl -s http://localhost/nginx_status

# Очистка зоны (если нужно сбросить лимит)
# Нет встроенной команды; требуется reload или удаление зоны через shared memory

# --- HAProxy ---
# Статус и stick-table
echo "show table frontend_api" | socat stdio /var/run/haproxy.sock | head -50

# Очистка stick-table
echo "clear table frontend_api" | socat stdio /var/run/haproxy.sock

# Статистика
echo "show stat" | socat stdio /var/run/haproxy.sock | column -t -s, | head -30

# --- fail2ban ---
# Статус jail
fail2ban-client status nginx-waf

# Просмотр banned IP
fail2ban-client status nginx-waf | grep "Banned IP list"

# Разбан IP
fail2ban-client set nginx-waf unbanip 1.2.3.4

# --- Kubernetes Ingress ---
# Проверка annotations
kubectl describe ingress frontend-ingress -n production | grep -A 20 Annotations

# Проверка логирования WAF в Controller
kubectl logs -n ingress-nginx -l app.kubernetes.io/name=ingress-nginx --tail=100 | grep -i "waf\|limit"

# --- Тестирование ---
# Rate limit тест
ab -n 200 -c 20 https://example.com/api/

# DDoS simulation (осторожно!)
hey -c 100 -n 5000 https://example.com/ --disable-keepalive

# WAF тест
curl -X POST "https://example.com/api/search?q=../etc/passwd"
curl -X POST "https://example.com/api/search?q=' OR 1=1 --"

# Проверка challenge page
curl -s -o /dev/null -w "%{http_code}" https://example.com/  # без JS
curl -s -o /dev/null -w "%{http_code}" -H "User-Agent: Googlebot" https://example.com/  # для SEO
```

---

## Типичные проблемы

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| Legit users получают 429 | Слишком строгий rate limit | Cookie-based или token-based limiting; увеличить burst; мониторить RPS baseline |
| Боты проходят WAF | Нет signature-based или behavioral rules | Включить OWASP CRS; добавить anomaly detection; использовать fail2ban |
| DDoS не детектируется | Слишком высокий порог | Настроить alert на rate > baseline + 3σ; использовать sliding window |
| Path traversal блокирует валидные URL | Жёсткий regex | Уточнить паттерн, добавить исключения в `map` |
| Challenge page ломает SEO | Googlebot получает challenge | Whitelist verified crawler User-Agent и IP ranges в WAF |
| Geographic block ломает CDN | CDN nodes в blocked регионах | Блокировать на L7 после Anycast; whitelist CDN IP ranges |
| Rate limit не работает | `limit_req_zone` не определён | Проверить порядок загрузки конфигов: `nginx -t` |
| WAF rules конфликтуют | Слишком много правил | Приоритизировать CRS managed rules, использовать tags, версионировать правила |
| fail2ban банит CDN NAT | CDN видится как один IP | Whitelist CDN IP ranges в `ignoreip`; использовать `X-Forwarded-For` с валидацией |
| Cache stampede при WAF false positive | CDN кэширует 403 | `Cache-Control: no-store always` для 4xx/5xx; разделение кэша по `Vary` |
| ModSecurity потребляет много CPU | RPS > 10 000, regex overhead | Перейти на NAXSI или Coraza; вынести WAF на отдельный хост |
| Slowloris атака не детектируется | Нет `limit_conn` или `client_body_timeout` | Настроить `limit_conn`, `client_body_timeout`, `keepalive_timeout` |

---

## Лучшие практики

1. Версионируйте WAF-правила в Git; deploy через configuration management или GitOps.
2. Включайте OWASP Core Rule Set (CRS) в режиме `DetectionOnly` на 1–2 недели, затем переключите на `On` после анализа false positives.
3. Настраивайте Rate Limiting на `/api/*` и auth-эндпоинтах; лимит — по результам нагрузочного тестирования (не по заголовкам из интернета).
4. Для auth-эндпоинтов используйте token-based limiting (cookie или API-key) вместо IP-based; это предотвращает NAT-проблемы.
5. Whitelist verified bots (Googlebot, Yandex) по IP ranges, а не по User-Agent; User-Agent легко подделать.
6. Настройте `Cache-Control: no-store always` для 4xx/5xx ответов, чтобы CDN не кэшировал WAF false positives.
7. Используйте Anycast CDN + Origin Shielding как first line; host-based WAF как second line для глубокого инспекта.
8. Мониторьте WAF violations в SIEM; алерт на всплеск > 3σ от среднего за 1h.
9. Для DDoS Protection сочетайте L3/L4 фильтрацию (nftables/iptables) + L7 WAF + Rate Limiting + Challenge.
10. Настройте fail2ban или аналогичный инструмент для автоматической блокировки повторяющихся нарушителей по логам WAF.
11. Для SSR/SSG фронтенда настроить origin-level rate limiting: даже если CDN/WAF отфильтровал 90%, origin должен иметь защиту на случай bypass.
12. Тестируйте WAF rules на penetration testing/red team; регулярно пересматривайте правила при изменении API.
13. Для Kubernetes используйте NetworkPolicy для изоляции Ingress Controller от бэкендов; WAF не заменяет NetworkPolicy.
14. Храните `nginx.conf`/`haproxy.cfg` в Git; используйте `nginx -t` в CI перед deploy.
15. Настройте logrotate для WAF audit logs: 7–14 дней retention, compress после 1 дня.
16. Для preview-окружений используйте отдельный WAF-профиль с более мягкими правилами, чтобы не блокировать разработчиков.

---

## Особые случаи

- **NAT / CGNAT за load balancer:** `$binary_remote_addr` видит IP балансировщика, а не клиента. Решения: использовать `X-Forwarded-For` с валидацией trusted proxy ranges; cookie-based rate limiting; `$connection_serial` в HAProxy.
- **Мобильные клиенты за NAT:** Hundreds of mobile users share one carrier-grade NAT IP. IP-based rate limit блокирует всех. Решения: token-based limiting (API-key); connection limiting per session; rate limit по ASN.
- **WebSocket соединения:** `limit_req` работает только на handshake; после upgrade WS не ограничивается. Решения: `limit_conn` на WS endpoint; application-level ping/pong timeout; отдельный upstream с maxconn.
- **Service Worker и кэширование:** SW может кэшировать WAF challenge/403; пользователь получает stale challenge. Решения: `Cache-Control: no-store` на challenge; SW skipWaiting + clients.claim; invalidate SW при изменении WAF правил.
- **Preview-окружения для MR/PR:** Временные окружения должны иметь отдельный WAF-профиль без production rate limits; иначе разработчики получают 429 при тестировании. Решения: отдельный Ingress/Namespace; WAF rules via ConfigMap per environment.
- **CI/CD раннеры заблокированы WAF:** Playwright/smoke-тесты из CI падают с 403/429. Решения: whitelist IP раннеров в WAF; использовать `curl` с user-agent; отдельный smoke-test namespace без WAF.
- **Cache stampede при Purge All:** Полная очистка CDN создаёт всплеск запросов к origin. Решения: ограничьте частоту Purge All, используйте теговую инвалидацию по умолчанию, добавьте Origin-level rate limiting.
- **Force-push в CDN cache:** Атакующий отправляет запросы на уникальные URL с `?nocache=<random>`, обходя кэш и создавая flood. Решения: WAF rule на `nocache` параметр; rate limit на query string; origin-level protection.
- **SSL/TLS termination и WAF:** WAF должен дешифровать трафик для инспекта. Если TLS terminated на CDN, host-based WAF видит только HTTP. Решения: terminate TLS на WAF/reverse proxy; или использовать CDN с integrated WAF + origin shielding.
- **Монорепо с несколькими фронтендами:** Разные приложения share один Ingress/Reverse Proxy. Конфликт rate limit зон и WAF rules. Решения: отдельные subdomain или path prefix per app; изоляция через namespace; версионирование правил per app.

---

## Дополнительная информация

### См. также

- **[WAF — обзор](../../Security/ApplicationSecurity/waf.md)** — ModSecurity, Coraza, NAXSI, WAAP, режимы работы, comparison.
- **[Rate Limiting и устойчивость HTTP-сервисов](../../Networking/Protocols/HTTP/http_rate_limiting_circuit_breakers.md)** — алгоритмы token bucket, sliding window, circuit breaker, HAProxy stick-rate-sessions.
- **[Security-заголовки и CSP](./frontend_security_headers.md)** — HSTS, CSP, X-Frame-Options, взаимодействие с WAF.
