# Микро-фронтенды и Module Federation в CI/CD

## Определения

- **Микро-фронтенд (Micro-Frontend, MFE)** — архитектурный подход, при котором фронтенд-приложение разбивается на независимо разрабатываемые, тестируемые и деплоящиеся части (микро-приложения), объединяемые в единый пользовательский интерфейс.
- **Module Federation** — механизм (встроен в Webpack 5 / доступен в Rspack / экспериментально в Vite) для загрузки кода одного билда («remote») внутрь другого («host») в runtime, без дублирования общих зависимостей.
- **Host (Shell/Container) приложение** — «оболочка», которая монтирует удалённые микро-фронтенды и отвечает за навигацию и layout.
- **Remote приложение** — микро-фронтенд, публикуемый как независимый модуль с заданной точкой входа (`exposes`).
- **Shared dependency (singleton)** — общая библиотека (например, React), которую Module Federation загружает ровно один раз и делит между всеми микро-фронтендами.
- **Контракт интеграции (Integration Contract)** — соглашение о версиях remote-модулей и их API, по которому host и remote остаются совместимыми при независимом деплое.

---

## Основные концепции

### Зачем это нужно в продакшене
Основная ценность — **независимый деплой команд**. Разные команды выкатывают свои микро-фронтенды без координации релиза всего монолитного SPA. Это сокращает Lead Time и сужает blast radius (радиус поражения) при ошибке.

### Модели композиции
- **Runtime-композиция (Module Federation):** код подгружается в браузере в момент работы приложения. Требует аккуратного управления версиями shared-зависимостей.
- **Build-time композиция (монорепо + единая сборка):** проще по совместимости, но теряется независимый деплой.
- **Iframe / Web Components:** изоляция по стандарту, но тяжелее по UX и производительности.

### Версии и совместимость
Главный риск микро-фронтендов — **version skew**: host ожидает API remote версии N, а задеплоена версия N+1 с изменённым контрактом. Смягчается:
- Фиксацией контракта и **contract testing** (Pact) между host и remote.
- Использованием `singleton: true` для shared-библиотек, чтобы не было двух копий React.
- Версионированием эндпоинтов remote (например, `https://remotes.example.com/cart/v12/remoteEntry.js`).

### Чем отличается CI от монолитного SPA
- Каждый remote собирается и **публикуется как отдельный артефакт** (remoteEntry + assets) под своей версией.
- Host не пересобирается при деплое remote (иначе теряется смысл), но должен знать, какую версию remote подгружать (через конфиг/манifest).
- Кэширование: имя `remoteEntry.js` тоже должно быть хэшировано или версионировано, иначе браузер отдаст старый модуль.

### Требования к окружению

Для продакшен-пайплайна микро-фронтендов необходимы:
- **Node.js LTS (v20+):** версия должна быть зафиксирована в `.nvmrc` / `engines` и совпадать в CI и на серверах shell/remote. Module Federation чувствителен к разным версиям `webpack`/`rspack` между host и remote.
- **Module Federation plugin:** для Webpack 5 (`webpack-container-plugin`), Rspack (`@module-federation/rspack`) или Vite (`@module-federation/vite`). Выбор инструмента — архитектурное решение, не меняйте его без пересборки всех контейнеров.
- **Хранилище артефактов remote:**Origin (S3-compatible/MinIO, Nexus, файловый сервер) для `remoteEntry.js` + ассеты с версионированными путями.
- **Reverse proxy / CDN:** выдача `remoteEntry.js` с заголовком `Cache-Control: no-cache` (браузер должен проверять актуальность манифеста) или с версионированным путём + `immutable`.
- **Contract testing:** Pact broker или аналогичный сервис для хранения контрактов и проверки `can-i-deploy`. Может быть self-hosted.
- **Runtime-конфигурация host:** источник URL remote-модулей (environment variables, feature flag service, конфиг-сервис), по которому host определяет, какой remoteEntry загружать.
- **Мониторинг:** метрики загрузки remoteEntry (время, ошибки 4xx/5xx), JS Error Rate, RUM для каждого микро-фронтенда отдельно.

---

## Практические сценарии

### Сценарий 1: Конфигурация Module Federation (Vite/Rspack)
```javascript
// vite.config.ts (плагин @module-federation/vite)
import { moduleFederation } from '@module-federation/vite'
export default {
  plugins: [
    moduleFederation({
      name: 'cart',
      filename: 'remoteEntry.js',
      exposes: { './CartWidget': './src/CartWidget.jsx' },
      shared: { react: { singleton: true }, 'react-dom': { singleton: true } },
    }),
  ],
}
```
# → сборка выдаёт `dist/assets/remoteEntry.js` + чанки с хэшами

### Сценарий 2: Per-remote пайплайн (сборка + публикация версии)
```yaml
build_remote_cart:
  image: node:22-bookworm
  script:
    - npm ci && npm run build
    - VERSION=$(node -p "require('./package.json').version")
    # Публикуем remoteEntry + assets по версионированному пути
    - rsync -az dist/ deploy@cdn-origin:/srv/remotes/cart/v${VERSION}/
    - echo "CART_REMOTE_URL=https://cdn.example.com/remotes/cart/v${VERSION}/remoteEntry.js" > remote_url.env
  artifacts:
    reports:
      dotenv: remote_url.env
```
# → артефакт `remote_url.env` содержит URL актуального remoteEntry для host

