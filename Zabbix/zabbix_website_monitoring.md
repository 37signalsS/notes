# Мониторинг веб-сайтов в Zabbix: скрипты, сценарии и Browser Items

> **Актуальность:** Основная долгосрочная ветка — **Zabbix 7.0 LTS** (обновления до 30 июня 2027, ограниченная поддержка до 30 июня 2029). Текущая стандартная ветка — **Zabbix 7.4** (выпущена 30 июня 2025). **Zabbix 8.0 LTS** на момент сверки не выпущен: доступен кандидат в релиз **8.0.0rc1 (1 октября 2026)**, выпуск GA запланирован на Q4 2026 (по roadmap — ноябрь 2026); сведения по 8.0 приведены по предрелизным данным. Особенности конкретных версий отмечены по тексту.

## Определения

* **Внешний скрипт (External Check / UserParameter)** — метод мониторинга, при котором Zabbix Agent запускает исполняемый скрипт и использует его стандартный вывод как значение метрики. Обеспечивает максимальную гибкость и возможность любой нестандартной логики (SSO, криптографические библиотеки).
* **Web Scenario (Веб-сценарий)** — встроенный в Zabbix механизм для выполнения последовательности HTTP-запросов. Оптимален для проверки REST API и простых сайтов без сложного JavaScript.
* **Синтетический мониторинг (Synthetic Monitoring)** — эмуляция действий реального пользователя (клики, ввод текста) для оценки работоспособности сложных веб-приложений (SPA). Реализован начиная с Zabbix 7.0 через **Browser Items** (поддержка помечена как experimental).
* **Browser Item** — тип элемента данных, который выполняет JavaScript-скрипт (диалект Duktape) в реальном браузере через Selenium WebDriver (протокол W3C WebDriver). Обрабатывается на Zabbix Server/Proxy процессом `browser poller`.
* **Selenium WebDriver** — серверная прослойка автоматизации браузера, к которой Zabbix подключается по HTTP(S), указывая адрес в параметре `WebDriverURL`. Стандартный способ развертывания — контейнер с Selenium Standalone (например, `selenium/standalone-chrome`).
* **Зависимый элемент данных (Dependent Item)** — элемент без собственного опроса: он получает отклик «материнского» элемента и извлекает нужные значения способом предобработки (JSONPath/Regex). Для Browser Item применяется для разбора JSON-отклика, в т.ч. для сохранения скриншотов (тип Binary).
* **SLA (Service Level Agreement)** — раздел Services: рассчитывает показатель доступности (Availability) и SLO/SLI для сервисов на основе тегов триггеров.
* **HTTP Agent** — встроенный компонент Zabbix, который выполняет HTTP(S)-запросы напрямую с Zabbix Server или Proxy (без агента на целевом хосте). Используется для мониторинга WebDriver и простых веб-проверок.
* **Zabbix Web Service** — отдельный сервис (по умолчанию порт 10053), который выполняет Browser Items (рендеринг через Selenium) и генерацию отчетов PDF. Подключение задается параметром `WebServiceURL`.
* **WebDriverURL** — параметр конфигурации Zabbix Server/Proxy, задающий адрес Selenium WebDriver для Browser Items.
* **StartBrowserPollers** — параметр конфигурации, задающий количество pre-forked процессов `browser poller` (по умолчанию 1; увеличивается при большом числе Browser Items).

---

## Основные концепции

### Выбор метода мониторинга

Для мониторинга веб-ресурсов в Zabbix применяются три основных подхода. Выбор зависит от сложности целевого приложения и требований к ресурсам:

| Реализация | JavaScript | Стороннее ПО | Нагрузка на ресурсы | Когда использовать |
| :--- | :---: | :---: | :---: | :--- |
| **Web Scenarios** | Нет | Нет | Низкая | REST API, статические сайты, простые проверки доступности |
| **Browser Items** (7.0+) | Да (полный браузер) | Selenium WebDriver | Высокая (RAM браузера) | SPA, авторизация, скриншоты, Navigation Timing |
| **Custom Scripts** (UserParameter) | Не требуется | Скрипт на хосте | Низкая | Специфическая логика, криптография, корпоративный SSO |

1. **Web Scenarios:** Встроенный инструмент ядра. Не требует стороннего ПО. Отправляет GET/POST запросы, проверяет HTTP-коды (200 OK) и наличие подстрок в теле ответа. Не умеет исполнять JavaScript. Подходит для большинства API и статических сайтов.
2. **Browser Items (Zabbix 7.0+, experimental):** Полноценный синтетический мониторинг. Требует развертывания Selenium WebDriver. Позволяет авторизоваться на сайтах с CAPTCHA/MFA (если есть обходной путь), собирать метрики производительности (Navigation Timing API) и сохранять скриншоты ошибок в БД Zabbix (тип данных `Binary`). Обрабатывается процессом `browser poller`.
3. **Кастомные скрипты (UserParameter):** Классический подход. Используется, когда требуется сложная нестандартная логика (например, авторизация через корпоративный SSO с использованием специфических криптографических библиотек Python), не реализуемая через Web Scenarios или Browser Items.

