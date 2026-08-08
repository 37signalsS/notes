# Мониторинг веб-сайтов в Zabbix: скрипты, сценарии и Browser Items

## Определения

* **Внешний скрипт (External Check / UserParameter)** — метод мониторинга, при котором Zabbix Agent запускает исполняемый скрипт и использует его стандартный вывод как значение метрики. Обеспечивает максимальную гибкость и возможность любой нестандартной логики (SSO, криптографические библиотеки).
* **Web Scenario (Веб-сценарий)** — встроенный в Zabbix механизм для выполнения последовательности HTTP-запросов. Оптимален для проверки REST API и простых сайтов без сложного JavaScript.
* **Синтетический мониторинг (Synthetic Monitoring)** — эмуляция действий реального пользователя (клики, ввод текста) для оценки работоспособности сложных веб-приложений (SPA). Реализован в Zabbix 7.0 через **Browser Items**.
* **Browser Item** — тип элемента данных, который выполняет JavaScript-скрипт (диалект Duktape) в реальном браузере через Selenium WebDriver (протокол W3C WebDriver). Обрабатывается на Zabbix Server/Proxy процессом `browser poller`.
* **Selenium WebDriver** — серверная прослойка автоматизации браузера, к которой Zabbix подключается по HTTP(S), указывая адрес в параметре `WebDriverURL`. Стандартный способ развертывания — Docker-образ `selenium/standalone-chrome`.
* **Зависимый элемент данных (Dependent Item)** — элемент без собственного опроса: он получает отклик «материнского» элемента и извлекает нужные значения способом предобработки (JSONPath/Regex). Для Browser Item применяется для разбора JSON-отклика, в т.ч. для сохранения скриншотов (тип Binary).
* **SLA (Service Level Agreement)** — раздел Services: рассчитывает показатель доступности (Availability) и SLO/SLI для сервисов на основе тегов триггеров.

---

## Основные концепции: Выбор метода мониторинга

Для мониторинга веб-ресурсов в Zabbix применяются три основных подхода. Выбор зависит от сложности целевого приложения:

| Реализация | JavaScript | Стороннее ПО | Нагрузка на ресурсы | Когда использовать |
| :--- | :---: | :---: | :---: | :--- |
| **Web Scenarios** | Нет | Нет | Низкая | REST API, статические сайты |
| **Browser Items** (7.0+) | Да (полный браузер) | Selenium WebDriver | Высокая (RAM браузера) | SPA, авторизация, скриншоты |
| **Custom Python Scripts** (UserParameter) | Не требуется | Скрипт на хосте | Низкая | Специфическая логика, криптография |

1. **Web Scenarios:** Встроенный инструмент ядра. Не требует стороннего ПО. Отправляет GET/POST запросы, проверяет HTTP-коды (200 OK) и наличие подстрок в теле ответа. Не умеет исполнять JavaScript.
2. **Browser Items (Zabbix 7.0+):** Полноценный синтетический мониторинг. Требует развертывания Selenium WebDriver. Позволяет авторизоваться на сайтах с CAPTCHA/MFA (если есть обходной путь), собирать метрики производительности (Navigation Timing API) и сохранять скриншоты ошибок в БД Zabbix (тип данных `Binary`).
3. **Кастомные скрипты (UserParameter):** Классический подход. Используется, когда требуется сложная нестандартная логика (например, авторизация через корпоративный SSO с использованием специфических криптографических библиотек Python), не реализуемая через Web Scenarios или JavaScript.

---

## Практические сценарии

### Метод 1: Синтетический мониторинг через Browser Items (Zabbix 7.0+)

Позволяет полноценно взаимодействовать с элементами страницы (DOM) и получать визуальное подтверждение сбоев.

#### 1. Развертывание Selenium WebDriver

Для работы Browser Items требуется запущенный экземпляр Selenium WebDriver (рекомендуется использовать контейнер):

```bash
docker run -d -p 4444:4444 --shm-size=2g selenium/standalone-chrome
# → <CONTAINER_ID> (идентификатор запущенного контейнера)
```

