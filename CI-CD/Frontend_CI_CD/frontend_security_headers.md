# Security-заголовки и CSP для статики (фронтенд-деплой)

## Определения

- **CSP (Content-Security-Policy)** — заголовок, ограничивающий источники скриптов, стилей, подключений; главная защита от XSS и внедрения кода.
- **HSTS (HTTP Strict Transport Security)** — заголовок, принудительно переводящий соединение на HTTPS и защищающий от downgrade-атак.
- **X-Frame-Options / Frame-Options** — защита от clickjacking (встраивания в `<iframe>`).
- **X-Content-Type-Options: nosniff** — запрет MIME-sniffing (подмена типа файла).
- **Referrer-Policy** — контроль утечки URL через заголовок `Referer`.
- **Permissions-Policy** — ограничение доступа к браузерным API (geolocation, camera, clipboard).
- **Nonce / Hash** — механизмы CSP для разрешения инлайн-скриптов: случайное значение на запрос (`nonce`) или хэш содержимого (`sha256-...`).

---

## Требования к окружению

Для корректной работы security-заголовков в пайплайне и production необходимы:

- **HTTPS/TLS termination:** Все security-заголовки (HSTS, CSP `upgrade-insecure-requests`) работают только на HTTPS. TLS завершается на reverse proxy (nginx/Angie/Traefik). Сертификат должен быть валидным; для staging допускается `localhost` или внутренний CA.
- **Reverse proxy / CDN:** Заголовки выставляются на edge/reverse proxy, а не в бандле. CDN должен корректно пробрасывать mutable заголовки (`sw.js`, `index.html`) без агрессивного кэширования. Подробнее — в **[Reverse proxy и балансировка для фронтенда](./frontend_reverse_proxy.md)**.
- **Node.js LTS:** Для сборки бандла, SSR-рендеринга (nonce) и playwright-тестов. Версия должна быть зафиксирована в `.nvmrc` / `engines`.
- **Сервер выдачи статики:** Должен поддерживать `add_header always` (nginx/Apache) или middleware (Traefik), чтобы заголовки присутствовали даже на error-ответах (4xx/5xx).
- **Тестовое окружение с браузером:** Playwright/Puppeteer в CI для проверки заголовков, CSP-нарушений и офлайн-режима.

---

## Основные концепции

### Зачем это в задаче фронтенд-деплоя
Защитные заголовки выставляются на **уровне выдачи** (nginx / CDN / балансировщик), то есть это задача деплоя и конфигурации сервера, а не кода. Фронтенд-инженер обязан знать, как заголовки влияют на его бандл (особенно CSP на инлайн-скрипты и inline-стиль).

### Проблема инлайн-скриптов и CSP
Строгий CSP (`default-src 'self'`) запрещает любые инлайн-скрипты (`<script>...</script>`). Варианты:
- **Nonce (для SSR):** сервер генерирует случайное значение на каждый ответ и добавляет `nonce="..."` в теги скриптов и в заголовок CSP. Требует динамической генерации HTML.
- **Hash (для статики):** хэш содержимого инлайн-скрипта известен на этапе сборки и прописывается в CSP (`'sha256-...'`). Подходит для SSG/статики, где HTML фиксирован.
- **Рекомендация:** выносить весь JS в отдельные файлы (хэшированные чанки) и использовать `'self'`, избегая инлайна — это самый простой и безопасный путь.

### HSTS и поддомены
`Strict-Transport-Security: max-age=63072000; includeSubDomains; preload` — но `preload` необратим без удаления из списка; включайте только если уверены, что все поддомены работают по HTTPS.

### Trade-off (Компромисс)
Слишком строгий CSP ломает легитимные скрипты (аналитика, сторонние виджеты). Подход: начать с `Content-Security-Policy-Report-Only` + сбор нарушений в CI/мониторинг, затем ужесточать.

### Где выставляются заголовки
Иерархия применения (от первого до последнего):

1. **CDN/Edge** — первый хоп; здесь ставятся HSTS, CSP, CORS. CDN может кэшировать заголовки, поэтому для mutable ассетов (`index.html`, `sw.js`) нужно `Cache-Control: no-cache`.
2. **Reverse proxy (nginx/Angie/Traefik)** — терминация TLS, финальная сборка заголовков, логирование нарушений. Заголовки должны добавляться с `always` (nginx `add_header ... always;`), иначе они теряются на error-ответах.
3. **Приложение (SSR)** — динамические заголовки (`nonce`, `report-to`) пробрасываются через middleware на уровне фреймворка (Next.js, Nuxt).

