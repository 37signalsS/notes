# Межсетевой экран веб-приложений (WAF)

**Актуально для:** ModSecurity 3.0.17 (libmodsecurity3, движок v3 для Nginx/Envoy/HAProxy), OWASP CRS 4.30.0 (или 4.25.0 LTS до Q3 2027). ModSecurity 2.9.x — поддерживаемая устаревшая ветка для Apache (см. ниже).

## Определение

**WAF (Web Application Firewall)** — специализированный межсетевой экран прикладного уровня (L7), предназначенный для защиты веб-приложений путем фильтрации, мониторинга и блокировки вредоносного HTTP/HTTPS-трафика. В отличие от традиционных файрволов, работающих на уровнях L3/L4, WAF анализирует содержимое пакетов (DPI — Deep Packet Inspection) и понимает логику протокола HTTP.

В современных реалиях (2025–2026 гг.) WAF эволюционировал в концепцию **WAAP (Web Application and API Protection)**, которая объединяет классический WAF, глубокую защиту API, продвинутое управление ботами и защиту от L7 DDoS в единую платформу.

См. также обзор [DDoS-атак и многоуровневой защиты](./ddos_overview.md), где WAF выступает критическим слоем защиты от атак на бизнес-логику и прикладной уровень.

## Архитектура и принципы работы

### Основные функции

- **Защита от OWASP Top 10** — противодействие критическим рискам: SQL Injection ([подробнее](./sql_injection.md)), XSS ([подробнее](./xss_and_csp.md)), RCE, Broken Access Control и другим.
- **Виртуальный патчинг (Virtual Patching)** — оперативное закрытие уязвимостей на уровне WAF до того, как будет исправлен исходный код приложения. Это критично при обнаружении Zero-day уязвимостей (например, Log4Shell).
- **Инспекция SSL/TLS** — дешифрование трафика для анализа полезной нагрузки (payload) и последующее шифрование перед отправкой на бэкенд.
- **Защита API** — проверка схем запросов (JSON/XML), валидация JWT-токенов и ограничение частоты запросов для конкретных методов API.
- **Управление ботами (Bot Management)** — идентификация и блокировка вредоносных ботов (сканеры, парсеры) при сохранении доступа для легитимных (поисковики, партнеры).
- **Поведенческий анализ** — использование ML-моделей для выявления аномалий, которые могут указывать на попытки взлома или мошенничества (Fraud), даже если сигнатуры отсутствуют.

### Модели безопасности

1.  **Отрицательная модель (Negative Security)** — блокирует только то, что явно считается вредоносным (на основе сигнатур).
    - *Плюсы:* Легкость настройки, стандартный подход для ModSecurity CRS.
    - *Минусы:* Не защищает от новых, неизвестных атак (Zero-day).
2.  **Положительная модель (Positive Security)** — разрешает только то, что явно описано как легитимное (белые списки, строгая валидация схем API).
    - *Плюсы:* Высочайший уровень защиты от неизвестных угроз.
    - *Минусы:* Требует глубокого понимания логики приложения и обновления правил при каждом релизе.

### Типы развертывания

| Тип | Описание | Особенности (2026) |
| :--- | :--- | :--- |
| **Cloud WAAP (SaaS)** | Облачные решения (Cloudflare, Akamai, Yandex Cloud WAF) | Быстрый запуск, глобальный Threat Intelligence, вbuilt-in защита от массированных DDoS. |
| **Host-based (Software)** | Модули для веб-серверов (ModSecurity для Nginx/Apache) | Минимальная задержка (latency), полный контроль над данными, но нагружает CPU сервера. |
| **Edge / Sidecar** | Интеграция в Kubernetes через Sidecar-контейнеры или eBPF | Использование **Coraza Wasm** для Envoy/Istio. Идеально для защиты East-West трафика. |
| **Network-based (Appliance)** | Физические или виртуальные устройства (F5 BIG-IP, Citrix) | Высокая производительность за счет аппаратного ускорения, интеграция в корпоративный периметр. |

## Режимы работы

- **Детектирование (Detection/Log only)** — WAF только логирует подозрительные запросы. Используется для отладки и предотвращения ложных срабатываний (False Positives).
- **Блокировка (Prevention/Blocking)** — WAF активно прерывает вредоносные сессии (обычно код 403 Forbidden).
- **Интерактивная проверка (Challenge)** — предъявление пользователю невидимых JS-проверок или CAPTCHA для подтверждения, что запрос сделан человеком.