*Контейнер с браузером требует существенного объема оперативной памяти (обычно >2 ГБ), учитывайте это при планировании ресурсов Zabbix Server/Proxy.*

В конфигурационном файле `zabbix_server.conf` (или `zabbix_proxy.conf`, если проверки идут через прокси) укажите адрес WebDriver и число процессов-обработчиков:

```bash
### Option: WebDriverURL
WebDriverURL=http://localhost:4444

### Option: StartBrowserPollers
# Количество pre-forked браузерных воркеров (по умолчанию 1).
# Увеличьте при большом числе Browser items.
StartBrowserPollers=2
```

Перезапустите Zabbix Server/Proxy:
```bash
systemctl restart zabbix-server
# → (без вывода при успешном перезапуске)
```

Проверьте: Browser Items обрабатывает процесс `browser poller`, поэтому доступность самого WebDriver критична. Проверка подключения к Selenium:
```bash
curl -s http://localhost:4444/status
# → {"value":{"ready":true,"message":"Selenium Grid ready.","nodes":[...]}}
```
`"ready": true` означает, что WebDriver готов принимать и выполнять сценарии.

> **Готовая основа:** вместо настройки «с нуля» можно использовать шаблон `Website By Browser` (по умолчанию доступен в Zabbix 7.x): он уже содержит items для времени навигации, ресурсов, скриншот и триггеры на доступность/производительность. В шаблоне замените только домен (макрос `{$WEBSITE.DOMAIN}`).

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
} finally {
    browser.quit();
}
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
- Элемент на хосте WebDriver через `HTTP agent` с ключом `selenium.status` и предобработкой JSONPath `$.value.ready` (возвращает `1`/`0`);
- Триггер: `last(/host/selenium.status)=0` → severity High (Selenium недоступен — Browser items не выполняются).
- Для расширения пропускной способности применяют **Selenium Grid** (несколько браузерных контейнеров, зарегистрированных на общем хабе) или запуск параллельных standalone-контейнеров.

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
- **Variables (переменные)** — объявите переменные сценария, в т.ч. с извлечением значения из тела ответа по регулярному выражению (например, `{csrftok}` → `regex:([0-9a-f]{32})`); переменные можно использовать в Headers и Post data последующих шагов.
- **Post data и Headers** (например, `Authorization: Bearer {token}`) — передача данных формы/JSON и авторизация.
- **Follow redirects** — следование за редиректами; **Timeout** — лимит ожидания ответа на шаг (по умолчанию 15s).
- **Required string и Regex проверки** — проверка тела ответа на бизнес-условие (не только HTTP-код).
- **TLS-верификация:** `Verify host` / `Verify peer` — проверка сертификата; клиентская аутентификация SSL-сертификатами (PEM-файлы).
- **Authentication:** Basic, NTLM, Kerberos, Digest авторизация на уровне всего сценария.

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
   * Скрипт использует библиотеки `requests`, `sys`, `warnings`.
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

1. Отредактируйте конфигурацию агента (Agent 2 v7.x: `/etc/zabbix/zabbix_agent2.conf`; классический агент — `/etc/zabbix/zabbix_agentd.conf`).
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
4. Проверьте работоспособность ключа локально (агентуры: `zabbix_agent2 -t site.auth`, классический — `zabbix_agentd -t site.auth`):
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

Оба режима опроса (пассивный/активный) используют одинаковый протокол. Активный режим предпочтителен при большом количестве хостов (нагрузка на опрос переносится с сервера на агентов).

---

## Настройка SLA и оповещений

Данные механизмы применимы к любому из выбранных выше методов.

### Настройка SLA (Service Level Agreement)

Инструмент SLA в Zabbix (7.0+) позволяет вычислять и визуализировать процент времени доступности (Uptime) в разрезе сервисов и их SLO-целей.

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
3. **Дашборд SLA:** виджет с метрикой SLA/SLO отражает статус `OK`/`WARNING`/`FAILED` для каждого сервиса и периодичность отчётов.

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