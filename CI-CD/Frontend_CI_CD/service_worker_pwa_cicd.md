# Service Worker и PWA в пайплайне деплоя

## Определения

- **Service Worker (SW)** — скрипт, работающий в фоне браузера, перехватывающий сетевые запросы и управляющий кэшем (Cache Storage API). Основа PWA и офлайн-режима.
- **PWA (Progressive Web App)** — веб-приложение, использующее SW, манифест и https для нативно-подобного опыта (офлайн, установка, пуши).
- **Precaching** — предварительное кэширование критических ресурсов (App Shell) на этапе `install` SW.
- **Runtime caching** — стратегии обработки запросов в момент `fetch` (cache-first, network-first, stale-while-revalidate).
- **skipWaiting / clients.claim** — API SW для немедленного применения нового SW ко всем вкладкам без ожидания их закрытия.
- **App Shell** — минимальный HTML/CSS/JS-каркас, отдаваемый мгновенно из SW-кэша.

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

---

## Дополнительная информация

### Лучшие практики
1. Версионируйте кэш SW по хэшу сборки и чистите старые кэши при `activate`.
2. `index.html` — только `network-first`/`SWR`, никогда `cache-first` без revalidation.
3. Хэшированные чанки — `cache-first` (по URL уникальны, можно `immutable`).
4. После деплоя инвалидируйте `sw.js` в CDN (его нельзя кэшировать агрессивно).
5. Интегрируйте проверку «SW не ссылается на отсутствующие ассеты» в CI (Сценарий 3).

### Типичные проблемы
| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| Пользователь видит старый UI | Застрявший SW (`waiting`) | `skipWaiting` + `clients.claim` или баннер обновления |
| Белый экран после релиза | SW кэшировал старый `index.html` (cache-first) | `network-first` для HTML, версионный кэш |
| 404 на чанк в офлайне | Precached-ссылка не совпадает с dist | Проверка в CI (Сценарий 3) |
| Двойная загрузка бандла | SW и браузер кэшируют по-разному | Единая стратегия + `immutable` на хэшированные чанки |

### См. также
- **[Специфические задачи Frontend CI/CD](./frontend_pipeline_specifics.md)** — Cache Busting и инвалидация CDN, тесно связанные с SW-кэшем.
- **[Клиентское кэширование в Nginx](../../WebServers/Nginx/Performance/Caching/client_caching.md)** — заголовки `Cache-Control` под SW.
- **[Политики кэширования и инвалидации в CDN](../../Networking/CDN/cdn_caching_and_invalidation.md)** — правильная инвалидация `sw.js`.
- **[SLO/SLI и RUM для фронтенда](./frontend_slo_rum.md)** — метрики загрузки SW как часть RUM.
