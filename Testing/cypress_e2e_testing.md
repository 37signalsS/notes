# E2E-тестирование с помощью Cypress

**Актуально для:** Cypress 16.x

## Определения

**Cypress** — JavaScript-фреймворк для end-to-end (E2E) и component-тестирования веб-приложений. Агрессивно отличается от классических Selenium-решений архитектурой: тест-раннер встраивается непосредственно в браузер (Chromium, Firefox, WebKit), а не общается с ним через внешний WebDriver-сервер. Актуальная мажорная версия — **Cypress 16.x** (последняя — 16.0.0, сентябрь 2026; в 16.0 HTTP/2 стал протоколом по умолчанию в Chrome/Chromium/Edge, базовый runtime — Node.js 24, удалена `Cypress.env()`).

**Spec (спека)** — файл E2E-теста (`cypress/e2e/*.cy.js`).

**Test Runner** — интерактивный интерфейс Cypress, где тесты выполняются вживую с перемоткой событий.

**Component Testing** — режим тестирования UI-компонентов (React/Vue/…) в изоляции; запускается через dev-server (Vite/Webpack), встроенный в Cypress 16.

**cy. commands** — методы объекта `cy` (например, `cy.get()`, `cy.visit()`, `cy.intercept()`), формирующие командную очередь с автоматическим ожиданием.

**Command Queue** — внутренняя очередь команд Cypress, которая выполняет `cy.`-вызовы последовательно с retry-механизмом.

**Retry-ability** — механизм автоматического повтора команд и assertion-ов до выполнения условия или `defaultCommandTimeout`.

**data-test атрибуты** — атрибуты вида `data-test="..."` в HTML, используемые в селекторах вместо CSS-классов для стабильности тестов.

**Cross-Origin** — переход между разными источниками (origins); в Cypress 12+ используется `cy.origin()` для кросс-доменных действий.

## Архитектура и принцип работы

### Как Cypress управляет браузером

Cypress работает по-другому, чем Selenium:

- **Встраивание в браузер**: тест-раннер запускает браузер (Chromium/Chrome/Edge/Firefox/Webkit) с встроенным прокси Cypress. Все `cy.`-команды исполняются в контексте страницы, а не через внешний протокол.
- **Command Queue и Event Loop**: команды не выполняются синхронно. `cy.get()` добавляет команду в очередь; Cypress извлекает её, исполняет и ждёт результата (с retry) прежде чем перейти к следующей.
- **Автоматическое ожидание**: каждая команда (и assertion) автоматически ждёт появления элемента или условия до `defaultCommandTimeout` (по умолчанию 4 сек). Это устраняет необходимость в `cy.wait(ms)`.

### Перехват и мок сетевых запросов

`cy.intercept()` — единый механизм для stub/spy на XHR и fetch-запросы:

- Мок ответов через fixtures (`{ fixture: 'price.json' }`).
- Алиасы для ожидания: `cy.intercept(...).as('alias')` → `cy.wait('@alias')`.
- Диагностика запросов в реальном времени в Test Runner (Network tab).

### Изоляция состояния

Между `it()` Cypress сбрасывает состояние (cookies, localStorage, sessionStorage) — «между тест-кейсами чистота» по умолчанию. Для кэширования сессии используется `cy.session()`.

### Отличие от Selenium

| Аспект | Cypress | Selenium WebDriver |
| :--- | :--- | :--- |
| Архитектура | Встраивается в браузер, напрямую управляет DOM | Обращение к браузеру через WebDriver-протокол |
| Асинхронность теста | Автоматическая (тест «плывёт» через retry) | Явные ожидания (WebDriverWait) |
| Скорость | Очень высокая за счёт отсутствия сетевых виттков | Зависит от драйвера; обычно медленнее |
| Установка | `npm i -D cypress` | Драйверы для каждого браузера отдельно |
| Мультибраузерность | Chrome, Chrome для Edge, Firefox, WebKit | Все браузеры (в т.ч. Safari, IE) |
| Поддержка mobile | Малый, только эмуляция viewport | Мобильные браузеры, эмуляции |

## Практические сценарии

### Сценарий 1: Установка и инициализация

**Предпосылки:**
- Node.js 22.x / 24.x (Cypress 16 требует Node.js 22+)
- npm или yarn
- Доступ к проекту с package.json