## Сравнение WAF, RASP и NAXSI

**RASP (Runtime Application Self-Protection)** — технология, интегрированная непосредственно в среду исполнения приложения (JVM, .NET, PHP).

- **WAF** работает на входе (внешний периметр), анализирует HTTP-поток, но не знает, как приложение обработает данные.
- **RASP** работает внутри приложения, видит выполнение функций, запросы к БД и файловой системе.
- **Сценарий:** WAF эффективен для отсечения массовых атак, RASP — для предотвращения сложных атак, использующих специфику кода. Рекомендуется совместное использование.

| Характеристика | ModSecurity | NAXSI | Coraza |
| :--- | :--- | :--- | :--- |
| **Язык правил** | SecRules (собственный DSL) | Nginx-специфичные директивы | SecRules (совместимость с ModSecurity) |
| **Наборы правил** | OWASP Core Rule Set (CRS), Comodo | Собственные правила | OWASP CRS, кастомные |
| **Режимы** | DetectionOnly, On, Off | Naxsi:learning, Naxsi:off | On, Off, DetectionOnly |
| **Производительность** | Средняя (регулярные выражения) | Высокая (whitelist-based) | Высокая (Go + Wasm) |
| **Интеграция** | Nginx, Apache, HAProxy, Envoy | Только Nginx | Nginx, Apache, Envoy (Wasm) |
| **False Positive Rate** | Средний (требует тонкой настройки) | Низкий (whitelist) | Низкий (современный парсер) |
| **Размер сообщения** | Средний | Высокий | Компактный |

## Практические сценарии и конфигурация

### Предпосылки и системные требования

#### Аппаратные требования

- **CPU:** ModSecurity добавляет 5–20 мс задержки на запрос из-за регулярных выражений. На сервисах с RPS > 10 000 требуется выделенный core или использование NAXSI/Coraza.
- **RAM:** OWASP CRS потребляет ~50–100 МБ дополнительной памяти на инстанс веб-сервера. Для высоконагруженных систем выделяйте не менее 2 ГБ под WAF-компонент.
- **Диск:** Логи ModSecurity (audit log) могут быстро расти. Рекомендуется выделить отдельный раздел или настроить logrotate с политикой хранения 7–14 дней.

#### Программные требования