### Архитектура Browser Items

Browser Items выполняются в реальном браузере (Chrome/Chromium) через Selenium WebDriver. Процесс выполнения:

1. **Zabbix Server/Proxy** (`browser poller`) передает JavaScript-сценарий в **Zabbix Web Service** (порт 10053).
2. **Zabbix Web Service** отправляет команду на выполнение в **Selenium WebDriver** (адрес задается `WebDriverURL`).
3. **Selenium WebDriver** запускает браузер, выполняет сценарий (навигация, клики, ввод текста).
4. Результат (JSON со статусом, временем, скриншотом) возвращается обратно в Zabbix.
5. **Dependent Items** с preprocessing (JSONPath/Regex) извлекают отдельные метрики из JSON-ответа.

### DevOps/SRE/Sysadmin контекст

Мониторинг веб-сайтов встроен в процессы эксплуатации ИТ-инфраструктур:

* **Synthetic Monitoring как часть Observability:** Browser Items дополняют Traditional Monitoring (Zabbix Agent, SNMP), давая представление о состоянии веб-приложений с точки зрения пользователя. Синтетические проверки измеряют доступность и задержку с точки зрения пользователя и дополняют классическую модель Four Golden Signals (latency, traffic, errors, saturation).
* **Incident Management:** оповещения по падению веб-сайтов интегрируются с ITSM-системами (Jira, GLPI) и дежурными сервисами (PagerDuty, OpsGenie). При срабатывании Browser Item триггера автоматически создается тикет с контекстом (скриншот, теги, время).
* **SLI/SLO/SLA:** Zabbix 6.0+ поддерживает расчет SLA на основе тегов триггеров (Services → SLA). SRE используют данные Browser Items для определения целевых показателей доступности (Uptime) и производительности (Navigation Timing) веб-сервисов.
* **Runbook Automation:** действия (Actions) могут выполнять не только оповещения, но и скрипты автоматического восстановления. При срабатывании триггера Browser Item Zabbix может автоматически перезапустить backend-сервис, очистить кэш или вызвать API оркестратора.
* **Post-mortem Analysis:** события Browser Items сохраняются с полным контекстом (скриншот, JSON-отклик, временные метки). Это позволяет проводить постмортем-анализ инцидентов и выявлять системные причины падений веб-приложений.
* **Change Management:** все изменения в порогах Browser Items, шаблонах синтетического мониторинга проходят через процедуры управления изменениями. Версионный контроль шаблонов в Git обеспечивает аудит и откат.
* **Capacity Planning:** WebDriver требует значительных ресурсов (RAM браузера). SRE планируют capacity для инфраструктуры Browser Items (число процессов `StartBrowserPollers`, размер `--shm-size` контейнера Selenium) исходя из числа мониторимых веб-приложений.

---

## Операции и команды

### Управление Selenium WebDriver

```bash
# Запуск Selenium Standalone Chrome (Docker)
docker run -d -p 4444:4444 --shm-size=2g selenium/standalone-chrome
# → <CONTAINER_ID> (идентификатор запущенного контейнера)

# Проверка доступности WebDriver (эндпоинт /status)
curl -s http://localhost:4444/status
# → {"value":{"ready":true,"message":"Selenium Grid ready.","nodes":[...]}}

# Остановка контейнера
docker stop <CONTAINER_ID>
```

### Валидация Browser Items

Selenium WebDriver и Zabbix Web Service не опрашиваются через `zabbix_get` (утилита работает только с Zabbix Agent). Проверяйте их напрямую, а внутренние метрики `zabbix[...]` настраивайте как элементы типа «Zabbix internal» на хосте Zabbix server.

```bash
# 1. Selenium WebDriver: проверка эндпоинта /status
curl -s http://localhost:4444/status
# → {"value":{"ready":true,"message":"Selenium Grid ready.","nodes":[...]}}

# 2. Zabbix Web Service: встроенного item-ключа нет, проверяйте TCP-порт
ss -tlnp | grep 10053
# → LISTEN 0 128 0.0.0.0:10053 (zabbix_web_service)
# Для регулярного мониторинга порта используйте простую проверку: net.tcp.service[tcp,<host>,10053]

# 3. Внутренние метрики (тип "Zabbix internal", значения — в Monitoring → Latest data):
#    zabbix[process,browser poller,avg,busy]  → занятость процесса browser poller, %
#    zabbix[queue]                            → число элементов в очереди опроса
#    zabbix[queue,<from>,<to>]                → очередь с задержкой опроса в диапазоне секунд
```

### Управление конфигурацией WebDriver

```bash
# Проверка конфигурации Zabbix Server
grep -E "WebDriverURL|StartBrowserPollers|WebServiceURL" /etc/zabbix/zabbix_server.conf
# → WebDriverURL=http://localhost:4444
# → StartBrowserPollers=2
# → WebServiceURL=http://localhost:10053

# Проверка работы Zabbix Web Service (порт 10053)
ss -tlnp | grep 10053
# → LISTEN 0 128 0.0.0.0:10053 (zabbix_web_service)
```

