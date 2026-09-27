# Service Worker и PWA в пайплайне деплоя

## Определения

- **Service Worker (SW)** — скрипт, работающий в фоне браузера, перехватывающий сетевые запросы и управляющий кэшем (Cache Storage API). Основа PWA и офлайн-режима.
- **PWA (Progressive Web App)** — веб-приложение, использующее SW, манифест и https для нативно-подобного опыта (офлайн, установка, пуши).
- **Precaching** — предварительное кэширование критических ресурсов (App Shell) на этапе `install` SW.
- **Runtime caching** — стратегии обработки запросов в момент `fetch` (cache-first, network-first, stale-while-revalidate).
- **skipWaiting / clients.claim** — API SW для немедленного применения нового SW ко всем вкладкам без ожидания их закрытия.
- **App Shell** — минимальный HTML/CSS/JS-каркас, отдаваемый мгновенно из SW-кэша.

---

## Требования к окружению

Для работы SW в пайплайне и production необходимы:

- **Secure context (HTTPS):** SW регистрируется только на `https://` или `http://localhost`. На staging/dev используйте localhost или самоподписанные сертификаты; в production — валидный TLS.
- **Node.js LTS:** для сборки Workbox-генерируемого SW, бандлеров и playwright-тестов. Версия должна быть зафиксирована в `.nvmrc` / `engines` и совпадать в CI и локально.
- **Reverse proxy / CDN:** должен корректно обрабатывать mutable ассеты (`sw.js`, `index.html`) без агрессивного кэширования. Подробнее — в **[Reverse proxy и балансировка для фронтенда](./frontend_reverse_proxy.md)**.
- **Тестовое окружение с браузером:** Playwright/Puppeteer в CI для проверки офлайн-режима, регистрации SW и жизненного цикла.
- **Хранилище артефактов:** `sw.js` и precache-манифест должны публиковаться как артефакты сборки и версионироваться по хэшу коммита/сборки.

---

## Основные концепции

### Жизненный цикл SW и обновление
SW проходит фазы `install` → `waiting` → `activate`. Новый SW не активируется, пока старый «висит» на открытых вкладках (фаза `waiting`). Без `skipWaiting` пользователь продолжает получать старый SW до перезагрузки всех вкладок.

### Координация SW с Cache Busting
Хэшированные ассеты (`app.a3f92bc1.js`) кэшируются по точному URL — это хорошо. Но **SW-кэш сам должен версионироваться**: precache-манifest должен ссылаться на актуальные хэши сборки. Если SW остался старым, он продолжит отдавать старые хэшированные файлы, даже когда на сервере лежат новые.

### Проблема «застрявшего» SW после деплоя
Классический инцидент: выложили новый бандл, но пользователь видит старый UI, потому что:
1. Старый SW ещё не обновился (`waiting`), либо
2. Старый SW закэшировал старые хэши и отдаёт их из `cache-first`, игнорируя новые файлы на сервере.

Решения:
- Версионировать имя кэша SW по хэшу сборки (`cacheName = 'app-v' + BUILD_HASH`).
- При `activate` удалять устаревшие кэши (`caches.keys().filter(k => k !== current)`).
- Использовать `skipWaiting()` + `clients.claim()` для быстрого применения, либо показывать баннер «доступна новая версия, перезагрузите».
- Никогда не кэшировать `index.html` как `cache-first` без revalidation — иначе SW раздаёт старый HTML, ссылающийся на старые чанки.

### Стратегии кэширования
- **Cache-first** — для хэшированных ассетов (безопасно, URL уникален).
- **Network-first / SWR** — для `index.html` и API (свежесть важнее).
- **Stale-while-revalidate** — для часто меняющихся, но некритичных данных.