```bash
npm init -y
npm install -D cypress
npx cypress open      # первый запуск создаст структуру cypress/
```

**Валидация:**
```bash
npx cypress verify    # → успешная верификация браузера
```

Структура: `cypress/e2e/` (спеки), `cypress/support/` (команды), `cypress/fixtures/` (тестовые данные), `cypress.config.js`.

### Сценарий 2: E2E сценарий покупки

**Предпосылки:**
- Приложение с доступом по `baseUrl`
- Тестовые данные в fixtures или мок через `cy.intercept()`

```js
describe('Флоу заказа', () => {
  it('оформляет заказ через корзину', () => {
    cy.visit('/')
    cy.get('[data-test=add-to-cart]').first().click()
    cy.get('[data-test=cart-link]').click()
    cy.contains('Оформить заказ').click()
    cy.get('[data-test=order-total]').should('contain', '₽')
    cy.intercept('POST', '/api/orders').as('createOrder')
    cy.get('[data-test=confirm-order]').click()
    cy.wait('@createOrder').its('response.statusCode').should('eq', 201)
    cy.contains('Спасибо за заказ').should('be.visible')
  })
})
```

**Валидация:** `cy.contains('Спасибо за заказ').should('be.visible')` подтверждает успешное оформление.

### Сценарий 3: Тесты компонентов (React example)

**Предпосылки:**
- React/Vite или React/Webpack в проекте
- `@cypress/react` установлен (`npm i -D @cypress/react`)

В Cypress 16 компонентное тестирование включено по умолчанию через секцию `component` в `cypress.config.js`:

```js
const { defineConfig } = require('cypress')

module.exports = defineConfig({
  component: {
    devServer: {
      framework: 'react',
      bundler: 'vite', // или 'webpack'
    },
    specPattern: 'src/**/*.cy.{js,jsx,ts,tsx}',
  },
  e2e: {
    baseUrl: 'http://localhost:3000',
  },
})
```

```js
import { mount } from 'cypress/react'
import Button from './Button'

it('рендерит кнопку', () => {
  mount(<Button>Нажми</Button>)
  cy.get('button').should('contain', 'Нажми').click()
})
```

**Валидация:** Test Runner переключает вкладку на Component Testing; тесты компонентов запускаются через `npx cypress run --component`.

### Сценарий 4: Флаки-чек и отладка

**Предпосылки:**
- Тест с нестабильной связью (flaky)

- Перехват сбоев: в Test Runner видно каждое действие (time-travel steps), команды, DOM в момент.
- Мок внешних сервисов через `cy.intercept` + fixtures:

```js
cy.intercept('GET', '/api/price', { fixture: 'price.json' })
```

- Видео/скриншоты по умолчанию при провале (artifacts в CI).
- `--retries` для автоматического перезапуска провалившихся спек:

```bash
npx cypress run --retries 2
```

### Сценарий 5: Интеграция в CI/CD (GitLab)

**Предпосылки:**
- GitLab CI с Docker-раннерами
- `baseURL` приложения в CI-окружении
- `cypress/included` Docker-образ (включает браузеры)

```yaml
e2e-tests:
  stage: test
  image: cypress/included:16.0.0
  script:
    - npm ci
    - npx cypress run --spec 'cypress/e2e/**/*.cy.js'
  artifacts:
    when: always
    paths:
      - cypress/screenshots
      - cypress/videos
```

**Валидация:** артефакты `cypress/screenshots` и `cypress/videos` появляются в GitLab CI UI; JUnit-репорт подключается через `--reporter junit` для агрегации в pipeline.

**Параллельный запуск:** `--parallel` + `cypress run --record` требует Cypress Cloud. Без Cloud — разбивка спек по машинам/раннерам в CI (Jenkins — по агентам, GitLab — parallel matrix).

Связь с общими практиками стабильности: [Управление флаки-тестами](../CI-CD/Testing/flaky_test_management.md), [E2E в CI/CD](../CI-CD/Testing/smoke_testing.md) — там про разбиение спек и ретраи.

### Сценарий 6: E2E в CI/CD с Docker и TestContainers (DevOps)