### Управление Runtime Control для Browser Poller

```bash
# Повысить уровень логирования для browser poller (Troubleshooting)
zabbix_server -R log_level_increase='browser poller'
# → Debug level 4 для всех browser pollers

# Возврат к стандартному уровню
zabbix_server -R log_level_decrease='browser poller'
```

### Мониторинг ресурсов Selenium контейнера

```bash
# Проверка RAM контейнера
docker stats <CONTAINER_ID> --no-stream
# → MEM USAGE / LIMIT (проверьте, что используется ≤ --shm-size=2g)

# Логи Selenium (ошибки запуска браузера)
docker logs <CONTAINER_ID> --tail 50
# → ошибки сессии, драйвера, X11
```

---

## Устранение неисправностей

### Типичные симптомы

| Симптом | Вероятная причина |
| :--- | :--- |
| **Browser Items в статусе Unsupported** | WebDriver недоступен (`WebDriverURL` неверен или Selenium не запущен); Zabbix Web Service не запущен (порт 10053); `WebServiceURL` неверен. |
| **Ошибка сессии Selenium** | Selenium Standalone перезапустился; исчерпан лимит сессий (не хватает `StartBrowserPollers`); браузер упал по OOM. |
| **Высокий RAM контейнера Selenium** | Накопление процессов браузера (утечки памяти в сценариях); не хватает `--shm-size`; слишком много параллельных Browser Items. |
| **Долгие проверки Browser Items** | Браузер ждет загрузки ресурсов (таймаут); Selenium Grid перегружен; медленная сеть до WebDriver. |
| **Нет скриншотов в Dependent Item** | JavaScript-сценарий не возвращает `screenshot`; Dependent Item не настроен на тип Binary; ошибка в preprocessing. |
| **Zabbix Web Service не отвечает** | Сервис не запущен; конфликт порта 10053; неверный `WebServiceURL` в конфигурации Server/Proxy. |

### Быстрая диагностика

1. **Проверьте доступность WebDriver:**
   ```bash
   curl -s http://localhost:4444/status
   # → "ready": true (WebDriver готов)
   # → "ready": false (WebDriver недоступен — проверьте Docker/контейнер)
   ```

2. **Проверьте Zabbix Web Service:**
   ```bash
   systemctl status zabbix-web-service
   ss -tlnp | grep 10053
   # → active (running); LISTEN 0.0.0.0:10053 (zabbix_web_service)
   ```

3. **Проверьте загрузку Browser Poller:**
   ```bash
   # Внутренний элемент (тип "Zabbix internal"), значение — Monitoring → Latest data
   zabbix[process,browser poller,avg,busy]
   # → >75% — увеличьте StartBrowserPollers
   ```

4. **Проверьте логи:**
   ```bash
   # Логи Zabbix Server
   tail -100 /var/log/zabbix/zabbix_server.log | grep -i browser
   # → ошибки инициализации WebDriver, таймауты

   # Логи Zabbix Web Service
   tail -100 /var/log/zabbix/zabbix_web_service.log
   # → ошибки рендеринга, порт 10053

   # Логи Selenium контейнера
   docker logs <CONTAINER_ID> --tail 50
   # → ошибки Chrome, сессий
   ```

5. **Диагностика через diaginfo:**
   ```bash
   zabbix_server -R diaginfo=preprocessing
   # → очередь и ошибки предобработки Browser Items

   zabbix_server -R diaginfo=alerting
   # → очередь оповещений по веб-мониторингу
   ```

### Распространенные проблемы

| Проблема | Причины | Решение |
| :--- | :--- | :--- |
| **Browser Items Unsupported** | WebDriver недоступен, Web Service не запущен | Проверьте `WebDriverURL`, запустите Selenium, проверьте порт 10053 |
| **Selenium session не создается** | Контейнер перезапущен, не хватает памяти | Перезапустите Selenium, увеличьте `--shm-size` и `StartBrowserPollers` |
| **Высокий RAM Selenium** | Утечки памяти в сценариях, мало `--shm-size` | Увеличьте `--shm-size=4g`, ограничьте параллельные проверки |
| **Нет скриншотов** | Ошибка в JS-сценарии, Dependent Item не настроен | Проверьте ключ preprocessing (Base64-декод), тип Binary |
| **Долгие проверки** | Таймауты загрузки, перегрузка WebDriver | Увеличьте таймаут в JS-сценарии, добавьте Selenium Grid |

Для глубокой диагностики смотрите разделы:
- **[Внутреннее устройство и процессы](./additional_info.md)** — архитектура `browser poller` и `Zabbix Web Service`
- **[Тюнинг и производительность](./zabbix_troubleshooting_and_performance_tuning.md)** — оптимизация воркеров и кэшей
- **[Лучшие практики настройки](./zabbix_best_practices.md)** — стратегия тегирования и оповещений

