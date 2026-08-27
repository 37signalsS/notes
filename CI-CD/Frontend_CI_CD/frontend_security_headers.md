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

---

## Дополнительная информация

### Лучшие практики
1. Всегда `always` у `add_header`, иначе заголовки теряются на error-ответах.
2. Для статики избегайте инлайн-скриптов — выносите в хэшированные файлы и используйте `'self'`.
3. Внедряйте CSP через `Report-Only`, собирайте нарушения, затем ужесточайте.
4. `X-Frame-Options` → предпочтительнее современный `frame-ancestors` внутри CSP.
5. Проверяйте заголовки автоматически в CI (Сценарий 3) для каждого превью-окружения.

### Типичные проблемы
| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| Сломался JS после включения CSP | Инлайн-скрипты запрещены | Nonce (SSR) или hash (статика), либо вынос в файлы |
| HSTS ломает поддомен | Не все поддомены на HTTPS | Убрать `includeSubDomains` или перевести поддомены на TLS |
| Clickjacking | Нет X-Frame-Options | `X-Frame-Options: SAMEORIGIN` / `frame-ancestors 'self'` |
| Утечка URL через Referer | Нет Referrer-Policy | `strict-origin-when-cross-origin` |

### См. также
- **[Управление секретами](../DevSecOps/secrets_management.md)** — что нельзя бейкить в бандл.
- **[Reverse proxy и балансировка для фронтенда](./frontend_reverse_proxy.md)** — где размещать заголовки.
- **[DevSecOps: обзор](../DevSecOps/devsecops_overview.md)** — место CSP в цепочке безопасности.
- **[SLO/SLI и RUM для фронтенда](./frontend_slo_rum.md)** — безопасность как часть надёжности.
