# Selenium WebDriver и Selenium Grid

## Определения

**Selenium WebDriver** — де-факто стандарт автоматизации браузеров и, фактически, предок W3C WebDriver-протокола. Позволяет автоматизировать практически все браузеры (Chrome, Firefox, Edge, Safari, IE/legacy) через «драйверы». Является основой для многих фреймворков (Selenide, WebdriverIO, TestNG-проекты).

**Selenium Grid** — компонент распределённого выполнения: **Hub** распределяет тесты между **Nodes** (агентами с браузерами), поддерживая параллельные запуски на множестве машин и/или браузеров.

**WebDriver Protocol (W3C)** — стандартизированный HTTP-протокол взаимодействия клиента и браузера.

## Основные концепции

### Архитектура Selenium 3 vs 4

- **Selenium 3**: WebDriver общается с браузером через сами браузерные драйверы (ChromeDriver, geckodriver, msedgedriver); Grid — Hub + Node.
- **Selenium 4**: встроенная поддержка **W3C WebDriver**, редизайн Grid — **узлы-компоненты** (Router, Distributor, Session Map, Event Bus, Node), замена Hub/Node на less-хрупкую сетевую топологию. Полностью совместим с JSON Wire Protocol на уровне клиентских библиотек.

### Компоненты Selenium Grid 4

| Компонент | Роль |
| :--- | :--- |
| **Router** | Единая точка входа для HTTP-запросов; проксирует запросы сессии к Distributor/Node |
| **Distributor** | Планировщик: распределяет новые сессии между Nodes |
| **Session Map** | Хранение соответствия sessionId → Node (для стабильной маршрутизации) |
| **Event Bus** | Event-driven обмен событиями между узлами (на базе Netty) |
| **Node** | Исполняет сессии, передаёт команды конкретному драйверу |

### Процесс создания сессии

1. Клиент (тест) отправляет команду `newSession` (с desired capabilities / options) на **Router**.
2. Router направляет запрос в **Distributor**.
3. Distributor выбирает свободный **Node** с подходящей browser/platform capability.
4. Node поднимает драйвер, возвращает sessionId.
5. Все последующие команды маршрутизируются строго на этото Node через Session Map.

Capabilities: `browserName`, `browserVersion`, `platformName`, а также фирменные префиксы (`goog:chromeOptions`, `moz:firefoxOptions`, `ms:edgeOptions`) — формат W3C.

### Разница Grid и обычного WebDriver

- Обычный WebDriver — тест и браузер на одной машине; драйвер поднимается для каждого запуска.
- Grid — тесты распределены по Nodes (могут быть разные ОС, браузеры, контейнеры); параллельность ограничена числом Nodes и concurrency `maxSession`.

## Практические сценарии

### Сценарий 1: Локальный WebDriver (базовый)

```java
import org.openqa.selenium.WebDriver;
import org.openqa.selenium.chrome.ChromeDriver;

WebDriver driver = new ChromeDriver();
driver.get("https://example.com");
System.out.println(driver.getTitle());
driver.quit();
```

Для Chrome требуется ChromeDriver (бинарник в PATH или авто-скоул в WebDriverManager).

### Сценарий 2: Запуск Selenium Grid (Docker Compose)

`.docker-compose.yml`:

```yaml
services:
  selenium-hub:
    image: selenium/hub:4.21
    ports: [4444:4444]
  chrome:
    image: selenium/node-chrome:4.21
    depends_on: [selenium-hub]
    shm_size: 2g
```

Запуск и проверка:

```bash
docker compose up -d
curl http://localhost:4444/status   # статус Nodes
```

Узлы подключаются к Hub автоматически — новые Nodes появляются как free и готовы к приёму сессий.

### Сценарий 3: Клиентский тест против Grid

```java
ChromeOptions options = new ChromeOptions();
options.setCapability("platformName", "LINUX");
WebDriver driver = new RemoteWebDriver(
    new URL("http://selenium-hub:4444/wd/hub"), options);
```

В Selenium 4 путь по умолчанию — `http://hub:4444` (без `/wd/hub`).

### Сценарий 4: Grid в CI/CD (через Kubernetes/Compose)

- Арктифакт — parallel jobs, каждая поднимает собственный Grid или одна общая для пайплайна.
- Типичная конфигурация пайплайна — «запустить N тест-спек на N контейнерах с браузерами», используя `maxSessions`.
- Для kubectl-инфраструктуры есть helm-чарты для Selenium Grid (идет набор docker images: `selenium/hub`, `selenium/node-chrome`, `selenium/node-firefox`, `selenium/node-edge`).

### Сценарий 5: Параллельность в TestNG и Grid

```xml
<suite name="Parallel" parallel="tests" thread-count="4">
  <test name="ChromeTests">
    <parameter name="browser" value="chrome"/>
    <classes><class name="tests.SearchTest"/></classes>
  </test>
</suite>
```

Каждый тест-нюк запускает новую сессию на Nodes; результатом является быстрое выполнение N независимых сценариев.

### Сценарий 6: Не-Selenium E2E стек

Современные альтернативы для E2E-тестирования: **Playwright** (Office-Group) — большинство новых проектов выбирают его из-за скорости, авто-вжит-теста и встроенной мок-слунэ; **Cypress** — см. [E2E-тестирование с помощью Cypress](./cypress_e2e_testing.md). Grid всё ещё актуален для корпоративных экосистем с TestNG/JUnit и Safari/legacy-браузерами.

## Типичные ошибки и диагностика

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `SessionNotCreatedException` | Нет подходящего драйвера/версии браузера | WebDriverManager; выровнять версии браузер и драйвера |
| Grid status показывает «no free slots» | Все Nodes заняты / maxSession=1 | Увеличить concurrency, добавить Nodes |
| `ElementClickInterceptedException` | Элемент перекрыт (модалка, анимация) | Явный `wait`, scrollIntoView, JS-клик как fallback |
| `TimeoutException` у createSession | Event Bus/сеть между компонентами Grid | Проверить Docker-сеть, увеличить `sessionTimeout` |
| Значительная флакость в CI | Ненужные sleep/wait | Использовать WebDriverWait + `expectedConditions` |

## Дополнительная информация

### См. также

- **[E2E-тестирование с помощью Cypress](./cypress_e2e_testing.md)** — современная альтернатива Selenium для веб-E2E.
- **[Мобильное тестирование](./mobile_testing.md)** — Appium (построен на WebDriver-протоколе) для нативных приложений.
- **[Визуальное тестирование в CI/CD](../CI-CD/Testing/visual-regression-cicd.md)** — регрессия кроншотов на WebDriver/Playwright.

### Внешние ресурсы

- [Selenium Documentation](https://www.selenium.dev/documentation/) — официальная документация (WebDriver, Grid, Migrating to 4).
- [Selenium Grid](https://www.selenium.dev/documentation/grid/) — документация Grid 4, запуск, настройка Nodes.