---

## Лучшие практики

### Проектирование Browser Items

* **Ограничьте параллельные Browser Items:** каждый Browser Item потребляет RAM браузера (обычно 200–500 МБ на сессию). Начинайте с `StartBrowserPollers=1` и увеличивайте только при стабильной загрузке выше 75%.
* **Используйте Selenium Grid для масштабирования:** при большом числе веб-приложений разверните Selenium Grid (хаб + несколько нод). Это позволяет распределять нагрузку и обеспечивает отказоустойчивость.
* **Ограничьте размер `--shm-size`:** контейнер Selenium должен иметь разделяемую память не меньше 2 ГБ. При нехватке `--shm-size` браузер падает с ошибкой `session not created`.
* **Не храните чувствительные данные в JS-сценариях:** используйте user macros (`{$PASSWORD}`) для передачи учетных данных, а не хардкод в сценарии.
* **Настраивайте таймауты в JS-сценарии:** используйте `browser.setSessionTimeout(15000)` (таймаут загрузки страницы), `browser.setScriptTimeout(15000)` (таймаут загрузки скриптов) и `browser.setElementWaitTimeout(5000)` (неявное ожидание элемента). Значение задается в миллисекундах.

### Мониторинг инфраструктуры Browser Items

* **Мониторьте Selenium отдельно:** создайте хост для WebDriver с элементом данных `selenium.status` (HTTP Agent + JSONPath) и триггером на `last(/selenium/status)=0`.
* **Мониторьте Zabbix Web Service:** проверяйте доступность порта 10053 простой проверкой `net.tcp.service[tcp,<host>,10053]`. Встроенного item-ключа для Web Service нет. Web Service критичен для выполнения Browser Items.
* **Подключите Template App Zabbix Server:** отслеживайте `zabbix[process,browser poller,avg,busy]` и `zabbix[queue]` для своевременного выявления узких мест.

### Безопасность

* **Ограничьте доступ к Selenium:** WebDriver (порт 4444) должен быть доступен только с Zabbix Server/Proxy. Никогда не открывайте порт 4444 в интернет.
* **Шифруйте трафик:** используйте HTTPS для `WebDriverURL` и `WebServiceURL` при удаленном WebDriver.
* **Храните учетные данные в Vault:** используйте `{$PASSWORD}` макросы вместо хардкода в JS-сценариях. Zabbix поддерживает хранение секретов во внешнем secret provider (HashiCorp Vault) для макросов начиная с версии 5.2; поддержка метода аутентификации Vault AppRole запланирована в ветке 8.0.

### Снижение шума оповещений

* **Настраивайте гистерезис для Browser Items:** используйте отдельное Recovery Expression для предотвращения дребезга при временных сбоях загрузки.
* **Используйте Problem Suppression:** временно подавляйте оповещения Browser Items при плановых работах на веб-приложении.
* **Настраивайте Maintenance:** для плановых остановок веб-приложений создайте Maintenance окно, чтобы не получать оповещения Browser Items.

### Очистка и откат

* **Отключите Browser Items:** удалите или отключите элементы типа Browser и связанные Dependent Items, затем уменьшите `StartBrowserPollers`.
* **Остановите и удалите Selenium:** `docker stop <CONTAINER_ID> && docker rm <CONTAINER_ID>`; при использовании Selenium Grid остановите хаб и ноды.
* **Откатите конфигурацию:** уберите параметры `WebDriverURL`, `WebServiceURL`, `StartBrowserPollers` из `zabbix_server.conf` и перезапустите Zabbix Server/Proxy.
* **Удалите сторонние компоненты:** при отказе от синтетического мониторинга остановите службу `zabbix-web-service` и удалите при необходимости созданные шаблоны/хосты.

---

## Практические сценарии

### Предварительные требования

Требования зависят от выбранного метода:

* **Метод 1 (Browser Items):**
  * Zabbix Server/Proxy 7.0+ с поддержкой Browser Items;
  * Zabbix Web Service, запущенный и доступный по `WebServiceURL` (порт по умолчанию 10053);
  * Selenium WebDriver (например, контейнер `selenium/standalone-chrome`), доступный по `WebDriverURL` (порт по умолчанию 4444);
  * сетевой доступ от Zabbix Server/Proxy до Web Service и WebDriver; контейнеру Selenium требуется не менее 2 ГБ RAM и `--shm-size` не менее 2 ГБ.
* **Метод 3 (UserParameter):** Zabbix Agent 2 и Python 3 на хосте-исполнителе.
* **Методы 2 (Web Scenarios) и 4 (SSL-сертификаты):** дополнительных компонентов не требуют.

Общая установка Zabbix описана в [`installation.md`](./installation.md).

### Метод 1: Синтетический мониторинг через Browser Items (Zabbix 7.0+)

Позволяет полноценно взаимодействовать с элементами страницы (DOM) и получать визуальное подтверждение сбоев.

#### 1. Развертывание Selenium WebDriver

Для работы Browser Items требуется запущенный экземпляр Selenium WebDriver:

