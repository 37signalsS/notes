# Межсайтовый скриптинг (XSS) и политика безопасности контента (CSP)

## Определения

**XSS (Cross-Site Scripting — Межсайтовый скриптинг)** — тип уязвимости веб-приложений, при которой злоумышленник внедряет вредоносный JavaScript-код в страницы, просматриваемые другими пользователями. В отличие от других инъекций, атака направлена на клиента (браузер пользователя), а не на сервер.

**CSP (Content Security Policy — Политика безопасности контента)** — механизм защиты, реализуемый через HTTP-заголовок `Content-Security-Policy`. Он позволяет владельцам сайтов ограничивать источники ресурсов (скрипты, стили, изображения), которые браузеру разрешено загружать и исполнять для данной страницы.

## Классификация XSS-атак

| Тип | Механизм | Особенности |
| :--- | :--- | :--- |
| **Хранимый (Stored / Persistent)** | Вредоносный код сохраняется на сервере (БД, файлы, логи). | Самый опасный: скрипт исполняется у каждого, кто откроет страницу с этим контентом. |
| **Отражённый (Reflected / Non-Persistent)** | Скрипт является частью запроса (URL-параметры, формы) и возвращается сервером без очистки. | Требует взаимодействия с жертвой (переход по специально подготовленной ссылке). |
| **DOM-based (На основе DOM)** | Уязвимость находится полностью в клиентском коде. Данные из источника (напр. `location.hash`) попадают в опасную функцию (sink) без обработки. | Сервер может даже не видеть вредоносную нагрузку. В 2026 году часто эксплуатируется через **Prototype Pollution**. |
| **Mutation-based (mXSS)** | Возникает, когда браузер "исправляет" или мутирует некорректный HTML при парсинге, что приводит к появлению скрипта там, где его не было. | Сложный тип, эксплуатирует различия в парсерах разных браузеров и библиотек. |

## Сравнение уровней защиты от XSS

| Уровень | Механизм | Что блокирует | Что пропускает | Стоимость внедрения |
| :--- | :--- | :--- | :--- | :--- |
| **Приложение (App)** | Output encoding, sanitization, безопасные API | Хранимый, отражённый, DOM-based XSS на этапе рендеринга | Логические ошибки санитайзера, устаревшие библиотеки | Высокая (требует изменений в коде) |
| **Браузер (CSP)** | Заголовок `Content-Security-Policy`, Trusted Types | Инлайн-скрипты, загрузка с неавторизованных источников, DOM-based XSS | Обход через `unsafe-inline`, утечки через доверенные CDN при слабом `strict-dynamic` | Средняя (конфиг веб-сервера) |
| **Сеть (WAF)** | ModSecurity, Coraza, NAXSI — сигнатурный и поведенческий анализ | Известные паттерны OWASP Top 10, сканеры | DOM-based XSS, обфусцированные payload, атаки на бизнес-логику | Средняя (модуль веб-сервера) |

**Вывод:** Эффективная защита требует всех трёх уровней (Defense in Depth). WAF не видит DOM-based XSS, CSP не защищает от уязвимостей в самом приложении, а санитизация не спасает от ошибок конфигурации.

## Последствия и риски

- **Кража сессионных данных:** захват `session_id` из cookies для угона аккаунта.
- **Фишинг на легитимном домене:** подмена форм входа или создание поддельных всплывающих окон.
- **Манипуляция DOM:** изменение контента страницы, цен в магазине, реквизитов платежей.
- **Распространение вредоносного ПО:** загрузка эксплойт-паков через браузер жертвы.
- **Обход CSRF-защиты:** XSS позволяет прочитать CSRF-токен и выполнить любое действие от имени пользователя.

## Предпосылки и системные требования

### Железо и ОС

| Компонент | Минимум | Рекомендация |
| :--- | :--- | :--- |
| **CPU** | 2 ядра ( bare-metal ) | 4+ ядра при RPS > 5k на узел |
| **RAM** | 2 ГБ | 4+ ГБ при наличии WAF + CSP-аналитика |
| **Диск** | 20 ГБ (SSD) | 40+ ГБ SSD для логов ( retention 30–90 дней ) |
| **ОС** | Debian 12+, RHEL 9+, Rocky Linux 9+ | Kernel 5.10+ (для `getrandom()` без блокировки) |

### Программный стек