**Предпосылки:**
- Docker registry с собранным образом приложения
- TestContainers или docker-compose для подъёма тестовой среды
- `CYPRESS_BASE_URL` или `baseUrl` в конфиге

```bash
# Поднятие окружения и запуск тестов в одном job
docker compose -f compose.test.yml up -d
sleep 5  # Ждём готовности (или healthcheck)
npx cypress run --env configFile=ci
docker compose -f compose.test.yml down
```

**Валидация:** `docker compose logs` показывают `ready` статус сервисов; `cypress/videos/*.mp4` создаются для каждой спеки.

Связь с аналогичными паттернами: [Testcontainers для E2E](./testcontainers_overview.md), [Acceptance/UAT тестирование](./acceptance_uat_testing.md).

## Операции и команды

### CLI-команды

| Команда | Описание |
| :--- | :--- |
| `npx cypress open` | Запуск Test Runner в интерактивном режиме |
| `npx cypress run` | Запуск всех спек в headless-режиме |
| `npx cypress run --spec 'cypress/e2e/auth/**'` | Запуск спецификаций по glob-паттерну |
| `npx cypress run --env env1=val1,env2=val2` | Передача env-переменных |
| `npx cypress run --config baseUrl=http://localhost:8080` | Переопределение конфига |
| `npx cypress run --browser chrome` | Явный выбор браузера |
| `npx cypress run --parallel` | Параллельный запуск (требует Cypress Cloud) |
| `npx cypress run --record --key <key>` | Запись результатов в Cypress Cloud |
| `npx cypress run --retries 2` | Автоматический перезапуск проваленных спек |
| `npx cypress verify` | Верификация установки браузеров |

### Ключевые cy. команды

| Команда | Описание |
| :--- | :--- |
| `cy.visit(url)` | Навигация на страницу |
| `cy.get(selector)` | Поиск элемента |
| `cy.contains(text)` | Поиск по тексту |
| `cy.type(text)` | Ввод текста |
| `cy.click()` | Клик по элементу |
| `cy.should(assertion)` | Assertion с retry |
| `cy.intercept()` | Мок/стаб запросов |
| `cy.request(url)` | Прямой HTTP-запрос без UI |
| `cy.session()` | Кэширование сессии |
| `cy.origin(url, fn)` | Действия в кросс-оригинальном контексте |

### Конфигурация (cypress.config.js)

| Опция | Описание | По умолчанию |
| :--- | :--- | :--- |
| `defaultCommandTimeout` | Таймаут для команд и assertion | 4000 мс |
| `pageLoadTimeout` | Таймаут загрузки страницы | 60000 мс |
| `requestTimeout` | Таймаут для `cy.request()` | 30000 мс |
| `responseTimeout` | Таймаут ответа на запрос | 30000 мс |
| `viewportWidth` / `viewportHeight` | Размеры viewport | 1000 / 660 |
| `screenshotOnRunFailures` | Скриншот при падении | true (E2E) |
| `video` | Запись видео | true |

## Типичные ошибки и диагностика

| Симптом | Причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| `Timed out retrying` | Элемент появляется позже 4с | Test Runner показывает время ожидания в Command Log; проверить Network tab | Увеличить `defaultCommandTimeout` в конфиге, если элемент медленный |
| Cypress не видит элемент из-за re-render | Неконсистентные селекторы (CSS-классы, структура DOM) | Элемент исчезает после `cy.get()` | Использовать `data-test` атрибуты, не классы/структуру DOM |
| Тест падает только в CI | Различие окружений (сервер, конфиг) | `CYPRESS_BASE_URL` не задан или отличается | `CYPRESS_BASE_URL`, `baseUrl` из env; health-check перед стартом |
| `Cross origin error` | Переход между доменами без `cy.origin()` | Ошибка в консоли: `SecurityError` или `cy.visit` fails | `cy.origin()` для кросс-оригинальных действий |
| Тест медленный (паузы) | Много `cy.wait(ms)` | Поиск `cy.wait(` в спеках | Убрать явные паузы; ждать события `cy.intercept`/`should` |
| Parallel без Cloud | Cypress не распараллеливает спекки на 1 машине | `npx cypress run --parallel` работает только с Cypress Cloud | Запускать по машинам/специям, добавить Cloud при необходимости |
| `Cypress.env()` ошибка после апгрейда до 16 | `Cypress.env()` удалена в Cypress 16 | Ошибка в консоли: `Cypress.env is not a function` | Перейти на env-переменные через `CYPRESS_` prefix и конфиг |
| `cy.request` не видит cookies | Автоматическая изоляция между `it()` | Cookie исчезает после `cy.request` в другом `it()` | Использовать `cy.session()` для кэширования, или `Cypress.Cookies.defaults()` |
| Screenshots пустые | headless-режим не захватывает DOM | Файл screenshot существует, но пуст | Убедиться, что `--browser` поддерживает видеозахват; использовать `cy.document().then()` |
| `cy.intercept` не мокает запрос | Алиас не совпадает или запрос идёт по другому URL | Network tab в Test Runner пуст | Проверить метод и URL в `cy.intercept`; использовать wildcards (`*`) |