- **ОС:** Linux (Debian 12+, RHEL/Rocky 9+, Ubuntu 22.04 LTS). Windows не рекомендуется для production WAF.
- **Веб-сервер:** Nginx 1.25+ или Apache 2.4+ с поддержкой динамических модулей.
- **Библиотеки:** `libmodsecurity3` (>= 3.0.17; CVE-2026-30923 — DoS-уязвимость segfault'а, закрыта в 3.0.15+, рекомендуется 3.0.17) с коннектором ModSecurity-nginx v1.0.4 или ModSecurity-apache.

### Установка ModSecurity на Nginx (bare metal)

#### Debian / Ubuntu

```bash
# 1. Установка зависимостей
sudo apt update
sudo apt install -y libmodsecurity3 modsecurity-crs

# 2. Проверка версии libmodsecurity3 (>= 3.0.17)
dpkg -s libmodsecurity3 | grep -iE '^Version'
# → 3.0.17-1 (пример)

# 3. Создание директорий
sudo mkdir -p /etc/nginx/modsecurity /var/log/modsecurity /var/cache/modsecurity
sudo chown -R www-data:www-data /var/log/modsecurity /var/cache/modsecurity
```

#### RHEL / Rocky / Alma

```bash
# 1. Установка из EPEL (коннектор nginx v3 + CRS из пакета)
sudo dnf install -y epel-release
sudo dnf install -y nginx-mod-http-modsecurity mod_security_crs

# 2. Сборка коннектора из исходников — только если нужен конкретный тег
sudo dnf install -y gcc make pcre-devel libxml2-devel
git clone --depth 1 -b v1.0.4 https://github.com/owasp-modsecurity/ModSecurity-nginx.git
sudo nginx -V 2>&1 | tr ' ' '\n' | grep -i -- '--add-module.*modsecurity'
```

#### Базовая конфигурация ModSecurity

Создайте `/etc/nginx/modsecurity.conf`:

```nginx
# Включение движка
SecRuleEngine On

# Доступ к телу запроса (обязательно для CRS)
SecRequestBodyAccess On
SecRequestBodyLimit 13107200
SecRequestBodyNoFilesLimit 131072

# Доступ к телу ответа (обычно отключен для производительности)
SecResponseBodyAccess Off
SecResponseBodyLimit 524288

# Логирование
SecAuditEngine RelevantOnly
SecAuditLogRelevantStatus ^(?:5|4(?!04))
SecAuditLogParts ABIJDEFHZ
SecAuditLogType Serial
SecAuditLog /var/log/modsecurity/audit.log
SecDebugLog /var/log/modsecurity/debug.log
SecDebugLogLevel 3

# SecCacheTransformations deprecated и не поддерживается в v3 — кэш трансформаций не используется
SecTmpDir /var/cache/modsecurity
SecDataDir /var/cache/modsecurity

# Отключение шумных правил при необходимости
# SecRuleRemoveById 920350  # Пример: правило на user-agent
```

#### Подключение к Nginx

В `/etc/nginx/nginx.conf` в блоке `http`:

```nginx
load_module modules/ngx_http_modsecurity_module.so;

http {
    modsecurity on;
    modsecurity_rules_file /etc/nginx/modsecurity.conf;

    server {
        listen 443 ssl;
        server_name app.example.com;

        # Включение CRS
        # Правило: запретить HTTP/1.0 (защита от smuggling)
        if ($server_protocol ~* "^HTTP/1\.0$") { return 403; }

        location / {
            proxy_pass http://127.0.0.1:8080;
        }
    }
}
```

#### Включение OWASP CRS

```bash
# Для Debian/Ubuntu пакет размещает CRS в /etc/modsecurity/crs
sudo mkdir -p /etc/nginx/modsecurity/crs
sudo cp -r /usr/share/modsecurity-crs/* /etc/nginx/modsecurity/crs/

# Текущая CRS — 4.30.0 (октябрь 2026) или 4.25.0 LTS (поддержка до Q3 2027).
# Пакеты дистрибутивов часто тормозят: EL9 даёт CRS 3.3.4 (EOL с Q3 2026).
# Рекомендуется ставить CRS из релиза на GitHub, а не из пакета.
wget -qO- https://github.com/coreruleset/coreruleset/archive/refs/tags/v4.30.0.tar.gz | tar xz -C /etc/nginx/modsecurity/crs --strip-components=1

# Добавьте в /etc/nginx/modsecurity.conf:
SecRuleRemoveById 920350  # Пример отключения шумного правила на yaweb crawler
Include /etc/nginx/modsecurity/crs/crs-setup.conf
Include /etc/nginx/modsecurity/crs/rules/*.conf
```

### Установка ModSecurity на Apache

```bash
# Debian / Ubuntu
sudo apt install -y libapache2-mod-security2

# RHEL / Rocky
sudo dnf install -y mod_security

# Проверка загрузки модуля
apachectl -M | grep security2
# → security2_module (shared)
```

> **Версия движка:** пакеты `libapache2-mod-security2` (Debian/Ubuntu) и `mod_security` (RHEL) доставляют **ModSecurity 2.9.x** — поддерживаемая, но устаревшая ветка (см. [ModSecurity v2 EOL](https://github.com/owasp-modsecurity/ModSecurity)). Коннектор **ModSecurity-apache** для v3 существует (собирается из `owasp-modsecurity/ModSecurity-apache`), но official README помечает его **«not production ready»**; для Apache рекомендуется v2.9.x, а для высокой производительности — Coraza (см. ниже) или развёртывание WAF на nginx/HAProxy.

#### Базовая конфигурация Apache

Создайте `/etc/apache2/mods-available/security2.conf` (Debian) или `/etc/httpd/conf.d/mod_security.conf` (RHEL):

```apache
<IfModule security2_module>
    SecRuleEngine On
    SecRequestBodyAccess On
    SecRequestBodyLimit 13107200
    SecRequestBodyNoFilesLimit 131072
    SecResponseBodyAccess Off

    SecAuditEngine RelevantOnly
    SecAuditLogRelevantStatus ^(?:5|4(?!04))
    SecAuditLogParts ABIJDEFHZ
    SecAuditLogType Serial
    SecAuditLog /var/log/modsec_audit.log
    SecDebugLog /var/log/modsec_debug.log
    SecDebugLogLevel 3

    SecTmpDir /var/cache/modsecurity
    SecDataDir /var/cache/modsecurity

    Include /etc/modsecurity/crs/crs-setup.conf
    Include /etc/modsecurity/crs/rules/*.conf
</IfModule>
```

```bash
# Применение
sudo a2enmod security2 && sudo systemctl restart apache2
# RHEL:
sudo systemctl restart httpd
```

### Coraza как движок и коннекторы

Coraza (текущая версия библиотеки **v3.8.1**, октябрь 2026) — WAF на Go, 100% совместим с OWASP CRS v4 и синтаксисом правил ModSecurity SecLang. Coraza — это **библиотека**, а не standalone-бинарь: движок встраивается в приложение или задействуется через коннекторы. Развёртывание на bare metal / виртуале выглядит как модуль вашего reverse proxy, а не как облачной SAAS.

Коннекторы (статусы — на 2026 г., из [README Coraza](https://github.com/corazawaf/coraza#integrations)):

| Коннектор | Статус | Применимо для SRE (on-prem) |
| :--- | :--- | :--- |
| **coraza-spoa** (HAProxy SPOE) | production | Демон передаёт трафик в Coraza через SPOE; есть встроенный `/metrics`. |
| **coraza-proxy-wasm** | stable (Envoy) | Wasm-фильтр для Envoy/Istio. |
| **coraza-caddy** | stable (ищет maintainer) | Плагин для Caddy: `xcaddy build --with github.com/corazawaf/coraza-caddy/v2`. |
| **coraza-nginx** (libcoraza) | experimental | Модуль C для nginx; пока не рекомендуется для prod. |

> **Важно:** у Coraza **нет** standalone-бинаря с флагами `--listen`/`--upstream`. Директория `releases` проекта `corazawaf/coraza` содержит только теги библиотеки (v3.8.1), а не готовые исполняемые файлы.

#### Coraza через HAProxy SPOE (on-prem)

`coraza-spoa` — демон, передающий HTTP-трафик в Coraza через SPOE и возвращающий вердикт. Запуск:

```bash
coraza-spoa -config /etc/coraza-spoa/coraza-spoa.yaml -metrics-addr=:9000
```

Файл конфигурации берётся из [примера](https://github.com/corazawaf/coraza-spoa/blob/main/example/coraza-spoa.yaml). HAProxy направляет трафик к SPOA через backend на `127.0.0.1:9000`:

```haproxy
# /etc/haproxy/coraza.cfg
spoe-agent coraza-agent
    groups      coraza-req
    use-backend coraza-spoa

spoe-message coraza-req
    args app=var(txn.coraza.app) src-ip=src ...
```

```haproxy
# /etc/haproxy/haproxy.cfg
frontend web
    http-request set-var(txn.coraza.app) str(sample_app)
    filter spoe engine coraza config /etc/haproxy/coraza.cfg
    http-request send-spoe-group coraza coraza-req
    http-request deny deny_status 403 hdr waf-block "request" if { var(txn.coraza.action) -m str deny }

backend coraza-spoa
    mode tcp
    option spop-check
    server s1 127.0.0.1:9000 check
```

**Жёсткий systemd-юнит** (флаги проверены в официальной сборке):

```ini
# /etc/systemd/system/coraza-spoa.service
[Unit]
Description=Coraza SPOA (HAProxy Web Application Firewall)
After=network.target

[Service]
Type=simple
User=coraza-spoa
Group=coraza-spoa
ExecStart=/usr/local/bin/coraza-spoa -config /etc/coraza-spoa/coraza-spoa.yaml -metrics-addr=:9000
Restart=always
RestartSec=10
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/var/lib/coraza-spoa /var/log/coraza-spoa
PrivateTmp=true
PrivateDevices=true
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
CapabilityBoundingSet=
RestrictAddressFamilies=AF_INET AF_INET6
SystemCallFilter=@system-service
LockPersonality=true
MemoryDenyWriteExecute=true
RestrictRealtime=true

[Install]
WantedBy=multi-user.target
```

#### Метрики Coraza (Prometheus)

`/metrics` на `:9000` даёт нативные метрики. Счётчики сбрасываются при рестарте SPOA — в PromQL используйте `rate()`/`increase()`.

| Метрика | Тип | Смысл |
| :--- | :--- | :--- |
| `coraza_requests_total{application}` | Counter | Запросов, полученных на оценку WAF. |
| `coraza_transactions_total{application,mode,outcome,suspicious}` | Counter | Транзакций после оценки (outcome: `allow`/`deny`/`drop`/`redirect`/`error`/`expired`). |
| `coraza_rule_matches_total{application,rule_id,severity}` | Counter | Все сработавшие правила (включая пользовательские ID). |
| `coraza_handle_spoe_duration_seconds{application,phase,result}` | Histogram | Время обработки SPOE-сообщения. |
| `coraza_inbound_anomaly_score{application}` | Histogram | Итоговый inbound anomaly score. |
| `coraza_response_uncorrelated_total{application,reason}` | Counter | `coraza-res`, не сопоставленные с транзакцией (`missing_id`, `not_found`, `closing`, `response_check_disabled`). |
| `coraza_ruleset_info{application,ruleset,version}` | Gauge | Версия набора правил (например `OWASP_CRS`/`4.25.0`) при загрузке. |

```yaml
# Prometheus scrape job
scrape_configs:
  - job_name: coraza-spoa
    static_configs:
      - targets: ['127.0.0.1:9000']
```

```promql
# WAF-вредикты в секунду по outcome и mode
sum by (outcome, mode) (rate(coraza_transactions_total[5m]))
```


### Использование ModSecurity в Kubernetes

ModSecurity остается стандартом для open-source решений, часто интегрируясь через NGINX Ingress Controller.

```yaml
# Фрагмент манифеста Ingress с включенным WAF
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: secured-app
  annotations:
    nginx.ingress.kubernetes.io/enable-modsecurity: "true"
    nginx.ingress.kubernetes.io/enable-owasp-core-rules: "true"
    nginx.ingress.kubernetes.io/modsecurity-snippet: |
      SecRuleEngine On
      SecDefaultAction "phase:1,deny,log,status:403"
spec:
  rules:
  - host: api.example.com
    http:
      paths:
      - path: /
        backend:
          service:
            name: api-service
            port:
              number: 80
```

### Защита API через проверку схем (JSON Schema)

Современные WAAP-решения позволяют блокировать запросы, не соответствующие OpenAPI-спецификации.

```yaml
# Пример концептуального правила для валидации API
api_security:
  endpoint: "/api/v1/user/update"
  allowed_methods: ["POST"]
  required_fields: ["user_id", "email"]
  json_schema:
    properties:
      user_id: { type: "integer" }
      email: { type: "string", format: "email" }
  action: block
```

### Использование Coraza (Wasm) в Service Mesh

Coraza — это современный WAF на Go, который может работать как Wasm-плагин для Envoy, обеспечивая защиту внутри облачных сред.

```yaml
# Пример конфигурации фильтра Envoy для Coraza Wasm
http_filters:
- name: envoy.filters.http.wasm
  typed_config:
    "@type": type.googleapis.com/envoy.extensions.filters.http.wasm.v3.Wasm
    config:
      name: "coraza_waf"
      vm_config:
        runtime: "envoy.wasm.runtime.v8"
        code:
          local: { filename: "/etc/coraza/coraza-proxy-wasm.wasm" }
```

### Управление правилами и тонкая настройка

#### Кастомные правила ModSecurity

Создайте `/etc/nginx/modsecurity/custom_rules/block_suspicious_user_agents.conf`:

```apache
# Блокировка известных сканеров
SecRule REQUEST_HEADERS:User-Agent "@rx (?:sqlmap|nikto|nmap|masscan)" \
    "id:1000001,phase:1,deny,status:403,msg:'Known scanner detected'"

# Блокировка запросов с недопустимой длиной URI (> 8192 байт)
SecRule REQUEST_URI "@gt 8192" \
    "id:1000002,phase:1,deny,status:414,msg:'URI Too Long'"

# Ограничение размера JSON-тела для API
SecRule REQUEST_HEADERS:Content-Type "^application/json" \
    "id:1000003,phase:1,pass,nolog,ctl:requestBodyProcessor=JSON"
SecRule REQUEST_BODY "@gt 1048576" \
    "id:1000004,phase:2,deny,status:413,msg:'JSON body too large'"
```

#### Обработка ложных срабатываний (False Positives)

```bash
# 1. Определите ID правила из audit.log
grep "Message.*Access denied" /var/log/modsecurity/audit.log | head -5
# → id:123456

# 2. Добавьте исключение в отдельный конфиг
echo 'SecRuleRemoveById 123456' | sudo tee /etc/nginx/modsecurity/custom_rules/whitelist.conf

# 3. Перезагрузите Nginx
sudo nginx -t && sudo systemctl reload nginx

# 4. Мониторьте 24 часа. Если ложных срабатываний нет — исключение можно оставить.
```

#### Жизненный цикл правил

1. **Разработка:** Пишите правила в отдельном файле (`custom_rules/`), протестируйте в `DetectionOnly`.
2. **Тестирование:** Запустите `curl` с payload, ожидаемым к блокировке. Проверьте `audit.log`.
3. **Промоушен:** Перенесите в production config после 1 недели без ложных срабатываний.
4. **Ревизия:** Раз в квартал удаляйте устаревшие правила, обновляйте CRS.

### Анализ логов и диагностика

#### Формат audit.log (ModSecurity)

```
--abcd1234-A--
[02/Oct/2026:14:32:01 +0300] 192.168.1.100 50001 192.168.1.10 443
--abcd1234-B--
GET /admin?id=1 OR 1=1 HTTP/1.1
Host: app.example.com
--abcd1234-F--
HTTP/1.1 403 Forbidden
--abcd1234-H--
Message: Access denied with code 403 (Phase 2). Pattern match "SQL Injection" at REQUEST_URI.
Action: Intercepted (Phase 2)
--abcd1234-E--
```

#### Полезные команды для SRE

```bash
# Поиск всех блокировок за последний час
awk -v d="$(date -d '1 hour ago' '+%d/%b/%Y:%H')" '$4 ~ d' /var/log/modsecurity/audit.log | grep "Access denied"

# Топ-10 IP-адресов по количеству блокировок
grep -oP '^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}' /var/log/modsecurity/audit.log | sort | uniq -c | sort -rn | head -10

# Топ-10 правил по срабатываниям
grep -oP 'id:\d+' /var/log/modsecurity/audit.log | sort | uniq -c | sort -rn | head -10

# Поиск SQL-инъекций
grep "SQL Injection" /var/log/modsecurity/audit.log | tail -20

# Корреляция ModSecurity audit ID с access.log
# В audit.log: --abcd1234-A-- содержит client_port
# В access.log: ищем тот же port и timestamp
```

#### Диагностика через journalctl (systemd)

```bash
# Логи Nginx с фильтром по ModSecurity
journalctl -u nginx --since "1 hour ago" | grep "ModSecurity"

# Логи Apache
journalctl -u httpd --since "1 hour ago" | grep "ModSecurity"
```

### Интеграция с fail2ban

fail2ban может использовать ModSecurity audit.log как источник для автоматической блокировки повторяющихся нарушителей.

```ini
# /etc/fail2ban/filter.d/modsecurity.conf
[Definition]
failregex = ^\s*<client>\s+\S+\s+\S+\s+\S+\s+\S+\s+\S+\s+\S+\s+\S+\s+\S+\s+"Access denied with code \d+ \(Phase \d+\).*id:(\d+).*$
ignoreregex =
```

```ini
# /etc/fail2ban/jail.local
[modsecurity]
enabled  = true
port     = http,https
logpath  = /var/log/modsecurity/audit.log
maxretry = 5
bantime  = 3600
findtime = 600
action   = iptables-multiport[name=ModSecurity, port="http,https", protocol=tcp]
```

```bash
# Применение
sudo fail2ban-client reload
sudo fail2ban-client status modsecurity
```

**Валидация:**
- 5 запросов с SQL-инъекцией с одного IP за 10 минут.
- `fail2ban-client status modsecurity` — IP в списке забаненных.
- `iptables -L -n` — правило DROP.

### Мониторинг и метрики

#### Prometheus Exporter для ModSecurity

У ModSecurity v3 нет единого официального Prometheus exporter'а; метрики собираются из `audit.log`.

**Coraza SPOA** напрямую отдаёт нативные `/metrics` на `:9000` — см. [Метрики Coraza](#метрики-coraza-prometheus) выше.

**ModSecurity v3 (Nginx/Apache).** Два проверенных подхода:

_Вариант A. Filebeat → локальный SIEM (ELK/Loki)._ Чтобы аудит не требовал склейки многострочных записей, переключите формат на JSON (опционально; если не менять — читайте Serial, как в варианте B):

```nginx
# /etc/nginx/modsecurity.conf — однострочный JSON-аудит для SIEM
SecAuditLogFormat JSON
SecAuditLog /var/log/modsecurity/audit.json
# SecAuditLogParts ABIJDEFHZ — оставьте без изменений
```

```yaml
# /etc/filebeat/conf.d/modsecurity.yml
- type: log
  enabled: true
  paths:
    - /var/log/modsecurity/audit.json
  json.keys_under_root: true
  json.add_error_key: true
  fields:
    waf: modsecurity
```

_Вариант B. Bash + алертинг без SIEM — для небольших хостов (см. ниже)._

#### Ключевые метрики

| Метрика | Описание | Порог тревоги |
| :--- | :--- | :--- |
| `modsecurity_blocks_total` | Количество заблокированных запросов | > 100/мин требует анализа |
| `modsecurity_phase2_blocks_total` | Блокировки на Phase 2 (body inspection) | Всплеск = атака на логику |
| `modsecurity_unique_ips_total` | Количество уникальных IP, заблокированных за период | > 50 = массовая атака |
| `modsecurity_rule_hits{rule_id="941100"}` | Срабатывания конкретного правила | Рост = обновление атакующих стратегий |

#### Простой мониторинг через bash

```bash
# Скрипт для мониторинга количества блокировок
#!/bin/bash
BLOCKS=$(grep -c "Access denied" /var/log/modsecurity/audit.log)
if [ "$BLOCKS" -gt 100 ]; then
    echo "WARNING: High block rate: $BLOCKS/min" | mail -s "WAF Alert" ops@example.com
fi
```

### Валидация и тестирование эффективности

#### Базовые тесты для проверки работоспособности

```bash
# 1. XSS (должен блокироваться 403)
curl -s -o /dev/null -w "%{http_code}" "https://app.example.com/?q=<script>alert(1)</script>"
# → 403

# 2. SQL Injection (должен блокироваться 403)
curl -s -o /dev/null -w "%{http_code}" "https://app.example.com/?id=1 OR 1=1"
# → 403

# 3. Path Traversal (должен блокироваться 403)
curl -s -o /dev/null -w "%{http_code}" "https://app.example.com/../../../etc/passwd"
# → 403

# 4. Легитимный запрос (должен проходить 200)
curl -s -o /dev/null -w "%{http_code}" "https://app.example.com/?id=42"
# → 200

# 5. Проверка audit.log
tail -5 /var/log/modsecurity/audit.log
# → Должны присутствовать записи с id:941100, id:942100 и т.д.
```

#### Регрессионное тестирование после изменения правил

```bash
#!/bin/bash
# test_waf_rules.sh — запускается после каждого обновления CRS

ATTACKS=(
    "?q=<script>alert(1)</script>:XSS"
    "?id=1+OR+1=1:SQLi"
    "?file=../../../etc/passwd:Path Traversal"
    "?cmd=cat+/etc/passwd:Command Injection"
)

PASS=0
FAIL=0

for attack in "${ATTACKS[@]}"; do
    PAYLOAD="${attack%%:*}"
    EXPECTED="${attack##*:}"
    STATUS=$(curl -s -o /dev/null -w "%{http_code}" "https://app.example.com/${PAYLOAD}")
    
    if [ "$STATUS" == "403" ]; then
        echo "[PASS] $EXPECTED blocked (403)"
        ((PASS++))
    else
        echo "[FAIL] $EXPECTED returned $STATUS (expected 403)"
        ((FAIL++))
    fi
done

echo "Results: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ] || exit 1
```

### Типичные проблемы и устранение неполадок

| Проблема | Симптом | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **Высокая задержка** | RPS падает, latency растет | `systemd-analyze blame`, `top`, проверка `SecRuleRemoveById` для сложных regex | Переход на NAXSI, отключение тяжелых правил, вертикальное/горизонтальное масштабирование |
| **Ложные срабатывания** | Легитимные запросы возвращают 403 | `grep "Access denied" /var/log/modsecurity/audit.log` | `SecRuleRemoveById`, создание исключений по `REQUEST_URI` |
| **Утечка памяти** | RSS процесса Nginx растет indefinitely | `pmap -x $(pgrep nginx)`, проверка `SecCacheTransformationsOnDiskCache` | Увеличение `SecTmpDir`, обновление до последней версии ModSecurity |
| **Не читается тело запроса** | Запросы с JSON/XML не проверяются | `grep "Request body no files data" /var/log/modsecurity/debug.log` | Убедитесь, что `SecRequestBodyAccess On` и `SecRequestBodyLimit` > реальный размер тела |
| **Утечка audit.log** | Лог занимает весь диск | `du -sh /var/log/modsecurity/*` | Настройте `logrotate` или `SecAuditLogRelevantStatus` для ограничения записей |
| **TLS Inspection ошибки** | Backend получает зашифрованный трафик | Проверка, что WAF стоит перед TLS termination | WAF должен работать после TLS termination (на plaintext HTTP) или использовать собственный сертификат |

### Лучшие практики для продакшена

1.  **Период DetectionOnly:** Первые 2–4 недели на проде работайте в режиме `SecRuleEngine DetectionOnly`. Собирайте статистику, отключайте шумные правила через `SecRuleRemoveById`, затем переключайтесь в `On`.
2.  **Обновление CRS:** Подписывайтесь на репозиторий OWASP CRS. Обновляйте правила раз в месяц, тестируйте на staging перед деплоем на prod.
3.  **Сегрегация правил:** Разделяйте кастомные правила, CRS и исключения по разным файлам. Это упрощает аудит и откат.
    ```
    /etc/nginx/modsecurity/
    ├── modsecurity.conf      # Основные директивы
    ├── crs/
    │   ├── crs-setup.conf
    │   └── rules/
    ├── custom_rules/
    │   ├── block_scanners.conf
    │   └── api_protection.conf
    └── whitelist/
        └── false_positives.conf
    ```
4.  **Rate Limiting + WAF:** Комбинируйте `limit_req_zone` в Nginx с WAF. WAF защищает от сложных атак, rate limiting — от простого флуда.
5.  **Логирование в SIEM:** Передавайте audit.log в ELK/Graylog/Splunk через Filebeat/Vector. Это позволяет коррелировать WAF-события с другими инцидентами.
6.  **Резервное копирование правил:** Храните кастомные правила в Git. Восстановление после сбоя занимает минуты, а не часы.
7.  **Регулярный пентест:** Раз в квартал запускайте сканеры (OWASP ZAP, Burp Suite) в режиме passive scan для проверки, что WAF действительно блокирует целевые векторы.
8.  **Отказ от unsafe-inline в CSP:** WAF не защищает от DOM-based XSS. CSP с `strict-dynamic` и nonces закрывает эту брешь.

## Ограничения и методы обхода (Evasion)

WAF не является панацеей, и злоумышленники используют различные техники обхода:

1.  **Impedance Mismatch (Несогласованность парсинга):** Разница в том, как WAF и бэкенд интерпретируют протокол или данные. Например, WAF может не видеть нагрузку в специфической кодировке, которую бэкенд успешно декодирует.
2.  **HTTP Request Smuggling:** Использование различий в обработке заголовков `Content-Length` и `Transfer-Encoding` для "протаскивания" скрытого запроса через WAF.
3.  **Обфускация и кодирование:** Использование двойного URL-кодирования, Unicode-эквивалентов или фрагментации JSON-полей.
4.  **Атаки на бизнес-логику:** WAF часто не понимает контекст (например, правомерность изменения цены товара), пропуская логические манипуляции.
5.  **DOM-based XSS:** Атаки, происходящие целиком на стороне браузера, которые серверный WAF не в состоянии проанализировать.

**Рекомендация:** Используйте WAF как один из уровней защиты в рамках стратегии **Defense-in-Depth**, дополняя его безопасной разработкой (Secure SDLC) и регулярными пентестами.

## Дополнительные материалы

### Внутренние ссылки
- [SQL Injection](./sql_injection.md) — детализация атак и примеры правил.
- [XSS and CSP](./xss_and_csp.md) — защита фронтенда и ограничения WAF.
- [DDoS Overview](./ddos_overview.md) — место WAF в иерархии защиты от DDoS.
- [Firewall Concepts](../../Networking/Concepts/firewall_concepts.md) — сравнение WAF с L3/L4 файрволами и NGFW.
- [Безопасность HTTP в продакшене](../../Networking/Protocols/HTTP/http_security_hardening.md) — расширенные сценарии ModSecurity, NAXSI и заголовки безопасности.
- [Руководство по безопасности Nginx и Angie](../../WebServers/Nginx/Security/nginx_security_guide.md) — тюнинг веб-серверов и модулей безопасности.

### Внешние ресурсы
- [OWASP Coraza WAF](https://coraza.io/) — современный Cloud Native WAF проект.
- [OWASP ModSecurity Core Rule Set (CRS)](https://coreruleset.org/) — основной набор сигнатур.
- [OWASP API Security Project](https://owasp.org/www-project-api-security/) — специфика защиты API.
- [WAF Evasion Techniques (OWASP)](https://owasp.org/www-community/WAF_Evasion_Techniques) — подробный разбор методов обхода.