- **Веб-сервер:** Nginx 1.25+ / Apache 2.4+ / Angie (совместимый форк Nginx).
- **WAF (опционально):** ModSecurity 3.x + libmodsecurity + CRS, или Coraza (Go/WASM).
- **Сбор логов:** Filebeat / Vector / Fluent Bit → Elasticsearch / Loki / Graylog.
- **Мониторинг:** Prometheus + Grafana (алерты на всплеск XSS-попыток).
- **Автоответ:** fail2ban (фильтры для access.log и audit.log).
- **Тестирование:** `curl`, `xsstrike`, `dalfox`, `nuclei` (шаблоны XSS).

## Методы защиты: Многоуровневый подход

### 1. Экранирование вывода (Output Encoding)

Основной рубеж обороны. Данные должны преобразовываться в безопасный формат непосредственно перед вставкой в DOM.

- **HTML-контекст:** `<` → `&lt;`, `>` → `&gt;`, `&` → `&amp;`, `"` → `&quot;`, `'` → `&#x27;`.
- **JavaScript-контекст:** Данные должны экранироваться как Unicode-последовательности (`\uXXXX`) или передаваться через `JSON.stringify()`.
- **URL-контекст:** Использование `encodeURIComponent()`.

### 2. Санитизация (Sanitization)

Если приложению необходимо разрешить пользователю ввод HTML (например, в редакторе текста), необходимо использовать проверенные инструменты для очистки кода.