## Лучшие практики

- **Селекторы**: использовать `data-test` / `data-cy` атрибуты, а не CSS-классы или структурные селекторы (`cy.get('.container > div:nth-child(3)')`).
- **Изоляция**: один бизнес-флоу на `it()`; минимизировать кросс-тестовые зависимости.
- **Мок vs реальный backend**: мокировать внешние сервисы через `cy.intercept`, но тестировать критические интеграции (API платежей, аутентификация) на real backend.
- **Стабильность CI**: выключать видео для быстрых спек (`video: false`), включать только для flaky-наборов; использовать `--reporter junit` для агрегации результатов.
- **Ретраи**: `--retries 1-2` для flaky-наборов, но не для unit-подобных E2E — ретраи скрывают настоящие дефекты.
- **Сессии**: `cy.session()` для кэширования логина между тестами — экономит 30-50% времени на аутентификацию.

## Ограничения и крайние случаи

- **Один браузер на запуск**: Cypress не поддерживает параллельный запуск нескольких браузеров в одном процессе.
- **Node.js только**: не работает с тестами, требующими Java/.NET-контекст.
- **HTTP/2 в Cypress 16**: включён только для Chrome, Chromium и Edge. Electron, Firefox и WebKit используют HTTP/1.1.
- **Мобильные браузеры**: эмуляция viewport работает, но нативный mobile E2E требует Appium или Cypress Mobile (beta).
- **File upload**: `cy.selectFile()` работает с `<input type="file">`, но не с drag-and-drop без обходных патчей.
- **Memory management**: длинные прогонки могут зависнуть; в Cypress 16 включено `manageBrowserMemory` по умолчанию.
- **`window.open`/`target=_blank`**: окна открываются в том же браузере, но с ограничениями на доступ к DOM popup-окна.

## Очистка

После завершения E2E-тестов в CI рекомендуется:

1. **Артефакты**: `cypress/screenshots/` и `cypress/videos/` — артефакты CI, не коммитятся в git.
2. **Кеш**: `node_modules/.cache/cypress` — можно очищать через `npx cypress cache clear`.
3. **Тестовые данные**: если тесты пишут в БД или очередь — отдельный cleanup job или `cy.request('DELETE', '/api/test-data')`.
4. **Docker**: `docker compose -f compose.test.yml down -v` для удаления томов.

## Дополнительная информация

### См. также

- **[Selenium WebDriver и Selenium Grid](./testing_selenium_grid.md)** — классический стек для мультибраузерного E2E.
- **[Мобильное тестирование](./mobile_testing.md)** — E2E для нативных приложений (Appium/XCUITest/Espresso).
- **[Управление флаки-тестами](../CI-CD/Testing/flaky_test_management.md)** — стабилизация E2E в продакшене.
- **[Acceptance/UAT тестирование](./acceptance_uat_testing.md)** — как E2E-автоматизация покрывает acceptance-сценарии.
- **[Testcontainers для E2E](./testcontainers_overview.md)** — поднятие тестовых окружений в Docker для E2E.

### Внешние ресурсы

- [Cypress Documentation](https://docs.cypress.io/) — официальная документация, загрузка, миграции.
- [Cypress на GitHub](https://github.com/cypress-io/cypress) — исходный код, issue-трекер, release notes.
- [Migration Guide: Cypress 15 → 16](https://docs.cypress.io/app/references/migration-guide) — миграция с `Cypress.env()`, изменения в component testing.