### Сценарий 3: Host подгружает remote по версионированному URL
```javascript
// В host-приложении URL remote берётся из конфигурации среды (runtime),
// а не запечатывается в билд — так деплой remote не требует пересборки host.
const remoteUrl = window.__APP_CONFIG__.cartRemoteUrl
__webpack_init_federation__(remoteUrl)
```
# → при изменении `cartRemoteUrl` host подгружает новую версию remote без пересборки

### Сценарий 4: Contract testing между host и remote
```bash
# Pact: remote публикует контракт, host проверяет совместимость перед деплоем
npx pact publish ./pacts --broker-base-url $PACT_BROKER
npx pact can-i-deploy --pacticipant cart-remote --version $CART_VER --to-environment production
```
# → `can-i-deploy` возвращает 0 при отсутствии-breaking изменений, иначе пайплайн остановлен

### Сценарий 5: Откат remote
Откат = переключение `cartRemoteUrl` в конфиге host на предыдущую версию (через feature flag или обновление manifest), либо инвалидация CDN и возврат старого каталога `v11`. Полной пересборки не требуется.
# → откат выполняется за секунды, не зависит от доступности CI

---

## Дополнительная информация

### Лучшие практики
1. Всегда делайте shared-зависимости `singleton`, чтобы не плодить копии React/Vue.
2. Версионируйте эндпоинты remote и храните актуальный URL в runtime-конфиге host.
3. Изолируйте сбои remote через error boundary — упавший микро-фронтенд не должен ложить весь shell.
4. Автоматизируйте contract testing, иначе version skew вскроется только в проде.
5. Мониторьте загрузку remoteEntry (время, ошибки) как отдельную метрику RUM.
6. Храните минимум 3–5 последних версий remote для мгновенного отката; удаляйте старые каталоги по cron или post-deploy хуком.
7. Отдавайте `remoteEntry.js` с `Cache-Control: no-cache` (проверка актуальности манифеста) или версионируйте путь и используйте `immutable` только на хэшированных чанках.
8. Для отката используйте feature flag или переключение URL в runtime-конфиге — это быстрее и безопаснее, чем пересборка host.

### Типичные проблемы
| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| Две копии React (хуки ломаются) | Shared не помечен `singleton` | `shared: { react: { singleton: true } }` |
| Host видит старый remote | Браузер закэшировал `remoteEntry.js` | Версионируйте путь (`/cart/v12/`) + `immutable` только на хэшированные чанки |
| Рассинхрон контракта | Деплой remote без проверки host | Pact `can-i-deploy` в пайплайне remote |
| Медленный старт shell | Тяжёлые remote грузятся синхронно | Ленивая загрузка (dynamic `import()`) remote-модулей |
| Version skew (API remote изменился) | Деплой remote без обновления host | Contract testing + semantic versioning remote API |
| Ошибка загрузки remoteEntry (404/500) | Неверный путь, файл не опубликован | Проверка доступности URL в CI (`curl -fsS $REMOTE_URL`) |
| Конфликт версий shared-зависимостей | Host и remote используют разные минорные версии | Фиксируйте версии в `package.json`, используйте `singleton: true` + `strictVersion: true` |
| Shell как SPOF | Падение shell ломает все remotes | Мониторинг shell отдельно, быстрый fallback на статическую страницу |

### Особые случаи

- **Version skew без contract testing:** при изменении props/events в remote-компоненте host может упасть с `undefined is not a function`. Решение: семантическое версионирование remote API + Pact broker + `can-i-deploy` в пайплайне. Для SSR-remote добавляйте smoke test на стороне host после деплоя.
- **Ошибки сети при загрузке remote:** при 5xx/CDN-отказе remoteEntry не загрузится, и shell останется без модуля. Используйте `import()` с таймаутом и fallback-UI (`Suspense` + error boundary). Кэшируйте `remoteEntry.js` на edge с коротким TTL.
- **Shared dependency с разными минорными версиями:** `react` 18.2 и 18.3 могут совместно работать, но `react-dom` 18.x и 19.x — нет. Фиксируйте точные версии в `package.json` обоих проектов, используйте `strictVersion: true` в Module Federation shared-конфиге.
- **SSR в remote-микро-фронтендах:** remote может быть SSR-приложением (Next.js/Nuxt), тогда `remoteEntry.js` — только точка входа для клиентского бандла, а серверная часть деплоится отдельно. Документируйте этот контракт, иначе команда host ожидает client-only модуль.
- **Кэширование remoteEntry на CDN:** `remoteEntry.js` содержит manifest с путями к чанкам. Если его закэшировать на long TTL, host не увидит новые чанки. Используйте `Cache-Control: no-cache` для `remoteEntry.js` (браузер запросит, но CDN может ответить 304) или версионируйте путь и используйте `immutable` только на хэшированных чанках.
- **Миграция с Module Federation на другой подход:** при переходе на monorepo или iframe-изоляцию деплой remote ломает host. Планируйте миграцию как feature flag: параллельно запускайте новую и старую стратегию, затем выключайте старую. Детали миграции — в **[Монорепо CI для фронтенда](./monorepo_frontend_ci.md)**.

### См. также
- **[Монорепо CI для фронтенда](./monorepo_frontend_ci.md)** — когда несколько микро-фронтендов живут в одном репозитории.
- **[Специфические задачи Frontend CI/CD](./frontend_pipeline_specifics.md)** — Cache Busting, инвалидация CDN, атомарный деплой и артефакты, применимые и к remote-чанкам.
- **[Feature flags в доставке фронтенда](./feature_flags_frontend.md)** — переключение версий remote без пересборки, kill switch.
