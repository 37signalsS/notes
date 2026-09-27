# E2E-тестирование с помощью Cypress

## Определения

**Cypress** — JavaScript-фреймворк для end-to-end (E2E) и component-тестирования веб-приложений. Агрессивно отличается от классических Selenium-решений архитектурой: тест-раннер встраивается непосредственно в браузер (Chromium, Firefox, WebKit), а не общается с ним через внешний WebDriver-сервер. Актуальная мажорная версия — **Cypress 16.x** (последняя — 16.1.0, сентябрь 2026; в 16.0 HTTP/2 стал протоколом по умолчанию, а базовый runtime — Node.js 24).

**Spec (спека)** — файл E2E-теста (`cy/e2e/*.cy.js`).

**Test Runner** — интерактивный интерфейс Cypress, где тесты выполняются вживую с перемоткой событий.

**Component Testing** — режим тестирования UI-компонентов (React/Vue/…) в изоляции; запускается через бандлер (Vite/Webpack).

## Основные концепции

### Как Cypress отличается от Selenium

| Аспект | Cypress | Selenium WebDriver |
| :--- | :--- | :--- |
| Архитектура | Встраивается в браузер, напрямую управляет DOM | Обращение к браузеру через WebDriver-протокол |
| Асинхронность теста | Автоматическая (тест «плывёт» через retry) | Явные ожидания (WebDriverWait) |
| Скорость | Очень высокая за счёт отсутствия сетевых виттков | Зависит от драйвера; обычно медленнее |
| Установка | `npm i -D cypress` | Драйверы для каждого браузера отдельно |
| Мультибраузерность | Chrome, Chrome для Edge, Firefox, WebKit | Все браузеры (в т.ч. Safari, IE) |
| Поддержка mobile | Малый, только эмуляция viewport | Мобильные браузеры, эмуляции |

### Ключевые механики

- **Автоматический ретрай**: команды являются «декларативными» — Cypress сам ждёт появления элементов и условий до заданного `defaultCommandTimeout` (4 сек).
- **Изоляция состояния**: между `it()` Cypress сбрасывает состояние (cookies, localStorage) — «между тест-кейсами чистота» по умолчанию.
- **Перехват сетевых запросов**: `cy.intercept()` — мок stub/spy на любые XHR/fetch, аналог `nock`/`msw`, диагностика запросов в реальном времени в Test Runner.
- **Повторные запуски тестов**: Cypress умеет ретраить только провалившиеся спецификации (`--retries`), в т.ч. с сохранением screenshots/videos.

### Основные команды (lib)

```js
cy.visit('/login')                    // навигация
cy.get('[data-test=email]').type('user@example.com')
cy.get('[data-test=submit]').click()
cy.contains('Добро пожаловать').should('be.visible')
cy.request('POST', '/api/token', {...}) // API-подготовка без UI
```

Используются **resolved & await-семантика** Cypress: `should()` / `expect()`.

### Параллельное выполнение

«Параллелизация» в Cypress официально реализуется через **Cypress Cloud** (`.record` к Cloud). Для open-source параллельного запуска:

- разбивка спецификаций по рабочим машинам (self-hosted agents);
- сторонние утилиты (напр., `cypress-parallel`) для запуска спек по CPU-ядрам;
- в CI/CD обычно достаточно: `npx cypress run --spec 'cy/e2e/**/*.cy.js'` на нескольких раннерах (Jenkins — по агентам, GitLab — parallel matrix).

### Cypress и локальные Web-приложения

Особенность: Cypress **не может заходить на удалённые хосты без `baseUrl`+`proxy`**; для тестов аутентификации обычно готовят сессию через `cy.session()` (кеш авторизации между тестами).

```js
Cypress.Commands.add('login', (email, password) => {
  cy.session([email, password], () => {
    cy.visit('/login')
    cy.get('[data-test=email]').type(email)
    cy.get('[data-test=password]').type(password)
    cy.get('form').submit()
    cy.location('pathname').should('eq', '/dashboard')
  })
})
```

## Практические сценарии

### Сценарий 1: Установка и инициализация

```bash
npm init -y
npm install -D cypress
npx cypress open      # первый запуск создаст структуру cypress/
```

Структура: `cypress/e2e/`, `cypress/support/` (команды), `cypress/fixtures/` (тестовые данные), `cypress.config.js`.

### Сценарий 2: E2E сценарий покупки

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

### Сценарий 3: Тесты компонентов (React example)

```js
import { mount } from 'cypress/react'
import Button from './Button'

it('рендерит кнопку', () => {
  mount(<Button>Нажми</Button>)
  cy.get('button').should('contain', 'Нажми').click()
})
```

Для запуска component-тестов требуется бандлер (Vite/Webpack) — конфигурируется в `cypress.config.js` (`experimentalComponentTesting` / `component`).

### Сценарий 4: Флаки-чек и отладка

- Перехват сбоев: в Test Runner видно каждое действие (time-travel steps), команды, DOM в момент.
- Мок внешних сервисов через `cy.intercept` + fixtures:

```js
cy.intercept('GET', '/api/price', { fixture: 'price.json' })
```

- Видео/скриншоты по умолчанию при провале (artifacts в CI).

### Сценарий 5: Интеграция в CI/CD (GitLab)

```yaml
e2e-tests:
  stage: test
  image: cypress/included:16.1.0
  script:
    - npm ci
    - npm run e2e:run   # cypress run --headless
  artifacts:
    when: always
    paths:
      - cypress/screenshots
      - cypress/videos
```

Связь с общими практиками стабильности: [Управление флаки-тестами](../CI-CD/Testing/flaky_test_management.md), [E2E в CI/CD](../CI-CD/Testing/smoke_testing.md) — там про разбиение спек и ретраи.

## Типичные ошибки и диагностика

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `Timed out retrying` | Элемент появляется позже 4с | Увеличить `defaultCommandTimeout`, если элемент медленный |
| Cypress не видит элемент из-за re-render | Неконсистентные селекторы | Использовать `data-test` атрибуты, не классы/структуру DOM |
| Тест падает только в CI | Различие окружений (сервер, конфиг) | `CYPRESS_BASE_URL`, `baseUrl` из env; health-check перед стартом |
| `Cross origin error` | Переход между доменами | `cy.origin()` для кросс-оригинальных действий |
| Тест медленный (паузы) | Много `cy.wait(ms)` | Убрать явные паузы; ждать события `cy.intercept`/`should` |
| Parallel без Cloud | Cypress не распараллеливает спекки сам на 1 машине | Запускать по машинам/специям, добавить Cloud при необходимости |
| `Cypress.env` ошибка после апгрейда до 16 | Удаление `Cypress.env` в Cypress 16 | Перейти на `cy.env()` / env-переменные через конфиг |

## Дополнительная информация

### См. также

- **[Selenium WebDriver и Selenium Grid](./testing_selenium_grid.md)** — классический стек для мультибраузерного E2E.
- **[Мобильное тестирование](./mobile_testing.md)** — E2E для нативных приложений (Appium/XCUITest/Espresso).
- **[Управление флаки-тестами](../CI-CD/Testing/flaky_test_management.md)** — стабилизация E2E в продакшене.

### Внешние ресурсы

- [Cypress Documentation](https://docs.cypress.io/) — официальная документация, загрузка, миграции.
- [Cypress на GitHub](https://github.com/cypress-io/cypress) — исходный код, issue-трекер, release notes.