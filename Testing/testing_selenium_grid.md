# Selenium WebDriver и Selenium Grid

**Актуально для:** Selenium Grid 4.50 (2026); Selenium 3 — только для контраста (устарела, преемник Selenium 4)

## Определения

**Selenium WebDriver** — де-факто стандарт автоматизации браузеров и, фактически, предок W3C WebDriver-протокола. Позволяет автоматизировать практически все браузеры (Chrome, Firefox, Edge, Safari, IE/legacy) через «драйверы». Является основой для многих фреймворков (Selenide, WebdriverIO, TestNG-проекты).

**Selenium Grid** — компонент распределённого выполнения: централизованный Router распределяет тестовые сессии между **Nodes** (агентами с браузерами), поддерживая параллельные запуски на множестве машин, ОС и/или браузеров.

**WebDriver Protocol (W3C)** — стандартизированный HTTP-протокол взаимодействия клиента и браузера.

## Основные концепции

### Архитектура Selenium 3 vs 4

- **Selenium 3** (устарела, преемник — Selenium 4): WebDriver общается с браузером через сами браузерные драйверы (ChromeDriver, geckodriver, msedgedriver); Grid — Hub + Node.
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
5. Все последующие команды маршрутизируются строго на этот Node через Session Map.

Capabilities: `browserName`, `browserVersion`, `platformName`, а также фирменные префиксы (`goog:chromeOptions`, `moz:firefoxOptions`, `ms:edgeOptions`) — формат W3C.

### Разница Grid и обычного WebDriver

- Обычный WebDriver — тест и браузер на одной машине; драйвер поднимается для каждого запуска.
- Grid — тесты распределены по Nodes (могут быть разные ОС, браузеры, контейнеры); параллельность ограничена числом Nodes и concurrency `SE_NODE_MAX_SESSIONS` (в Docker Selenium 4; в Selenium 3 — `maxSession`).

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

> **Системные требования:** Docker Engine 26.1.4+, Docker Compose v2.34.0+ (для Kubernetes — v1.26.15+). Для браузерных контейнеров обязательна `--shm-size`.

`.docker-compose.yml`:

```yaml
services:
  selenium-hub:
    image: selenium/hub:4.50.0
    container_name: selenium-hub
    ports: ["4442:4442", "4443:4443", "4444:4444"]
  chrome:
    image: selenium/node-chrome:4.50.0
    depends_on: [selenium-hub]
    shm_size: 2g
    environment:
      - SE_EVENT_BUS_HOST=selenium-hub
```

Запуск и проверка:

```bash
docker compose up -d
# Ожидание готовности Grid (порт 4444 = Router)
for i in $(seq 1 30); do curl -s http://localhost:4444/status | grep -q '"ready"' && break; sleep 1; done
```

Порты: `4442` — Distributor, `4443` — NoVNC, `4444` — Router (GraphQL + `/status`). Узлы подключаются к Hub через Event Bus (`SE_EVENT_BUS_HOST`); новые Nodes появляются как free и готовы к приёму сессий.

**Важно:** `shm_size: 2g` обязателен — без него Chrome падает с `DevToolsActiveOutput` /crash'ами в `/dev/shm`.

### Сценарий 3: Клиентский тест против Grid

```java
ChromeOptions options = new ChromeOptions();
options.setCapability("platformName", "LINUX");
WebDriver driver = new RemoteWebDriver(
    new URL("http://selenium-hub:4444/wd/hub"), options);
```

В Selenium 4 путь по умолчанию — `http://hub:4444` (без `/wd/hub`), но `/wd/hub` поддерживается для обратной совместимости.

### Сценарий 4: Grid в CI/CD

*   **Локальная параллельность:** в одной джобе можно масштабировать число Nodes через `docker compose up --scale chrome=<N>`; по умолчанию каждый Node принимает одну сессию (`SE_NODE_MAX_SESSIONS=1`), поэтому для параллелизма внутри контейнера задайте `SE_NODE_MAX_SESSIONS` и `SE_NODE_OVERRIDE_MAX_SESSIONS=true`:
```yaml
services:
  selenium-hub:
    image: selenium/hub:4.50.0
    ports: ["4442:4442", "4443:4443", "4444:4444"]
  chrome:
    image: selenium/node-chrome:4.50.0
    shm_size: 2g
    environment:
      - SE_EVENT_BUS_HOST=selenium-hub
      - SE_NODE_MAX_SESSIONS=4
      - SE_NODE_OVERRIDE_MAX_SESSIONS=true
```
*   **Kubernetes:** используйте официальный Helm-чарт (репо `https://www.selenium.dev/docker-selenium`, chart `selenium-grid`):
```bash
helm repo add docker-selenium https://www.selenium.dev/docker-selenium
helm install selenium-grid docker-selenium/selenium-grid
# полностью развязанная топология (Router/Queue/Distributor/EventBus/SessionMap отдельными компонентами)
helm install selenium-grid docker-selenium/selenium-grid --set isolateComponents=true
```
*   **Автоскейлинг:** включите KEDA (`autoscaling.enabled=true`) — чарт автоматически ставит KEDA и масштабирует Nodes (job или deployment) по нагрузке.
*   **Мониторинг:** чарт поддерживает `ServiceMonitor`/`PodMonitor` для Prometheus Operator (добавлено в 4.44). Опционально включайте Jaeger (`tracing.enabled=true`) для трассировок Grid.
*   **Артефакты видео:** видео стоит ~1 CPU на контейнер (`SE_RECORD_VIDEO=true`); храните на том же томе `/videos`.