```bash
docker run -d -p 4444:4444 --shm-size=2g --name selenium selenium/standalone-chrome
# → <CONTAINER_ID> (идентификатор запущенного контейнера)
```

*Контейнер с браузером требует существенного объема оперативной памяти (обычно >2 ГБ), учитывайте это при планировании ресурсов Zabbix Server/Proxy.*

В конфигурационном файле `zabbix_server.conf` (или `zabbix_proxy.conf`, если проверки идут через прокси) укажите адрес WebDriver и число процессов-обработчиков:

```bash
### Option: WebDriverURL
WebDriverURL=http://localhost:4444

### Option: WebServiceURL
# Адрес Zabbix Web Service (порт 10053)
WebServiceURL=http://localhost:10053

### Option: StartBrowserPollers
# Количество pre-forked браузерных воркеров (по умолчанию 1).
# Увеличьте при большом числе Browser Items.
StartBrowserPollers=2
```

Перезапустите Zabbix Server/Proxy:

```bash
systemctl restart zabbix-server
# → (без вывода при успешном перезапуске)
```

Проверьте: Zabbix Web Service должен быть запущен на порту 10053:

```bash
ss -tlnp | grep 10053
# → LISTEN 0 128 0.0.0.0:10053 (zabbix_web_service)
```

> **Готовая основа:** вместо настройки «с нуля» можно использовать шаблон `Website By Browser` (поставляется начиная с Zabbix 7.0): он уже содержит items для времени навигации, ресурсов, скриншот и триггеры на доступность/производительность. В шаблоне замените только домен (макрос `{$WEBSITE.DOMAIN}`).

#### 2. Настройка Browser Item в веб-интерфейсе

1. Создайте Item с типом **Browser**.
2. В поле **Script** укажите код логики на встроенном диалекте JavaScript (Duktape):

```javascript
var browser = new Browser(Browser.chromeOptions());
try {
    browser.navigate("https://example.com/login");

    // Поиск элементов и ввод данных
    browser.findElement("css selector", "input[name='user']").sendKeys("admin");
    browser.findElement("css selector", "input[name='pass']").sendKeys("passwordA");
    browser.findElement("css selector", "button#submit").click();

    // Проверка успешной авторизации по наличию элемента (проверка текста ссылки)
    browser.findElement("link text", "Dashboard");

    // Сбор метрик производительности и скриншота
    var screenshot = browser.getScreenshot();
    var result = browser.getResult();
    result.screenshot = screenshot;

    // Возврат JSON с откликом родительскому элементу
    return JSON.stringify(result);
} catch (err) {
    var screenshot = browser.getScreenshot();
    return JSON.stringify({"error": err.message, "screenshot": screenshot});
}
// Сессия WebDriver завершается автоматически при уничтожении объекта Browser:
// отдельный метод quit() не требуется.
```

3. Создайте **Dependent Items** (зависимые элементы данных), используя шаги предобработки (JSONPath), чтобы извлечь отдельные метрики производительности из полученного JSON. Для извлечения скриншота создайте Dependent Item с типом информации **Binary** (Base64-декод через предобработку). Скриншот доступен в истории элементов данных и может быть добавлен на дашборд.

*Тестирование Browser Item выполняйте в UI: кнопка **Test** (Get value and test) — вы увидите JSON, который вернет скрипт, а при исключении — `error`. Selenium должен быть доступен по сети с Zabbix Server/Proxy (при удаленном WebDriver проверьте firewall/NSG).*

#### 3. Мониторинг WebDriver (Selenium)

Так как WebDriver-компонент стал критически важным, его состояние следует мониторить отдельно. Standalone Selenium Server имеет эндпоинт `/status`, возвращающий JSON с данными о готовности браузера (см. **[Определения и основы Zabbix](./definitions_and_concepts.md)**).

```json
{
  "value": {
    "ready": true,
    "message": "Selenium Grid ready.",
    "nodes": [ { "id": "...", "slots": { "chrome": { "max": 1, "lastRegistrationError": "" } } } ]
  }
}
```

* Элемент на хосте WebDriver через `HTTP agent` с ключом `selenium.status` и предобработкой JSONPath `$.value.ready` (возвращает `1`/`0`);
* Триггер: `last(/host/selenium.status)=0` → severity High (Selenium недоступен — Browser items не выполняются).
* Для расширения пропускной способности применяют **Selenium Grid** (несколько браузерных контейнеров, зарегистрированных на общем хабе) или запуск параллельных standalone-контейнеров.

---

### Метод 2: Мониторинг через Web Scenarios (Встроенный HTTP-клиент)

Оптимальный подход для быстрой проверки статических сайтов и API.

1. Перейдите в конфигурацию хоста → вкладка **Web scenarios** → **Create web scenario**.
2. **Name:** `API Health Check`.
3. Вкладка **Steps** (Шаги):
   * **Step 1 (Check Homepage):**
     * URL: `https://api.example.com/health`
     * Required string: `"status":"UP"` *(Обязательное условие: проверяйте бизнес-логику, а не только HTTP-код)*.
     * Required status codes: `200`.