### Безопасность и ограничения
- **HTTPS requirement:** SW работает только на secure context. На production это означает валидный сертификат; на development — `localhost`.
- **Scope ограничение:** SW зарегистрированный на `/app/` не перехватывает запросы к `/other/`. Scope определяется при регистрации (`navigator.serviceWorker.register('/sw.js', {scope: '/app/'})`) и должен покрывать все нужные маршруты.
- **Subresource Integrity (SRI):** `sw.js` — это исполняемый скрипт с правами на весь origin. Рекомендуется SRI-хеш для `sw.js`, чтобы защититься от отравления кэша/CDN.
- **CSP:** `script-src` должен разрешать `sw.js`. Если используется `nonce-` или `hash-`based CSP, добавьте исключение для `sw.js` или используйте `strict-dynamic` с корректным nonce.
- **Mutable assets:** `sw.js` и `index.html` никогда не должны кэшироваться агрессивно (`Cache-Control: no-cache`), иначе пользователь получит старый SW из CDN. Хэшированные чанки — наоборот, `immutable`.
- **Квоты хранилища:** Cache Storage API имеет практические лимиты (обычно процент от диска, например 50%). Большие precache-манифесты или нескончаемый runtime-кэш могут быть удалены браузером при нехватке места. Следите за `caches.keys().then(names => names.map(name => caches.open(name).then(cache => cache.matchAll()).then(...)))` для аудита.

---

## Практические сценарии

### Сценарий 1: Генерация SW на этапе сборки (Workbox)
```javascript
// workbox-config.js
module.exports = {
  globDirectory: 'dist/',
  globPatterns: ['**/*.{js,css,html,png,svg,woff2}'],
  // Префикс кэша, включающий хэш сборки (прокидывается из CI)
  cacheId: `app-${process.env.BUILD_HASH}`,
  runtimeCaching: [{
    urlPattern: /\/api\//,
    handler: 'NetworkFirst',
    options: { cacheName: 'api', networkTimeoutSeconds: 3 },
  }],
}
```
```bash
# В пайплайне
BUILD_HASH=$(git rev-parse --short HEAD) npx workbox generateSW workbox-config.js
```

### Сценарий 2: Автоматическое применение обновления
```javascript
// register.js (в проде)
navigator.serviceWorker.register('/sw.js').then(reg => {
  reg.addEventListener('updatefound', () => {
    const newSw = reg.installing
    newSw.addEventListener('statechange', () => {
      if (newSw.state === 'installed' && navigator.serviceWorker.controller) {
        // Уведомить пользователя или сделать skipWaiting
        newSw.postMessage({ type: 'SKIP_WAITING' })
      }
    })
  })
})
// В sw.js: self.addEventListener('message', e => e.data?.type === 'SKIP_WAITING' && self.skipWaiting())
```

### Сценарий 3: Проверка целостности precache в CI
```bash
# Проверяем, что сгенерированный sw.js ссылается только на существующие в dist файлы
node -e "
const fs=require('fs');const sw=fs.readFileSync('dist/sw.js','utf8');
const refs=[...sw.matchAll(/\"([^\"]+\.(js|css|png))\"|'([^\']+\.(js|css|png))'/g)].map(m=>m[1]||m[3]);
const missing=refs.filter(f=>!fs.existsSync('dist/'+f));
if(missing.length){console.error('SW references missing assets:',missing);process.exit(1);}
"
```

### Сценарий 4: Тестирование SW в пайплайне (Playwright)
```yaml
test_sw:
  image: mcr.microsoft.com/playwright:v1.49.0-noble
  script:
    - npx playwright test --grep @service-worker
```
```javascript
// Тест: офлайн-режим отдаёт App Shell из кэша
test('works offline', async ({ context }) => {
  const page = await context.newPage()
  await page.goto('/')
  await context.setOffline(true)
  await page.reload()
  await expect(page.locator('#app')).toBeVisible()
})
```

### Сценарий 5: Валидация в production (curl + JS)
```bash
# Проверяем, что SW зарегистрирован и имеет актуальную версию кэша
curl -sS https://example.com/sw.js | grep -i "cacheId\|CACHE_VERSION\|BUILD_HASH"
# → app-a3f92bc1

# Проверяем, что sw.js не кэшируется агрессивно (должен перепроверяться)
curl -sI https://example.com/sw.js | grep -i -E "cache-control|etag"
# → Cache-Control: no-cache
# → ETag: "a3f92bc1"

# Проверяем, что CDN/edge отдаёт актуальный sw.js (не старый)
curl -sI https://cdn.example.com/sw.js | grep -i -E "cache-control|etag|age"
# → Cache-Control: no-cache
# → Age: 0 (не закэширован на edge)
```