Для связки покрытия с JUnit-отчётом в GitLab CI см. [Конструктор рабочих процессов GitLab CI/CD](../CI-CD/GitLab_CI/Advanced/gitlab_ci_workflow_builder.md).

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

Современные альтернативы для E2E-тестирования: **Playwright** (выигрывает новые проекты за счёт скорости, авто-вжит-теста и встроенной мок-слоем); **Cypress** — см. [E2E-тестирование с помощью Cypress](./cypress_e2e_testing.md). Grid всё ещё актуален для корпоративных экосистем с TestNG/JUnit и Safari/legacy-браузерами.

## Типичные ошибки и диагностика

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `SessionNotCreatedException` | Нет подходящего драйвера/версии браузера | WebDriverManager; выровнять версии браузер и драйвера |
| Grid status показывает «no free slots» | Все Nodes заняты / `SE_NODE_MAX_SESSIONS=1` | Увеличить concurrency, добавить Nodes |
| `ElementClickInterceptedException` | Элемент перекрыт (модалка, анимация) | Явный `wait`, scrollIntoView, JS-клик как fallback |
| `TimeoutException` у createSession | Event Bus/сеть между компонентами Grid | Проверить Docker-сеть, увеличить `sessionTimeout` |
| Значительная флакость в CI | Ненужные sleep/wait | Использовать WebDriverWait + `expectedConditions` |
| Падение Chrome в контейнере | Недостаточно `/dev/shm` | Обязательно `--shm-size="2g"` |
| Сессии висят в очереди | `SE_NODE_MAX_SESSIONS` ниже нагрузки | Увеличить `SE_NODE_MAX_SESSIONS` и/или число реплик |

## Лучшие практики

### Настройка и масштабирование

*   **Обязательно `shm_size: 2g`** для любого браузерного контейнера — иначе Chrome падает.
*   **Полные теги, никогда `:latest`** — документация Selenium требует pinning (`selenium/hub:4.50.0`, `selenium/node-chrome:4.50.0`); `:latest` делает сборку непроизводственной.
*   **Конкуренция:** по умолчанию `SE_NODE_MAX_SESSIONS=1` (одна сессия на контейнер). Чтобы увеличить параллелизм, задайте `SE_NODE_MAX_SESSIONS` (рекомендованное максимум ≈ число процессоров) и обязательно `SE_NODE_OVERRIDE_MAX_SESSIONS=true` — иначе повышение не применяется.
*   **Readiness:** проверяйте `GET http://hub:4444/status` (ждите `"ready": true`) перед прогоном, а не только передачей порта.

### Безопасность

*   **Порт 4444 (Router) не открывайте в интернет.** WebDriver-endpoint (порт 4444) должен быть доступен только из доверенной сети/CI — см. также рекомендации в [Zabbix: Мониторинг веб-сайтов](../Zabbix/zabbix_website_monitoring.md).
*   Для K8s используйте `networkPolicies`, ограничьте namespace и включайте `tracing.enabled` только в изолированном видеоконтуре.
*   Храните `SE_OPTS`/`SE_JAVA_OPTS` (например, `--host`, `--port`) в Secret, а не в репозитории.

### Жизненный цикл и отчистка

*   После прогонов: `docker compose down` (удаляет контейнеры и сеть по умолчанию, освобождая порты 4442–4444).
*   Видео и скриншоты — ограничьте retention (`expire_in` в GitLab, `retention-days` в GitHub Actions) и периодически очищайте каталог `/videos`.
*   Для K8s очищайте PVC с видео/скриншотами отдельно от данных сервиса.

## Дополнительная информация

### См. также

- **[Selenium Report (Allure) и агрегация JUnit](./testing_reporting_tools.md)** — публикация и визуализация результатов Selenium.
- **[Мобильное тестирование](./mobile_testing.md)** — Appium (построен на WebDriver-протоколе).
- **[Визуальное тестирование в CI/CD](../CI-CD/Testing/visual-regression-cicd.md)** — регрессия кроншотов на WebDriver/Playwright.
- **[Управление нестабильными тестами](../CI-CD/Testing/flaky_test_management.md)** — теория флаков, метрики стабильности, детекция.
- **[GitHub Actions: Тест-отчёты и надёжность тестов](../Github_CI/Test_Reporting_Reliability.md)** — публикация JUnit в PR, ретраи, карантин.

### Внешние ресурсы

- [Selenium Documentation](https://www.selenium.dev/documentation/) — официальная документация (WebDriver, Grid, Migrating to 4).
- [Selenium Grid](https://www.selenium.dev/documentation/grid/) — документация Grid 4, запуск, настройка Nodes.
- [docker-selenium (README)](https://github.com/SeleniumHQ/docker-selenium) — образы, переменные окружения, docker-compose, Helm-чарт.
