# Мониторинг веб-сайтов в Zabbix: скрипты, сценарии и Browser Items

## Определения

* **Внешний скрипт (External Check / UserParameter)** — метод мониторинга, при котором Zabbix Agent запускает исполняемый файл (Bash, Python) и использует его вывод как метрику. Обеспечивает максимальную гибкость.
* **Web Scenario (Веб-сценарий)** — встроенный в Zabbix механизм для выполнения последовательности HTTP-запросов. Оптимален для проверки REST API и простых сайтов без сложного JavaScript.
* **Синтетический мониторинг (Synthetic Monitoring)** — эмуляция действий реального пользователя (клики, ввод текста) для оценки работоспособности сложных веб-приложений (SPA). Реализован в Zabbix 7.0 через **Browser Items**.
* **Browser Item** — тип элемента данных, управляющий реальным браузером через Selenium WebDriver (по протоколу W3C WebDriver) с помощью скриптов на JavaScript.
* **SLA (Service Level Agreement)** — инструмент Zabbix для измерения уровня доступности (Availability) IT-услуг на основе данных от элементов мониторинга.

---

## Основные концепции: Выбор метода мониторинга

Для мониторинга веб-ресурсов в Zabbix применяются три основных подхода. Выбор зависит от сложности целевого приложения:

1. **Web Scenarios:** Встроенный инструмент ядра. Не требует стороннего ПО. Отправляет GET/POST запросы, проверяет HTTP-коды (200 OK) и наличие подстрок в теле ответа. Не умеет исполнять JavaScript.
2. **Browser Items (Zabbix 7.0+):** Полноценный синтетический мониторинг. Требует развертывания Selenium WebDriver. Позволяет авторизоваться на сайтах с CAPTCHA/MFA (если есть обходной путь), собирать метрики производительности (Navigation Timing API) и сохранять скриншоты ошибок в БД Zabbix (тип данных `Binary`).
3. **Кастомные скрипты (UserParameter):** Классический подход. Используется, когда требуется сложная нестандартная логика (например, авторизация через корпоративный SSO с использованием специфических криптографических библиотек Python), не реализуемая через Web Scenarios или JavaScript.

---

## Практические сценарии

### Метод 1: Синтетический мониторинг через Browser Items (Zabbix 7.0+)

Позволяет полноценно взаимодействовать с элементами страницы (DOM) и получать визуальное подтверждение сбоев.

#### 1. Развертывание Selenium WebDriver
Для работы Browser Items требуется запущенный экземпляр Selenium (рекомендуется использовать Docker):
```bash
docker run -d -p 4444:4444 --shm-size=2g selenium/standalone-chrome
```
В конфигурационном файле `zabbix_server.conf` (или `zabbix_proxy.conf`, если проверки идут через прокси) укажите адрес WebDriver:
`WebDriverURL=http://localhost:4444`
Перезапустите Zabbix Server/Proxy.

#### 2. Настройка Browser Item в веб-интерфейсе
1. Создайте Item с типом **Browser**.
2. В поле **Script** укажите код логики на встроенном диалекте JavaScript:
```javascript
var browser = new Browser(Browser.chromeOptions());
try {
    browser.navigate("https://example.com/login");
    
    // Поиск элементов и ввод данных
    browser.findElement("css selector", "input[name='user']").sendKeys("admin");
    browser.findElement("css selector", "input[name='pass']").sendKeys("password123");
    browser.findElement("css selector", "button#submit").click();
    
    // Проверка успешной авторизации по наличию элемента
    browser.findElement("link text", "Dashboard");
    
    // Сбор метрик производительности и скриншота
    var screenshot = browser.getScreenshot();
    var result = browser.getResult();
    result.screenshot = screenshot;
    
    // Возврат JSON
    return JSON.stringify(result);
} catch (err) {
    var screenshot = browser.getScreenshot();
    return JSON.stringify({"error": err.message, "screenshot": screenshot});
} finally {
    browser.quit();
}
```
3. Создайте **Dependent Items** (зависимые элементы данных), используя шаги предобработки (JSONPath), чтобы извлечь отдельные метрики производительности из полученного JSON. Для извлечения скриншота создайте Dependent Item с типом информации **Binary**.

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

---

### Метод 3: Мониторинг через внешний Python-скрипт (UserParameter)

Данный сценарий описывает настройку глубоко кастомизированной проверки с использованием Python 3 на стороне агента.

#### Шаг 1. Подготовка скрипта на сервере

Скрипт располагается на сервере с установленным Zabbix Agent.

1. Создайте директорию и файл скрипта:
   ```bash
   sudo mkdir -p /opt/monitoring
   sudo nano /opt/monitoring/site-check.py
   ```
2. Пример логики скрипта (Python 3):
   * Скрипт использует библиотеки `requests`, `sys`, `warnings`.
   * При успешной проверке скрипт обязан вывести в stdout `1`, при ошибке — `0`.