### Взаимодействие CSP с другими фронтенд-механизмами
- **Service Worker:** `script-src` должен разрешать `sw.js`. При использовании nonce/hash-based CSP добавьте исключение для `sw.js` или используйте `strict-dynamic` с корректным nonce. Детали — в **[Service Worker и PWA](./service_worker_pwa_cicd.md)**.
- **Mutable vs Immutable ассеты:** `sw.js` и `index.html` — mutable, их нельзя кэшировать агрессивно. Хэшированные чанки (`app.a3f92bc1.js`) — immutable, можно `max-age=31536000, immutable`.
- **Trusted Types и strict-dynamic:** Для защиты от DOM-based XSS используйте `strict-dynamic` в `script-src` вместе с nonce. Полная теория и конфигурация — в **[XSS и CSP](../../Security/ApplicationSecurity/xss_and_csp.md)**.

### Устаревшие заголовки
- **`X-XSS-Protection`** — legacy-заголовок для старых браузеров (Chrome, Safari). В 2026 году актуален только как fallback; основная защита — CSP + Trusted Types.
- **`X-Download-Options: noopen`** — устарел, актуален только для IE.

---

## Практические сценарии

### Сценарий 1: Базовый набор заголовков в nginx
```nginx
server {
    add_header Strict-Transport-Security "max-age=63072000; includeSubDomains" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;
    add_header Permissions-Policy "geolocation=(), camera=(), microphone=()" always;
    add_header Content-Security-Policy "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'" always;
}
```

### Сценарий 2: CSP с nonce для SSR (Next.js)
```javascript
// На сервере генерируем nonce и пробрасываем в HTML + заголовок
const nonce = crypto.randomBytes(16).toString('base64')
res.setHeader('Content-Security-Policy', `script-src 'self' 'nonce-${nonce}'`)
// В шаблоне: <script nonce={nonce} src="/assets/app.abc.js"></script>
```

### Сценарий 3: Проверка заголовков в пайплайне
```yaml
security_headers_check:
  stage: test
  script:
    - |
      H=$(curl -sI https://preview.example.com | grep -i content-security-policy)
      if [ -z "$H" ]; then echo "CSP missing"; exit 1; fi
      echo "$H" | grep -q "default-src 'self'" || { echo "CSP too weak"; exit 1; }
```

### Сценарий 4: CSP Report-Only и сбор нарушений
```nginx
add_header Content-Security-Policy-Report-Only "default-src 'self'; report-uri /csp-report" always;
```
```javascript
// Эндпоинт /csp-report собирает нарушения и шлёт в мониторинг (Sentry/self-hosted)
```

### Сценарий 5: Строгая CSP для статики с hash
```nginx
# Для SSG/статики: хэш инлайн-скрипта прописывается на этапе сборки
add_header Content-Security-Policy "default-src 'self'; script-src 'self' 'sha256-abc123...'; style-src 'self' 'sha256-def456...'; img-src 'self' data:; connect-src 'self'" always;
```

### Сценарий 6: Валидация заголовков в production (curl)
```bash
# Проверяем наличие и значения ключевых заголовков
curl -sI https://example.com/ | grep -i -E "strict-transport|x-frame|x-content-type|referrer-policy|permissions-policy|content-security-policy"
# → Strict-Transport-Security: max-age=63072000; includeSubDomains
# → X-Frame-Options: SAMEORIGIN
# → X-Content-Type-Options: nosniff
# → Referrer-Policy: strict-origin-when-cross-origin
# → Permissions-Policy: geolocation=(), camera=(), microphone=()
# → Content-Security-Policy: default-src 'self'; ...

# Проверяем mutable ассеты (sw.js, index.html) — не должны кэшироваться агрессивно
curl -sI https://example.com/sw.js | grep -i cache-control
# → Cache-Control: no-cache

# Проверяем хэшированные чанки — должны быть immutable
curl -sI https://example.com/assets/app.a3f92bc1.js | grep -i cache-control
# → Cache-Control: public, max-age=31536000, immutable
```

### Сценарий 7: Аварийный откат CSP (hotfix)
```bash
# 1. Временно отключаем CSP enforce, оставляя Report-Only
ssh deploy@origin "sed -i 's/add_header Content-Security-Policy/add_header Content-Security-Policy-Report-Only/' /etc/nginx/conf.d/security-headers.conf"
nginx -s reload

# 2. После фикса нарушений в бандле — возвращаем enforce
ssh deploy@origin "sed -i 's/add_header Content-Security-Policy-Report-Only/add_header Content-Security-Policy/' /etc/nginx/conf.d/security-headers.conf"
nginx -s reload
```

