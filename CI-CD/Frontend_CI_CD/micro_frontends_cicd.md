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

### Сценарий 3: Host подгружает remote по версионированному URL
```javascript
// В host-приложении URL remote берётся из конфигурации среды (runtime),
// а не запечатывается в билд — так деплой remote не требует пересборки host.
const remoteUrl = window.__APP_CONFIG__.cartRemoteUrl
__webpack_init_federation__(remoteUrl)
```

### Сценарий 4: Contract testing между host и remote
```bash
# Pact: remote публикует контракт, host проверяет совместимость перед деплоем
npx pact publish ./pacts --broker-base-url $PACT_BROKER
npx pact can-i-deploy --pacticipant cart-remote --version $CART_VER --to-environment production
```

### Сценарий 5: Откат remote
Откат = переключение `cartRemoteUrl` в конфиге host на предыдущую версию (через feature flag или обновление manifest), либо инвалидация CDN и возврат старого каталога `v11`. Полной пересборки не требуется.

---

## Дополнительная информация

### Лучшие практики
1. Всегда делайте shared-зависимости `singleton`, чтобы не плодить копии React/Vue.
2. Версионируйте эндпоинты remote и храните актуальный URL в runtime-конфиге host.
3. Изолируйте сбои remote через error boundary — упавший микро-фронтенд не должен ложить весь shell.
4. Автоматизируйте contract testing, иначе version skew вскроется только в проде.
5. Мониторьте загрузку remoteEntry (время, ошибки) как отдельную метрику RUM.

### Типичные проблемы
| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| Две копии React (хуки ломаются) | Shared не помечен `singleton` | `shared: { react: { singleton: true } }` |
| Host видит старый remote | Браузер закэшировал `remoteEntry.js` | Версионируйте путь (`/cart/v12/`) + `immutable` только на хэшированные чанки |
| Рассинхрон контракта | Деплой remote без проверки host | Pact `can-i-deploy` в пайплайне remote |
| Медленный старт shell | Тяжёлые remote грузятся синхронно | Ленивая загрузка (dynamic `import()`) remote-модулей |

### См. также
- **[Монорепо CI для фронтенда](./monorepo_frontend_ci.md)** — когда несколько микро-фронтендов живут в одном репозитории.
- **[Специфические задачи Frontend CI/CD](./frontend_pipeline_specifics.md)** — Cache Busting и инвалидация CDN, применимые и к remote-чанкам.
- **[Управление артефактами](../artifact_management.md)** — публикация и продвижение версий remote.
- **[Feature flags в доставке фронтенда](./feature_flags_frontend.md)** — переключение версий remote без пересборки.