3. Установите права доступа:
   ```bash
   # Делаем скрипт исполняемым
   sudo chmod +x /opt/monitoring/site-check.py
   # Меняем группу на zabbix для предоставления прав агенту
   sudo chown root:zabbix /opt/monitoring/site-check.py
   ```

#### Шаг 2. Настройка Zabbix Agent

Необходимо объявить новый пользовательский параметр (`UserParameter`), чтобы агент мог запускать скрипт и передавать вывод серверу.

1. Отредактируйте конфигурацию агента:
   ```bash
   sudo nano /etc/zabbix/zabbix_agentd.conf
   ```
2. Добавьте параметр `UserParameter`:
   ```bash
   # site.auth — уникальный ключ метрики, далее абсолютный путь к исполняемому файлу
   UserParameter=site.auth,/opt/monitoring/site-check.py
   ```
3. Перезапустите службу агента:
   ```bash
   sudo systemctl restart zabbix-agent.service
   ```
4. Проверьте работоспособность ключа локально из командной строки:
   ```bash
   zabbix_agentd -t site.auth
   ```

#### Шаг 3. Настройка конфигурации в веб-интерфейсе Zabbix

1. **Создание шаблона:**
   * `Configuration` → `Templates` → `Create template` (напр. `Template Custom Website Monitoring`).
2. **Создание элемента данных (Item):**
   * В созданном шаблоне перейдите в `Items` → `Create item`.
   * **Name:** `Website Custom Availability Check`.
   * **Key:** `site.auth` (должен строго совпадать с ключом из `zabbix_agentd.conf`).
   * **Type:** `Zabbix agent`.
   * **Type of information:** `Numeric (unsigned)`.
   * **Update interval:** `1m`.
3. **Создание триггера:**
   * В шаблоне перейдите в `Triggers` → `Create trigger`.
   * **Name:** `Website authorization failed on {HOST.NAME}`.
   * **Expression:** Логика срабатывания (гистерезис) при двух последовательных неудачных проверках (код 0):
     ```bash
     last(/Template Custom Website Monitoring/site.auth,#1)=0 and last(/Template Custom Website Monitoring/site.auth,#2)=0
     ```
   * **Severity:** `High` или `Average`.

---

## Настройка SLA и оповещений

Данные механизмы применимы к любому из выбранных выше методов.

### Настройка SLA (Service Level Agreement)

Инструмент SLA позволяет вычислять и визуализировать процент времени аптайма (Uptime).

1. **Создание сервиса (Service):**
   * `Services` → `Services` → `Create service`.
   * Назначьте соответствующий тег (например, `Service: WebPortal`). В конфигурации триггеров (из шагов выше) должен присутствовать аналогичный тег для привязки проблем к данному сервису.
2. **Настройка параметров SLA:**
   * `Services` → `SLA` → `Create SLA`.
   * **Name:** `Web Portal Availability SLA`.
   * **SLO:** Целевой показатель (например, `99.9%`).
   * **Reporting period:** `Quarterly` (Квартал) или `Monthly`.
   * Привяжите созданный Service к данному SLA.

### Настройка каналов оповещений (Actions)

1. **Настройка почтового шлюза (Media Type):**
   * `Administration` → `Media types` → `Email`.
   * Укажите технические параметры SMTP-сервера (Server, Port, HELO, Email).
2. **Определение получателей:**
   * Создайте группу: `User groups` → `Create user group` (напр. `Alert Administrators`). Назначьте права `Read` на группу хостов с мониторингом.
   * Создайте пользователя: `Users` → `Create user`. На вкладке **Media** добавьте способ связи (Email) и укажите адрес получателя.
3. **Настройка реакции (Action):**
   * `Configuration` → `Actions` → `Trigger actions` → `Create action`.
   * **Conditions:** Выберите тег сервиса (напр. `Service: WebPortal`) или конкретный шаблон.
   * **Operations:** Добавьте операцию отправки сообщения (`Send message`) созданной группе `Alert Administrators` через тип медиа `Email`.

---

## Итоговая визуализация

Отображение метрик доступности, графиков времени ответа и показателей SLA/SLI обычно выносится на внешние дашборды. Инструкции по настройке панелей (включая использование плагина Zabbix Data Source) доступны в разделе:
**[Источники данных и интеграция с Grafana](../Grafana/grafana_datasources.md)**.

---

## Дополнительная информация

### См. также

* **[Определения и концепции Zabbix](./definitions_and_concepts.md)** — архитектурный обзор системы и базовые термины.
* **[Лучшие практики настройки](./zabbix_best_practices.md)** — рекомендации по написанию триггеров, гистерезису и тегированию.
* **[Тюнинг и производительность](./zabbix_troubleshooting_and_performance_tuning.md)** — оптимизация инфраструктуры мониторинга.