---

## Валидация

### В пайплайне
- **Наличие заголовков:** Сценарий 3 — проверяем, что CSP присутствует и содержит `default-src 'self'`. Добавьте аналогичные проверки для HSTS, `X-Frame-Options`, `X-Content-Type-Options`.
- **CSP integrity:** Если используется nonce, проверьте, что nonce в HTML совпадает с заголовком CSP (end-to-end test).
- **Отсутствие `unsafe-inline`:** Автоматическая проверка, что в production CSP нет `'unsafe-inline'` в `script-src` (кроме обоснованных случаев с `'sha256-...'`).
- **Mutable assets:** Проверка, что `sw.js` и `index.html` имеют `Cache-Control: no-cache` или `max-age=0, must-revalidate`.

### В production
- **HSTS:** `curl -I https://example.com/ | grep -i strict-transport` → должен присутствовать с `max-age >= 63072000`.
- **CSP enforce:** Заголовок `Content-Security-Policy` должен присутствовать на всех ответах (включая error-страницы). `Content-Security-Policy-Report-Only` — только на preview-средах.
- **X-Frame-Options / frame-ancestors:** `X-Frame-Options: SAMEORIGIN` или `frame-ancestors 'self'` в CSP.
- **Referrer-Policy:** `strict-origin-when-cross-origin` или строже.
- **Permissions-Policy:** Отключены ненужные API (камера, геолокация, микрофон).
- **Mixed content:** Никакие ресурсы не должны грузиться по HTTP на HTTPS-странице. Проверка: `curl -s https://example.com/ | grep -i "http://"` — должно быть пусто.

---

## Наблюдаемость

- **CSP violations:** Настройте эндпоинт `/csp-report` и логирование в файл/ SIEM. Анализ топ-10 заблокированных источников: `grep -oP '"blocked-uri":"[^"]*"' /var/log/nginx/csp_violations.log | sort | uniq -c | sort -rn | head -20`.
- **RUM-метрики:** Тегируйте события `csp.violation`, `security_header.missing` версией деплоя. Детали — в **[SLO/SLI и RUM для фронтенда](./frontend_slo_rum.md)**.
- **Алерты:** Всплеск CSP-нарушений (>3σ от среднего) указывает на либо сломанный деплой, либо атаку XSS. Настройте алерт в Prometheus/Grafana.
- **Логирование:** Security-логи (CSP violations, XSS payloads) должны идти в отдельный log-файл или stream, доступный для SIEM (Elasticsearch/Loki/Graylog).

---

## Операции и команды

### Быстрые проверки
```bash
# Полный аудит заголовков
curl -sI https://example.com/ | grep -i -E "strict-transport|x-frame|x-content-type|referrer|permissions|content-security"

# Проверка HSTS preload eligibility
curl -sI https://example.com/ | grep -i "strict-transport"
# → max-age=63072000; includeSubDomains; preload

# Проверка mixed content
curl -s https://example.com/ | grep -iE "src=['\"]http://|href=['\"]http://"
# → (пусто) — mixed content отсутствует

# Проверка, что error-страницы тоже имеют заголовки
curl -sI https://example.com/nonexistent | grep -i -E "x-frame|x-content-type|strict-transport"
# → заголовки присутствуют (add_header always работает)
```

### Откат и hotfix
```bash
# Переключение на Report-Only при всплеске CSP-нарушений
nginx -s reload  # после изменения конфига

# Возврат к предыдущей версии конфига (если управляется через Git)
cd /etc/nginx/conf.d && git checkout HEAD~1 -- security-headers.conf && nginx -s reload
```

---

## Особые случаи