- **[DOMPurify](https://github.com/cure53/dompurify)** — золотой стандарт санитизации на стороне клиента.
- **Sanitizer API** — встроенный браузерный API (стандарт 2026 года), позволяющий безопасно обрабатывать HTML-строки напрямую в браузере с высокой производительностью.

### 3. Использование безопасных API и фреймворков

- **Безопасно:** `element.textContent`, `element.innerText`, `document.createElement`.
- **Опасно:** `element.innerHTML`, `element.outerHTML`, `document.write()`, `eval()`.
- **Фреймворки:** React, Vue и Angular по умолчанию экранируют данные в шаблонах. Уязвимости возникают при использовании функций `dangerouslySetInnerHTML` (React), `v-html` (Vue) или обходе `DomSanitizer` (Angular).

### 4. Безопасность Cookies

Использование флагов для минимизации последствий XSS:
- **`HttpOnly`** — запрещает доступ к куки из JavaScript.
- **`Secure`** — передача только по HTTPS.
- **`SameSite=Strict/Lax`** — защита от CSRF и некоторых видов утечек данных.

## Политика безопасности контента (CSP)

CSP — это декларативный метод защиты, который блокирует исполнение неавторизованных скриптов и ресурсов.

### Ключевые директивы (CSP Level 3)

| Директива | Описание |
| :--- | :--- |
| `default-src` | Фоллбэк для других директив, если они не указаны. |
| `script-src` | Разрешенные источники для скриптов. Рекомендуется использовать `strict-dynamic`. |
| `script-src-elem` | (Level 3) Управление конкретно тегами `<script>`. |
| `script-src-attr` | (Level 3) Управление инлайновыми обработчиками событий (`onclick`). |
| `style-src` | Разрешенные источники для стилей. |
| `img-src` | Источники изображений. |
| `connect-src` | Ограничивает URL для fetch, XHR, WebSockets. |
| `frame-ancestors` | Указывает, кто может встраивать страницу в iframe (защита от Clickjacking). |
| `base-uri` | Ограничивает URL в теге `<base>`. |
| `report-uri` / `report-to` | Эндпоинт для отправки отчетов о нарушениях политики. |

### Специальные значения и CSP Level 3

- **`'self'`** — текущий домен и протокол.
- **`'none'`** — запретить всё.
- **`'unsafe-inline'`** — разрешает инлайн-скрипты (крайне не рекомендуется).
- **`'strict-dynamic'`** — позволяет скрипту, которому доверяют (через nonce или hash), загружать дополнительные зависимости автоматически.
- **`nonce-<base64-value>`** — использование одноразового числа для разрешения конкретных скриптов.
- **Trusted Types** — механизм, запрещающий передачу строк в опасные API (sink) и требующий использования доверенных объектов.

### Пример строгой политики

```http
Content-Security-Policy: default-src 'none'; script-src 'self' 'nonce-rAnd0m123' 'strict-dynamic'; connect-src 'self'; img-src 'self'; style-src 'self'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'; upgrade-insecure-requests;
```

### Режим тестирования (Report-Only)

Позволяет проверить работу CSP без блокировки ресурсов:
```http
Content-Security-Policy-Report-Only: default-src 'self'; report-to default;
```

## Практические сценарии

### Санитизация с помощью DOMPurify

```javascript
import DOMPurify from 'dompurify';

// Очистка пользовательского ввода перед вставкой в innerHTML
const cleanHTML = DOMPurify.sanitize(userInput);
document.getElementById('content').innerHTML = cleanHTML;
```

### Использование Trusted Types (Стандарт 2026)

Trusted Types заставляют приложения использовать "доверенные объекты" вместо строк для опасных API.

```http
Content-Security-Policy: require-trusted-types-for 'script';
```

```javascript
// Создание политики безопасности
const policy = trustedTypes.createPolicy('myAppPolicy', {
  createHTML: (input) => DOMPurify.sanitize(input)
});

// Браузер заблокирует строку, но разрешит TrustedHTML объект
element.innerHTML = policy.createHTML(userInput);
```

### Конфигурация логирования нарушений (Nginx)

Для сбора нарушений CSP и попыток XSS настройте отдельный `log_format`:

```nginx
http {
    # Формат для Security-логов с полным набором полей
    log_format security_combined escape=json
        '{'
            '"time":"$time_iso8601",'
            '"remote_addr":"$remote_addr",'
            '"request":"$request",'
            '"status":$status,'
            '"body_bytes_sent":$body_bytes_sent,'
            '"http_referer":"$http_referer",'
            '"user_agent":"$http_user_agent",'
            '"xss_payload":"$args"'
        '}';

    server {
        listen 443 ssl;
        server_name example.com;

        access_log /var/log/nginx/security_xss.log security_combined;

        # CSP с отправкой нарушений на эндпоинт /csp-report
        add_header Content-Security-Policy-Report-Only
            "default-src 'self'; script-src 'self'; report-uri /csp-report" always;
    }
}
```

**Валидация:**
```bash
# Проверка, что лог-файл создаётся и наполняется
tail -f /var/log/nginx/security_xss.log
# → {"time":"2026-09-18T13:00:00+00:00","remote_addr":"1.2.3.4",...}
```

### Конфигурация логирования нарушений (Apache)

```apacheconf
LogFormat "{ \
    \"time\":\"%t\", \
    \"remote_addr\":\"%h\", \
    \"request\":\"%r\", \
    \"status\":%>s, \
    \"user_agent\":\"%{User-Agent}i\" \
}" security_json

CustomLog "|/usr/bin/logger -p local4.info -t apache_xss" security_json

# CSP Report-Only
Header always set Content-Security-Policy-Report-Only \
    "default-src 'self'; script-src 'self'; report-uri /csp-report"
```

### Сбор и анализ нарушений CSP

Настройте эндпоинт для приёма JSON-отчётов о нарушениях CSP:

```bash
# /etc/nginx/conf.d/csp-report.conf
server {
    listen 127.0.0.1:8080;
    server_name localhost;

    location /csp-report {
        # Сохраняем в файл для последующего анализа
        access_log /var/log/nginx/csp_violations.log security_combined;
        return 204;
    }
}
```

Анализ нарушений:

```bash
# Топ-10 заблокированных источников скриптов
grep -oP '"blocked-uri":"[^"]*"' /var/log/nginx/csp_violations.log \
  | sort | uniq -c | sort -rn | head -20

# Поиск XSS-паттернов в CSP-нарушениях
grep -i "script-src" /var/log/nginx/csp_violations.log \
  | grep -iE "data:|eval\(|javascript:" | wc -l

# Корреляция с access.log: какой IP генерирует больше всего нарушений
awk -F'"' '/csp-report/ {print $3}' /var/log/nginx/csp_violations.log \
  | sort | uniq -c | sort -rn | head -10
```

### Интеграция с fail2ban

Создайте фильтр для блокировки IP, генерирующих XSS-паayloads в access.log:

```ini
# /etc/fail2ban/filter.d/nginx-xss.conf
[Definition]
failregex = ^<HOST> .* "(GET|POST) .*(<script|javascript:|onerror=|onload=|alert\().*" \d+ \d+$
            ^<HOST> .* "(GET|POST) .*(%3Cscript|%3Csvg|%3Cimg).*" \d+ \d+$
ignoreregex =
```

```ini
# /etc/fail2ban/jail.d/nginx-xss.conf
[nginx-xss]
enabled  = true
port     = http,https
filter   = nginx-xss
logpath  = /var/log/nginx/access.log
maxretry = 3
findtime = 600
bantime  = 3600
action   = iptables-multiport[name=nginx-xss, port="http,https", protocol=tcp]
```

**Валидация:**
```bash
# Тестовый запуск фильтра без применения бана
fail2ban-regex /var/log/nginx/access.log /etc/fail2ban/filter.d/nginx-xss.conf

# Проверка статуса jail
fail2ban-client status nginx-xss
# → Banned IP list: 1.2.3.4
```

### Мониторинг и оповещения

#### Ключевые метрики

| Метрика | Источник | Порог тревоги |
| :--- | :--- | :--- |
| `csp_violations_total` | `/var/log/nginx/csp_violations.log` | > 100/час на одного клиента |
| `xss_payloads_detected` | Access log + fail2ban | > 5 уникальных payloadов/час |
| `waf_xss_blocks` | ModSecurity audit.log | Всплеск > 3σ от среднего |
| `csp_report_endpoint_errors` | Nginx error.log | > 10/час (возможна DoS-атака на эндпоинт) |

#### Prometheus Exporter для логов

```bash
# Пример metrics-сниппета через Loki/Promtail
groups:
  - name: xss_rules
    rules:
      - record: job:csp_violations:rate5m
        expr: sum(rate({job="nginx"} |= "csp-report"[5m])) by (remote_addr)
      - alert: CSPViolationSpike
        expr: rate({job="nginx"} |= "csp-report"[5m]) > 10
        for: 2m
        labels:
          severity: warning
        annotations:
          summary: "Всплеск CSP-нарушений на {{ $labels.remote_addr }}"
```

### Валидация и регрессионное тестирование

#### curl-тесты для XSS

```bash
#!/bin/bash
# test_xss_protection.sh — запускается после каждого деплоя

BASE_URL="https://example.com"

ATTACKS=(
    "<script>alert(1)</script>"
    "<img src=x onerror=alert(1)>"
    "<svg onload=alert(1)>"
    "javascript:alert(1)"
    "<body onload=alert(1)>"
    "\"><script>alert(1)</script>"
    "'><script>alert(1)</script>"
)

echo "=== Testing XSS Protection ==="
for payload in "${ATTACKS[@]}"; do
    encoded=$(python3 -c "import urllib.parse; print(urllib.parse.quote('''$payload'''))")
    status=$(curl -s -o /dev/null -w "%{http_code}" "${BASE_URL}/?q=${encoded}")

    if [ "$status" == "403" ] || [ "$status" == "406" ]; then
        echo "[PASS] Blocked: ${payload:0:40}... → ${status}"
    else
        echo "[FAIL] NOT blocked: ${payload:0:40}... → ${status}"
    fi
done
```

**Валидация:**
```bash
chmod +x test_xss_protection.sh
./test_xss_protection.sh
# → [PASS] Blocked: <script>alert(1)</script>... → 403
# → [PASS] Blocked: <img src=x onerror=alert(1)>... → 403
```

#### Проверка заголовков CSP

```bash
#!/bin/bash
# test_csp_headers.sh

URL="https://example.com"
HEADERS=$(curl -sI "$URL")

echo "=== CSP Header Check ==="

if echo "$HEADERS" | grep -qi "Content-Security-Policy"; then
    echo "[PASS] CSP header present"
    echo "$HEADERS" | grep -i "Content-Security-Policy"
else
    echo "[FAIL] CSP header missing"
    exit 1
fi

if echo "$HEADERS" | grep -qi "unsafe-inline"; then
    echo "[WARN] unsafe-inline detected in CSP — review required"
else
    echo "[PASS] No unsafe-inline in CSP"
fi

if echo "$HEADERS" | grep -qi "strict-dynamic"; then
    echo "[PASS] strict-dynamic present"
else
    echo "[INFO] strict-dynamic not set — consider adding for CDN scripts"
fi
```

### Типичные проблемы и устранение неполадок

| Проблема | Симптом | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **CSP ломает легитимный JS** | Консоль: `Refused to execute inline script` | DevTools → Console → CSP violation | Добавить `nonce-...` или хэш для конкретного скрипта |
| **Аналитика не работает** | Нет данных в Google Analytics / Matomo | DevTools → Network → запросы к analytics домену заблокированы | Добавить домен аналитики в `connect-src` / `img-src` |
| **DOM-based XSS не детектируется** | XSS в консоли, WAF молчит | Запросы на сервер чистые, но payload в `location.hash` | CSP с `strict-dynamic` + Trusted Types; или Safer DOM API |
| **CSP Report-Only не доставляется** | Нет записей в логе `/csp-report` | `curl -I` — проверка `report-uri`; доступность эндпоинта | Проверить сетевую доступность, CORS для `report-uri` |
| **False positive: XSS в username** | WAF блокирует `O'Brien` или `5 < 10` | Audit.log — правило ID и описание | `SecRuleRemoveById` или `SecRuleUpdateTargetById` в ModSecurity |
| **mXSS в rich-text редакторе** | Появление `<script>` после нормализации HTML | DOMPurify не настроен на `RETURN_DOM` или `RETURN_DOM_FRAGMENT` | Включить `RETURN_DOM` и проверять нормализацию до вставки |
| **Mutation XSS через base64** | XSS-пейлоад в base64-изображении | Изображение с data: URI декодируется браузером как HTML | Блокировать `img-src data:` в CSP или валидировать MIME на сервере |

### Практика внедрения CSP в продакшене

#### Этап 1: Аудит (неделя 1–2)

```bash
# Включите Report-Only и соберите нарушения 7–14 дней
add_header Content-Security-Policy-Report-Only \
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; report-uri /csp-report" always;

# Ежедневно анализируйте топ нарушений
grep -oP '"violated-directive":"[^"]*"' /var/log/nginx/csp_violations.log \
  | sort | uniq -c | sort -rn
```

#### Этап 2: Включение в enforce-режим (неделя 3–4)

```bash
# Переключите на enforce, оставив report-uri для сбора новых нарушений
add_header Content-Security-Policy \
    "default-src 'self'; script-src 'self' 'nonce-REPLACE_ME'; style-src 'self'; img-src 'self' data:; connect-src 'self'; report-uri /csp-report" always;
```

#### Этап 3: Мониторинг и итерации (непрерывно)

- Настройте алерты на всплеск CSP-нарушений (>3σ от среднего).
- Раз в квартал пересматривайте `SecRuleRemoveById` исключения в WAF.
- После каждого релиза фронтенда проверяйте, что CSP не ломает новые фичи (CI/CD пайплайн, Сценарий 3 из `frontend_security_headers.md`).

## Инструменты и аудит

- **Google CSP Evaluator** — проверка политики на наличие лазеек для обхода.
- **Mozilla Observatory** — комплексный аудит заголовков безопасности.
- **XSStrike / Dalfox** — инструменты для автоматизированного поиска XSS-уязвимостей.
- **Sentry / Report-URI** — сервисы для сбора и мониторинга CSP-отчетов в реальном времени.

## Дополнительная информация

### Внутренние ссылки
- [WAF (Web Application Firewall)](./waf.md) — блокировка XSS на сетевом уровне.
- [SQL Injection](./sql_injection.md) — обзор серверных инъекций.
- [SAST/DAST в DevSecOps](../../CI-CD/DevSecOps/devsecops_overview.md) — автоматизация поиска XSS в пайплайне.
- [Security-заголовки и CSP для статики](../../CI-CD/Frontend_CI_CD/frontend_security_headers.md) — практические конфигурации Nginx/Apache.
- [Безопасность HTTP в продакшене](../../Networking/Protocols/HTTP/http_security_hardening.md) — WAF, ModSecurity, NAXSI и диагностика.
- [Руководство по безопасности Nginx и Angie](../../WebServers/Nginx/Security/nginx_security_guide.md) — модные заголовки, включая CSP `strict-dynamic`.

### Внешние ресурсы
- [OWASP XSS Prevention Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Cross_Site_Scripting_Prevention_Cheat_Sheet.html)
- [MDN: Content Security Policy](https://developer.mozilla.org/en-US/docs/Web/HTTP/CSP)
- [Cure53 XSS Payload List](https://github.com/cure53/XSSPayloads) — для тестирования фильтров.