4. На основе сценария Zabbix автоматически создаст элементы данных для скорости загрузки и кодов ответа, на которые можно настроить триггеры.

**Расширенные возможности шага:**
* **Variables (переменные)** — объявите переменные сценария, в т.ч. с извлечением значения из тела ответа по регулярному выражению (например, `{csrftok}` → `regex:([0-9a-f]{32})`); переменные можно использовать в Headers и Post data последующих шагов.
* **Post data и Headers** (например, `Authorization: Bearer {token}`) — передача данных формы/JSON и авторизация.
* **Follow redirects** — следование за редиректами; **Timeout** — лимит ожидания ответа на шаг (по умолчанию 15s).
* **Required string и Regex проверки** — проверка тела ответа на бизнес-условие (не только HTTP-код).
* **TLS-верификация:** `Verify host` / `Verify peer` — проверка сертификата; клиентская аутентификация SSL-сертификатами (PEM-файлы).
* **Authentication:** Basic, NTLM, Kerberos, Digest авторизация на уровне всего сценария.

---

### Метод 3: Мониторинг через внешний Python-скрипт (UserParameter)

Данный сценарий описывает настройку глубоко кастомизированной проверки с использованием Python 3 на стороне агента.

#### Шаг 1. Подготовка скрипта на сервере

Скрипт располагается на сервере с установленным Zabbix Agent (2).

1. Создайте директорию и файл скрипта:
   ```bash
   sudo mkdir -p /opt/monitoring
   sudo nano /opt/monitoring/site-check.py
   ```
2. Пример логики скрипта (Python 3):
   * Скрипт использует стандартные библиотеки `sys`, `urllib.request`, `ssl` (без внешних зависимостей).
   * При успешной проверке скрипт обязан вывести в `stdout` значение `1`, при ошибке — `0` (Zabbix как значение элемента возьмет последнюю строку вывода).

   ```python
   #!/usr/bin/env python3
   import sys
   import urllib.request
   import ssl

   url = sys.argv[1] if len(sys.argv) > 1 else "https://example.com/login"

   ctx = ssl.create_default_context()
   ctx.check_hostname = False
   ctx.verify_mode = ssl.CERT_NONE

   try:
       with urllib.request.urlopen(url, timeout=10, context=ctx) as resp:
           body = resp.read().decode("utf-8", errors="ignore")
           ok = resp.status == 200 and "Dashboard" in body
   except Exception:
       ok = False

   print("1" if ok else "0")
   ```

3. Установите права доступа:
   ```bash
   # Делаем скрипт исполняемым
   sudo chmod +x /opt/monitoring/site-check.py
   # Меняем группу на zabbix для предоставления прав агенту
   sudo chown root:zabbix /opt/monitoring/site-check.py
   ```

#### Шаг 2. Настройка Zabbix Agent

Необходимо объявить новый пользовательский параметр (**UserParameter**), чтобы агент мог запускать скрипт и передавать вывод серверу.

1. Отредактируйте конфигурацию агента (Agent 2, ветка 7.0/7.4: `/etc/zabbix/zabbix_agent2.conf`; классический агент — `/etc/zabbix/zabbix_agentd.conf`).
2. Добавьте параметр:
   ```bash
   # site.auth — уникальный ключ метрики, далее абсолютный путь к скрипту
   UserParameter=site.auth,/opt/monitoring/site-check.py
   ```
3. Перезапустите службу агента:
   ```bash
   sudo systemctl restart zabbix-agent2.service
   # → (пусто при успехе)
   ```
4. Проверьте работоспособность ключа локально (Agent 2: `zabbix_agent2 -t site.auth`; классический агент: `zabbix_agentd -t site.auth`):
   ```bash
   zabbix_agent2 -t site.auth
   # → site.auth [u]: 1
   ```
5. Если агент выполняет скрипт от пользователя `zabbix` — проверьте вывод под его правами:
   ```bash
   sudo -u zabbix /opt/monitoring/site-check.py
   # → 1
   ```

#### Шаг 3. Настройка конфигурации в веб-интерфейсе Zabbix

1. **Создание шаблона:**
   * `Configuration` → `Templates` → `Create template` (напр. `Template Custom Website Monitoring`).
2. **Создание элемента данных (Item):**
   * В созданном шаблоне перейдите в раздел `Items` → `Create item`.
   * **Name:** `Website Custom Availability Check`.
   * **Key:** `site.auth` (должен строго совпадать с ключом из конфигурации агента).
   * **Type:** `Zabbix agent` (для активного режима — `Zabbix agent (active)`).
   * **Type of information:** `Numeric (unsigned)`.
   * **Update interval:** `1m`.