### Сценарий 6: Аварийный откат и принудительное обновление SW
```bash
# 1. Принудительная инвалидация sw.js в CDN (если используется)
curl -X POST "$CDN/purge" -H "Auth: $TOKEN" -d '{"prefix":"/sw.js"}'

# 2. Проверка, что новые вкладки получают актуальный SW
curl -sS https://example.com/sw.js | grep -o "cacheId:[^ ]*"
# → cacheId: app-a3f92bc1

# 3. Если нужно экстренно откатить — меняем BUILD_HASH на предыдущий коммит
PREV_HASH=$(git rev-parse --short HEAD~1)
BUILD_HASH=$PREV_HASH npx workbox generateSW workbox-config.js
# Новый SW кэширует старые ассеты, которые ещё валидны
```

### Сценарий 7: Graceful reload и zero-downtime обновление SW
```javascript
// В UI: показать баннер обновления, дать пользователю подтвердить
const updateBanner = document.getElementById('update-banner')
if (updateBanner) {
  updateBanner.style.display = 'block'
  updateBanner.onclick = () => {
    window.location.reload()
  }
}
// После reload новый SW активируется, кэш обновляется
```

---

## Валидация

### В пайплайне
- **Precache integrity:** Сценарий 3 проверяет, что все ссылки в `sw.js` существуют в `dist/`. Добавьте этот скрипт как этап CI после сборки.
- **Offline smoke test:** Сценарий 4 через Playwright: открыть `/`, переключиться в offline, перезагрузить — App Shell должен отобразиться.
- **SRI check:** Если используется SRI для `sw.js`, добавьте проверку, что хэш в HTML совпадает со сгенерированным `sw.js`.

### В production
- **Регистрация:** `navigator.serviceWorker.controller` должен быть `true` после повторного визита; `navigator.serviceWorker.ready` разрешается для deferred-логики.
- **Версия кэша:** `sw.js` должен содержать актуальный `cacheId`/`BUILD_HASH`. Сравнивайте с коммитом деплоя.
- **Mutable assets:** `sw.js` и `index.html` должны иметь `Cache-Control: no-cache` (или `max-age=0, must-revalidate`). Хэшированные чанки — `immutable`.
- **Offline mode:** Вручную или через synthetics: зайти на сайт, переключиться в offline, обновить — контент должен грузиться из кэша.

---

## Наблюдаемость

- **RUM-метрики:** Тегируйте события `service_worker.registered`, `service_worker.updated`, `service_worker.cache_hit` версией `cacheId` и `deploy_version`. Детали — в **[SLO/SLI и RUM для фронтенда](./frontend_slo_rum.md)**.
- **Update adoption rate:** В приложении отправляйте метрику: `service_worker.state === 'activated' && navigator.serviceWorker.controller` — доля пользователей на новом SW. Резкий отказ от роста после деплоя указывает на застрявшие вкладки.
- **Cache hit ratio:** В runtime-логах (если используете custom runtime caching) или через `PerformanceObserver` для `resource`-type запросов, отдаваемых из SW.
- **Ошибки активации:** Логируйте `statechange` в `install`/`activate` с ошибками (`statechange` на `redundant` означает ошибку установки).

---

## Особые случаи

