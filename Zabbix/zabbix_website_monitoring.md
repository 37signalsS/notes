# Мониторинг веб-сайтов в Zabbix с помощью внешних скриптов

## Определения

* **Внешний скрипт (External Check)** — метод мониторинга, при котором Zabbix Server или Agent запускает исполняемый файл (скрипт) и использует возвращаемое им значение как метрику.
* **UserParameter** — директива в конфигурации Zabbix Agent, позволяющая расширить стандартный набор метрик пользовательскими командами.
* **SLA (Service Level Agreement)** — в контексте Zabbix это инструмент для измерения уровня доступности (Availability) IT-услуг на основе данных от элементов мониторинга.

---

## Практические сценарии

### Настройка мониторинга доступности сайта (Часть 1)

Сценарий описывает настройку проверки кода ответа HTTP (200 OK) и успешности авторизации с использованием Python-скрипта.

#### Шаг 1. Подготовка скрипта на сервере

Скрипт должен располагаться на сервере с установленным Zabbix Agent (в данном примере — на самом Zabbix Server).

1. Создайте директорию и файл скрипта:
   ```bash
   sudo mkdir -p /opt/monitoring
   sudo nano /opt/monitoring/site-check.py
   ```
2. Пример логики скрипта (Python 3):
   * Скрипт использует библиотеки `requests`, `sys`, `warnings`.
   * При успешной проверке возвращает `1`, при ошибке — `0`.
3. Установите права доступа:
   ```bash
   # Делаем исполняемым
   sudo chmod +x /opt/monitoring/site-check.py
   # Меняем группу на zabbix для возможности запуска агентом
   sudo chown root:zabbix /opt/monitoring/site-check.py
   ```

#### Шаг 2. Настройка Zabbix Agent

Необходимо объявить новый пользовательский параметр, чтобы агент мог передавать данные скрипта серверу.

1. Отредактируйте конфигурацию агента:
   ```bash
   sudo nano /etc/zabbix/zabbix_agentd.conf
   ```
2. Добавьте параметр `UserParameter`:
   ```bash
   # site.auth — ключ метрики, далее путь к исполняемому файлу
   UserParameter=site.auth,/opt/monitoring/site-check.py
   ```
3. Перезапустите службу:
   ```bash
   sudo systemctl restart zabbix-agent.service
   ```
4. Проверьте работоспособность ключа локально:
   ```bash
   zabbix_agentd -t site.auth
   ```

#### Шаг 3. Настройка в веб-интерфейсе Zabbix

1. **Создание шаблона:**
   * `Configuration` → `Templates` → `Create template` (напр. `Template Website Monitoring`).
2. **Создание элемента данных (Item):**
   * В шаблоне перейдите в `Items` → `Create item`.
   * **Name:** `Website Availability Check`.
   * **Key:** `site.auth`.
   * **Type:** `Zabbix agent`.
   * **Type of information:** `Numeric (unsigned)`.
   * **Update interval:** `1m`.
3. **Создание триггера:**
   * В шаблоне перейдите в `Triggers` → `Create trigger`.
   * **Name:** `Website authorization failed on {HOST.NAME}`.
   * **Expression:** Логика срабатывания при двух последовательных неудачных проверках (код 0):
     ```bash
     last(/Template Website Monitoring/site.auth,#1)=0 and last(/Template Website Monitoring/site.auth,#2)=0
     ```
   * **Severity:** `High` или `Average`.

#### Шаг 4. Настройка SLA

Инструмент SLA позволяет визуализировать процент времени аптайма (Uptime) за период.

1. **Настройка SLA:**
   * `Services` → `SLA` → `Create SLA`.
   * **Name:** `Website Availability SLA`.
   * **Reporting period:** `Quarterly` (или другой необходимый период).
2. **Создание сервиса:**
   * `Services` → `Services` → `Create service`.
   * Назначьте соответствующий тег (например, `Service: Website`), указанный в триггере, для привязки данных.

---

### Настройка оповещений и визуализации (Часть 2)

Этот этап включает настройку каналов уведомлений для администраторов и построение дашборда в Grafana.

#### Шаг 5. Настройка оповещений в Zabbix

1. **Настройка почтового сервера (Media Type):**
   * `Administration` → `Media types` → `Email`.
   * Укажите параметры вашего SMTP-сервера (Server, Port, HELO, Email).
2. **Создание группы пользователей:**
   * `User groups` → `Create user group` (напр. `Alert Administrators`).
   * **Permissions:** Укажите права `Read` на группу хостов, где запущен мониторинг (напр. `Zabbix servers`).
3. **Создание пользователя:**
   * `Users` → `Create user`.
   * Вкладка **Media**: Добавьте способ связи (Email) и укажите адрес получателя.
4. **Настройка действия (Action):**
   * `Configuration` → `Actions` → `Trigger actions` → `Create action`.
   * **Conditions:** Выберите созданный ранее триггер или шаблон.
   * **Operations:** Добавьте операцию отправки сообщения группе `Alert Administrators` через `Email`.

#### Шаг 6. Визуализация в Grafana

Предполагается, что в Grafana установлен и настроен плагин **Zabbix Data Source**. Подробнее: **[Источники данных в Grafana](../Grafana/grafana_datasources.md)**.

1. **Создание панели:**
   * Добавьте новую панель типа `Stat`.
2. **Настройка запросов (Query):**
   * **Query A (Статус триггера):**
     * Query type: `Triggers`.
     * Group: Имя вашей группы хостов.
     * Host: Имя хоста.
     * Application/Problem: Выберите ваш триггер.
     * Count: `On`.
   * **Query B (SLA/SLI):**
     * Query type: `Services`.
     * Service: Имя вашего сервиса.
     * SLA: Имя вашего SLA.
     * Property: `SLI`.
3. **Настройка отображения (Transform):**
   * Используйте `Rename by regex` для изменения имен метрик на понятные (напр. `Status` и `Availability %`).
   * Настройте `Filter by name`, чтобы оставить только нужные значения.

---

## Итоговая схема мониторинга

1. **Zabbix Agent** раз в минуту запускает Python-скрипт через `UserParameter`.
2. **Zabbix Server** получает код ответа (1 или 0) и сохраняет его в истории.
3. **Триггер** анализирует последние 2 значения: если оба равны 0, генерируется проблема.
4. **Action** отправляет Email-уведомление администратору.
5. **Grafana** запрашивает данные через API Zabbix и отображает текущий статус и процент доступности (SLA) на дашборде.

---

## Дополнительная информация

### См. также

* **[Веб-мониторинг (встроенный)](./definitions_and_concepts.md#способы-получения-данных)** — альтернативный метод без использования скриптов.
* **[Дашборды в Grafana](../Grafana/grafana-dashboards.md)** — общие принципы построения визуализаций.
* **[Управление пользователями в Grafana](../Grafana/grafana_user_management_and_authentication.md)** — настройка прав доступа.