3. **Создание триггера:**
   * В шаблоне перейдите в `Triggers` → `Create trigger`.
   * **Name:** `Website authorization failed on {HOST.NAME}`.
   * **Expression:** Логика срабатывания при двух последовательных неудачных проверках (код 0) — гистерезис:
     ```bash
     last(/Template Custom Website Monitoring/site.auth,#1)=0 and last(/Template Custom Website Monitoring/site.auth,#2)=0
     ```
   * **Severity:** `High` или `Average`.

Оба режима опроса (пассивный/активный) используют одинаковый протокол. Активный режим предпочтителен при большом количестве хостов (нагрузка на опрос переносится с сервера на агенты).

---

### Метод 4: Мониторинг SSL-сертификатов через шаблон Website Certificate by Zabbix Agent 2

Данный метод позволяет отслеживать срок действия SSL/TLS-сертификатов веб-сайтов без написания скриптов. Используется встроенный шаблон `Website certificate by Zabbix agent 2`.

#### Архитектура мониторинга

| Компонент | Назначение |
| :--- | :--- |
| **Хост (Host)** | Сущность в Zabbix, к которой прикреплен шаблон и указан адрес агента |
| **Шаблон (Template)** | Содержит элементы данных и триггеры; в макросе `{$CERT.WEBSITE.HOSTNAME}` указывается целевой сайт |
| **Zabbix Agent 2** | Сбор данных о сертификате с хоста, имеющего стабильный доступ в интернет |

Zabbix Agent 2 с одного из мониторинговых хостов выполняет проверку SSL-сертификата удаленного сайта.

#### Установка шаблона

Шаблон `Website certificate by Zabbix agent 2` может отсутствовать в системе (особенно после обновления Zabbix).