- **Long-lived tabs:** Пользователь с открытой вкладкой «зависнет» на старом SW, пока не закроет её. Это нормально, но с ростом числа таких вкладок adoption rate падает. Решения: `skipWaiting` + `clients.claim`, или баннер «доступна новая версия».
- **Storage quota:** Cache Storage API лимитирован (обычно 50% диска). Большой precache или нескончаемый runtime-кэш могут быть удалены. Используйте `navigator.storage.estimate()` для мониторинга.
- **Scope mismatch:** SW на `/` перехватывает всё; на `/app/` — только внутри. Убедитесь, что `scope` при регистрации покрывает все нужные маршруты, иначе запросы улетят в сеть.
- **Navigation preload:** Если используется `navigationPreload`, убедитесь, что SSR/SSG origin корректно обрабатывает `Service-Worker-Navigation-Preload` заголовок.
- **Memory limits:** Очень большой precache-манифест (тысячи записей) потребляет память при `activate`. Ограничьте прекэш критическими ресурсами; остальное — по demande или через runtime caching.
- **Browser support:** SW поддерживается во всех современных браузерах (Chrome, Edge, Firefox, Safari). Исключение: IE11 (не поддерживается) и некоторые старые in-app браузеры. Проверяйте `if ('serviceWorker' in navigator)` перед регистрацией.

---

## Лучшие практики

1. Версионируйте кэш SW по хэшу сборки и чистите старые кэши при `activate`.
2. `index.html` — только `network-first`/`SWR`, никогда `cache-first` без revalidation.
3. Хэшированные чанки — `cache-first` (по URL уникальны, можно `immutable`).
4. После деплоя инвалидируйте `sw.js` в CDN (его нельзя кэшировать агрессивно).
5. Интегрируйте проверку «SW не ссылается на отсутствующие ассеты» в CI (Сценарий 3).
6. Используйте `skipWaiting()` + `clients.claim()` для быстрого распространения критичных исправлений.
7. Для PWA добавьте Web App Manifest (`manifest.json`) с `display: standalone`, `start_url` и иконками — это отдельный артефакт сборки, который тоже нужно версионировать.
8. Применяйте SRI для `sw.js` и CSP `script-src` с allowlist, чтобы ограничить последствия компрометации.
9. `sw.js` и `index.html` должны иметь `Cache-Control: no-cache` на CDN и reverse proxy.
10. Тестируйте офлайн-режим и обновление SW в CI (Playwright) на каждом релизе.
11. Логируйте версию `cacheId` в RUM, чтобы коррелировать ошибки пользователей с версией SW.
12. Ограничьте размер precache критическими ресурсами; для остального используйте runtime caching.

---

## Типичные проблемы

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| Пользователь видит старый UI | Застрявший SW (`waiting`) | `skipWaiting` + `clients.claim` или баннер обновления |
| Белый экран после релиза | SW кэшировал старый `index.html` (cache-first) | `network-first` для HTML, версионный кэш |
| 404 на чанк в офлайне | Precached-ссылка не совпадает с dist | Проверка в CI (Сценарий 3) |
| Двойная загрузка бандла | SW и браузер кэшируют по-разному | Единая стратегия + `immutable` на хэшированные чанки |
| `sw.js` раздаётся старый из CDN | Агрессивное кэширование mutable ассета | `Cache-Control: no-cache` + инвалидация после деплоя |
| SW не обновляется после релоада | `skipWaiting` не вызван, вкладка не закрыта | Баннер обновления или `message` → `skipWaiting` |
| Офлайн не работает на Safari | Safari ограничивает SW в фоне / приватном режиме | Проверять `navigator.serviceWorker.controller` и fallback |
| Кэш переполнен | Прекэш слишком большой / runtime кэш бесконечный | Лимиты на precache, `caches.delete()` для старых, `storage.estimate()` |
| CSP блокирует SW | `script-src` не разрешает `sw.js` | Добавить `sw.js` в CSP allowlist или SRI |
| Scope не покрывает маршрут | SW зарегистрирован на `/`, а приложение на `/app/` | Увеличить `scope` или переместить `sw.js` |

---

## Дополнительная информация

### См. также

- **[Специфические задачи Frontend CI/CD](./frontend_pipeline_specifics.md)** — Cache Busting, инвалидация CDN, атомарный деплой; `sw.js` и `index.html` должны оставаться mutable.
- **[Инцидент-респонс для фронтенда](./frontend_incident_response.md)** — runbook для «застрявшего» SW и broken deploy.
- **[Reverse proxy и балансировка для фронтенда](./frontend_reverse_proxy.md)** — заголовки кэширования для mutable и immutable ассетов.