- **Error-ответы:** Без `always` (nginx) заголовки теряются на 4xx/5xx. Проверьте `curl -I https://example.com/nonexistent` — заголовки должны присутствовать.
- **Subdomains:** HSTS с `includeSubDomains` ломает поддомены без TLS. Используйте отдельный заголовок для поддоменов или убедитесь, что все поддомены имеют валидный TLS.
- **CDN/Edge кэширование:** CDN может кэшировать заголовки. Для mutable ассетов (`index.html`, `sw.js`) установите `Cache-Control: no-cache`. Для immutable хэшированных чанков — `immutable`.
- **Mixed content:** На HTTPS-странице любой HTTP-ресурс (`<img src="http://...">`, `fetch('http://...')`) блокируется браузером и ломает страницу. Используйте относительные URL или `https://`.
- **Third-party origins:** Для аналитики, CDN, payment-виджетов добавьте их домены в соответствующие директивы CSP (`img-src`, `script-src`, `connect-src`, `frame-src`). Начинайте с Report-Only, чтобы собрать все нарушения.
- **Service Worker:** `sw.js` — исполняемый скрипт с правами на весь origin. CSP `script-src` должен разрешать его. Если используете SRI для `sw.js`, добавьте соответствующий `sha256-...` в CSP.
- **Legacy браузеры:** `X-XSS-Protection` и `X-Content-Type-Options: nosniff` нужны для старых движков. В 2026 году актуально для IE11 и старых in-app браузеров.
- **CORS + CSP:** `Access-Control-Allow-Origin` — отдельный заголовок от CSP. Не путайте: CORS разрешает кросс-доменные запросы, CSP ограничивает источники ресурсов. Оба должны быть настроены для корректной работы шрифтов/API.

---

## Лучшие практики

1. Всегда `always` у `add_header`, иначе заголовки теряются на error-ответах.
2. Для статики избегайте инлайн-скриптов — выносите в хэшированные файлы и используйте `'self'`.
3. Внедряйте CSP через `Report-Only`, собирайте нарушения, затем ужесточайте.
4. `X-Frame-Options` → предпочтительнее современный `frame-ancestors` внутри CSP.
5. `sw.js` и `index.html` — mutable: `Cache-Control: no-cache`. Хэшированные чанки — immutable.
6. HSTS с `preload` только после подтверждения, что все поддомены на HTTPS; иначе используйте `max-age=63072000; includeSubDomains` без `preload`.
7. `X-XSS-Protection` — legacy fallback; основная защита — CSP + Trusted Types.
8. Проверяйте заголовки в CI (Сценарий 3) для preview и production.
9. Настройте `/csp-report` эндпоинт и логирование violations для SIEM.
10. После каждого релиза проверяйте CSP в production: `curl -I` + анализ логов violations.
11. Для CDN/third-party скриптов используйте `strict-dynamic` + nonce вместо `unsafe-inline`.
12. Документируйте exceptions (`unsafe-inline` для легитимных случаев, third-party origins) в runbook.

---

## Типичные проблемы

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| Сломался JS после включения CSP | Инлайн-скрипты запрещены | Nonce (SSR) или hash (статика), либо вынос в файлы |
| HSTS ломает поддомен | Не все поддомены на HTTPS | Убрать `includeSubDomains` или перевести поддомены на TLS |
| Clickjacking | Нет X-Frame-Options | `X-Frame-Options: SAMEORIGIN` / `frame-ancestors 'self'` |
| Утечка URL через Referer | Нет Referrer-Policy | `strict-origin-when-cross-origin` |
| Заголовки пропали на error-страницах | Нет `always` у `add_header` | Добавить `always` в nginx / использовать middleware в Traefik |
| Mixed content ломает страницу | HTTP-ресурсы на HTTPS-странице | Заменить на относительные URL или HTTPS |
| `sw.js` не обновляется | `sw.js` закэширован агрессивно | `Cache-Control: no-cache` + инвалидация в CDN |
| CSP ломает аналитику/виджеты | Домен не в allowlist | Добавить домен в `connect-src` / `img-src` / `script-src` |
| `unsafe-inline` в production | Легаси-код или CMS | Перевести на nonce/hash; если нельзя — обосновать исключение и мониторить |
| CSP Report-Only не доставляется | `report-uri` недоступен или CORS блокирует | Проверить сетевую доступность эндпоинта, добавить CORS для `/csp-report` |

---

## Дополнительная информация

### См. также

- **[Межсайтовый скриптинг (XSS) и CSP](../../Security/ApplicationSecurity/xss_and_csp.md)** — директивы CSP Level 3, Trusted Types, strict-dynamic, fail2ban-интеграция, Prometheus-алерты.
- **[Reverse proxy и балансировка для фронтенда](./frontend_reverse_proxy.md)** — размещение заголовков в инфраструктуре, TLS-терминация, mutable/immutable кэширование.
- **[Инцидент-респонс для фронтенда](./frontend_incident_response.md)** — runbook для CSP break, mixed content и застрявшего SW.