1. Проверьте наличие шаблона: `Configuration` → `Templates`.
2. При отсутствии загрузите шаблон с [официального репозитория Zabbix](https://git.zabbix.com/projects/ZBX/repos/zabbix/browse/templates/app/zabbix_agent2) (выберите версию, соответствующую вашей инсталляции).
3. Импортируйте: `Configuration` → `Templates` → `Import` → выберите YAML-файл → `Import`.

> **Возможная ошибка импорта:** `Invalid tag "/zabbix_export/version": unsupported version number`. В этом случае вручную измените версию в YAML-файле шаблона на совместимую (например, `7.0` или `7.4`).

#### Установка Zabbix Agent 2

Агент должен быть установлен на хосте со стабильным интернет-доступом (изолированный периметр не подойдет). При наличии старого агента — остановите его.

**Установка на Ubuntu 24.04 / Zabbix 7.4:**

```bash
wget https://repo.zabbix.com/zabbix/7.4/release/ubuntu/pool/main/z/zabbix-release/zabbix-release_latest+ubuntu24.04_all.deb
dpkg -i zabbix-release_latest+ubuntu24.04_all.deb
apt update
apt install zabbix-agent2 zabbix-agent2-plugin-*
systemctl restart zabbix-agent2
systemctl enable zabbix-agent2
```

Актуальные ссылки для других ОС и версий — на [официальном сайте Zabbix](https://www.zabbix.com/download?zabbix=7.4).

#### Добавление хоста для мониторинга

1. Перейдите: `Configuration` → `Hosts` → `Create new host`.
2. Заполните параметры:
   * **Host name:** рекомендуется использовать имя мониторимого сайта (например, `example.com-cert`).
   * **Templates:** прикрепите `Website certificate by Zabbix agent 2`.
   * **Groups:** добавьте хост в группу (например, `SSL Certificates`).
   * **Interfaces:** `Add` → `Agent`, укажите адрес или DNS хоста с Zabbix Agent 2.
3. Перейдите на вкладку **Macros** → **Inherited and host macros**.
4. Найдите макрос `{$CERT.WEBSITE.HOSTNAME}` и нажмите **Change** → введите домен сайта (например, `example.com`).
5. Сохраните хост.

Проверьте поступление данных: `Monitoring` → `Latest data`.

#### Настройка порога срабатывания триггера

Встроенный триггер срабатывает при приближении даты окончания сертификата. Порог определяется макросом `{$CERT.EXPIRY.WARN}`.

| Вариант | Область действия | Путь настройки |
| :--- | :--- | :--- |
| **Глобальный** | Все хосты с шаблоном | `Configuration` → `Templates` → `Website certificate by Zabbix agent 2` → `Macros` |
| **Хост-специфичный** | Конкретный хост | `Configuration` → `Hosts` → выберите хост → `Macros` → **Change** |

Значение указывается в днях (по умолчанию обычно `14` или `21`).

#### Добавление поля Days Left (Calculated Item)

Шаблон содержит дату окончания (`cert.not_after`), но не отображает количество оставшихся дней. Для визуализации добавьте вычисляемый элемент данных (**Calculated Item**) в шаблон:

1. `Configuration` → `Templates` → `Website certificate by Zabbix agent 2` → `Items` → `Create item`.
2. Заполните параметры:
   * **Name:** `Cert: Days left`
   * **Type:** `Calculated`
   * **Key:** `cert.days_left`
   * **Type of information:** `Numeric (float)`
   * **Formula:**
     ```bash
     round(((last(//cert.not_after) - now()) / 86400),1)
     ```
   * **Units:** `days`
   * **Update interval:** `1m` (или требуемый интервал)

Теперь в `Latest data` появится элемент с количеством дней до истечения сертификата.

#### Создание виджета на дашборде

1. Объедините хосты мониторинга SSL в одну группу (например, `SSL Certificates`).
2. Перейдите: `Monitoring` → `Dashboard` → `Create Dashboard` (или откройте существующий).
3. Добавьте виджет **Data overview**:
   * **Data set:** выберите группу хостов `SSL Certificates`.
   * **Items:** выберите `Cert: Days left` (или `cert.not_after`).
4. Сохраните дашборд.

Виджет отобразит оставшиеся дни для всех мониторимых сертификатов.

---

## Настройка SLA и оповещений

Данные механизмы применимы к любому из выбранных выше методов.

### Настройка SLA (Service Level Agreement)

Инструмент SLA в Zabbix (6.0+) позволяет вычислять и визуализировать процент времени доступности (Uptime) в разрезе сервисов и их SLO-целей.

1. **Создание сервисного дерева:**
   * `Services` → `Create service`.
   * Построение дерева: листовые узлы сервисов (например, `WebPortal → API → DB`) с тегами, на которые ссылаются триггеры; дочерние показатели агрегируются в родительский сервис.
   * Назначьте соответствующий тег (например, `Service: WebPortal`). В конфигурации триггеров (из шагов выше) должен присутствовать аналогичный тег для привязки проблем к данному сервису.
2. **Настройка параметров SLA:**
   * `Services` → `SLA` → `Create SLA`.
   * **Name:** `Web Portal Availability SLA`.
   * **SLO:** Целевой показатель (например, `99.9%`).
   * **Reporting period:** `Quarterly` (Квартал) или `Monthly`.
   * Привяжите созданный Service к данному SLA и укажите, какие именно теги проблем учитываются в расчёте (Service tags / Problem tags).
3. **Дашборд SLA:** добавьте виджет **SLA report** (настраивается через `Monitoring` → `Dashboard`). Он отображает SLI за каждый период; периоды, нарушающие заданный SLO, выделяются красным. Количество отображаемых периодов и даты задаются параметрами **Show periods**, **From**, **To**.

### Настройка каналов оповещений (Actions)

1. **Настройка почтового шлюза (Media Type):**
   * `Administration` → `Media types` → `Email`.
   * Укажите технические параметры SMTP-сервера (Server, Port, HELO, Email).
   * Активируйте Media Type после тестовой отправки (кнопка `Test`).
2. **Определение получателей:**
   * Создайте группу: `User groups` → `Create user group` (например, `Alert Administrators`). Назначьте права `Read` на группу хостов с мониторингом.
   * Создайте пользователя: `Users` → `Create user`. На вкладке **Media** добавьте способ связи (Email) и укажите адрес получателя.
3. **Настройка реакции (Action):**
   * `Configuration` → `Actions` → `Trigger actions` → `Create action`.
   * **Conditions:** Выберите тег сервиса (например, `Service: WebPortal`) или конкретный шаблон.
   * **Operations:** Добавьте операцию отправки сообщения (`Send message`) созданной группе `Alert Administrators` через тип медиа `Email`. Для эскалации добавьте несколько операций с интервалами повторов.

---

## Итоговая визуализация

Отображение метрик доступности, графиков времени ответа и показателей SLA/SLI выносится на дашборды (внутренние или внешние). Инструкции по настройке панелей (включая использование плагина Zabbix Data Source) доступны в разделе:
**[Источники данных и интеграция с Grafana](../Grafana/grafana_datasources.md)**.

---

## Дополнительная информация

### См. также

* **[Определения и концепции Zabbix](./definitions_and_concepts.md)** — архитектурный обзор системы и базовые термины.
* **[Лучшие практики настройки](./zabbix_best_practices.md)** — рекомендации по написанию триггеров, гистерезису и тегированию.
* **[Тюнинг и производительность](./zabbix_troubleshooting_and_performance_tuning.md)** — оптимизация инфраструктуры мониторинга и процессов Browser Poller.

### Источники и ссылки

* Официальная документация Zabbix 7.4: [https://www.zabbix.com/documentation/7.4/en/manual](https://www.zabbix.com/documentation/7.4/en/manual) (для текущей LTS-ветки 7.0 — [/documentation/7.0/en/manual](https://www.zabbix.com/documentation/7.0/en/manual))
* Browser item (JS API, объекты `Browser`/`Element`): [https://www.zabbix.com/documentation/7.4/en/manual/config/items/itemtypes/browser](https://www.zabbix.com/documentation/7.4/en/manual/config/items/itemtypes/browser)
* Release Notes Zabbix 7.4.0: [https://www.zabbix.com/rn/rn7.4.0](https://www.zabbix.com/rn/rn7.4.0)
* Roadmap Zabbix: [https://www.zabbix.com/roadmap](https://www.zabbix.com/roadmap)
