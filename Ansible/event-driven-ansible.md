# Event-Driven Ansible (EDA) — Реактивная автоматизация

## Определения

**Event-Driven Ansible (EDA)** является реализацией [хореографического подхода в событийной архитектуре](../Concepts/event-driven-architecture.md#2-хореография-choreography).

- **Event-Driven Ansible (EDA)** — расширение экосистемы Ansible для автоматизации реагирования на события в ИТ-инфраструктуре в режиме реального времени. EDA позволяет перейти от периодического запуска (polling) к событийной модели (push), инициируя действия на основе данных от внешних источников.
- **ansible-rulebook** — движок EDA (CLI-инструмент), который слушает источники событий, сопоставляет их с правилами и выполняет действия. Базируется на Java Drools. Современные версии (1.0+) используют асинхронную архитектуру на базе Python asyncio.
- **EDA Controller (Event-Driven Ansible Controller)** — компонент Ansible Automation Platform (AAP), предоставляющий графический интерфейс, API и возможности масштабирования для управления активациями Rulebook в корпоративной среде.
- **Event Streams (Потоки событий)** — (введено в AAP 2.5) механизм централизованного приема событий через единый endpoint (Platform Gateway) с последующей маршрутизацией к нужным правилам.
- **Rule Engine (Движок правил)** — компонент на базе Java Drools, отвечающий за логику сопоставления входящих событий с заданными условиями (Condition Matching).
- **Self-healing (Самовосстановление)** — стратегия автоматизации, при которой система самостоятельно исправляет инциденты (перезапуск сервисов, очистка диска) сразу после получения сигнала от системы мониторинга.
- **Event Feedback (Обратная связь событий)** — механизм подтверждения обработки события источником. Требует включённой персистентности (persistence) в ansible-rulebook. Позволяет источнику знать, что событие успешно обработано, и не отправлять его повторно.
- **Decision Environment (DE)** — специализированный Execution Environment, оптимизированный для запуска Rulebook. Содержит ansible-rulebook, Python-зависимости и коллекции. В AAP предоставляется как `ee-minimal` или `ee-supported`.

---

## Предпосылки и область применения

### Почему Event-Driven

Традиционная автоматизация Ansible использует модель **polling** (опроса): плейбуки запускаются по расписанию или вручную и проверяют состояние систем. Этот подход имеет ограничения:

- **Задержка реакции:** между возникновением проблемы и её исправлением проходит время до следующего запуска.
- **Лишняя нагрузка:** плейбуки опрашивают системы даже когда ничего не изменилось.
- **Пропуск событий:** кратковременные сбои могут быть не обнаружены при опросе.

EDA решает эти проблемы через модель **push**: внешняя система отправляет событие, и EDA мгновенно реагирует, запуская предопределённые действия.

### Типичные сценарии применения

| Сценарий | Источник событий | Действие |
| :--- | :--- | :--- |
| Защита от Brute Force | journald (sshd) | Блокировка IP через iptables/nftables |
| Очистка диска | Prometheus Alertmanager | Запуск плейбука очистки |
| Реакция на изменение конфига | file_watch | Перезапуск сервиса |
| Автоматическая реакция на алерты Prometheus | alertmanager | Создание инцидента, исправление |
| Мониторинг доступности URL | url_check | Уведомление, переключение |
| Обработка сообщений из Kafka | kafka | Запуск пайплайна обработки |
| Реакция на webhook от CI/CD | webhook | Обновление конфигурации |

---

## Архитектура и основные концепции

Архитектура EDA строится на декларативном описании логики в **Ansible Rulebook**:

1.  **Источники (Sources):** Плагины-адаптеры, подключающиеся к внешним системам (Webhook, Kafka, Prometheus). Источники генерируют события и помещают их в очередь для обработки движком Drools.
2.  **Фильтры событий (Event Filters):** (Опционально) Механизмы предварительной обработки данных (нормализация, очистка, разделение) до попадания в движок правил. Фильтры снижают нагрузку на память и упрощают условия в правилах.
3.  **Правила (Rules):** Логические условия (`condition`), определяющие, на какие именно данные нужно реагировать. Движок Drools выполняет Condition Matching.
4.  **Действия (Actions):** Ответная реакция (запуск плейбука, выполнение шаблона в AAP, установка фактов, генерация новых событий).

### Схема работы (Workflow)

```
Внешняя система → Источник (Source) → Фильтр (Filter) → Движок (Drools) → Правило (Rule) → Действие (Action)
```

### Жизненный цикл события

1. Внешняя система генерирует событие (HTTP POST, сообщение Kafka, алерт Prometheus).
2. Плагин-источник принимает данные и преобразует их в формат события EDA.
3. (Опционально) Фильтры обрабатывают событие: извлекают нужные поля, нормализуют ключи, разделяют пакеты.
4. Движок Drools сопоставляет событие с условиями правил (Condition Matching).
5. При срабатывании условия выполняется одно или несколько действий.
6. Действие может быть локальным (запуск плейбука) или удалённым (запуск Job Template в AAP).

---

## Миграция пространств имён (Plugin Namespace Migration)

Начиная с версии AAP 2.6/2.7, происходит миграция плагинов из коллекции `ansible.eda` в новые пространства имён. **Все новые rulebook рекомендуется писать с использованием актуальных пространств имён.**

### Builtin-модули (мигрировали в ansible-rulebook)

Следующие плагины доступны как встроенные модули `ansible-rulebook` и **рекомендуются к использованию**:

| Старое пространство имён | Новое пространство имён | Тип |
| :--- | :--- | :--- |
| `ansible.eda.webhook` | `eda.builtin.webhook` | Source |
| `ansible.eda.generic` | `eda.builtin.generic` | Source |
| `ansible.eda.range` | `eda.builtin.range` | Source |
| `ansible.eda.pg_listener` | `eda.builtin.pg_listener` | Source |
| `ansible.eda.json_filter` | `eda.builtin.json_filter` | Filter |
| `ansible.eda.normalize_keys` | `eda.builtin.normalize_keys` | Filter |
| `ansible.eda.dashes_to_underscores` | `eda.builtin.dashes_to_underscores` | Filter |
| `ansible.eda.insert_hosts_to_meta` | `eda.builtin.insert_hosts_to_meta` | Filter |

Для обратной совместимости старые имена (`ansible.eda.*`) всё ещё работают и автоматически маппятся на `eda.builtin`, но **не поддерживаются активно** в коллекции `ansible.eda`.

### Устаревшие плагины (мигрировали в community.eda)

| Старое пространство имён | Новое пространство имён | Примечание |
| :--- | :--- | :--- |
| `ansible.eda.journald` | `community.eda.journald` | Требует Decision Environment с community.eda |
| `ansible.eda.file_watch` | `community.eda.file_watch` | Требует DE с community.eda |
| `ansible.eda.file` | `community.eda.file` | Требует DE с community.eda |
| `ansible.eda.url_check` | `community.eda.url_check` | Требует DE с community.eda |
| `ansible.eda.tick` | `eda.builtin.generic` или `eda.builtin.range` | Замена |

**Важно:** При использовании плагинов из `community.eda` необходимо создать кастомный Decision Environment с соответствующими зависимостями.

---

## Установка и настройка

### Предпосылки

| Компонент | Минимальная версия | Рекомендуемая версия |
| :--- | :--- | :--- |
| Python | 3.9 | 3.11+ |
| Ansible Core | 2.15 | 2.21+ |
| ansible-rulebook | 1.0 | Последняя стабильная |
| Java Runtime Environment (JRE) | 17 | 21 |

### Установка ansible-rulebook

#### Через pip (рекомендуется для разработки)

```bash
pip install ansible-rulebook
```

Установка в виртуальное окружение (рекомендуется):

```bash
python3 -m venv ~/eda-venv
source ~/eda-venv/bin/activate
pip install ansible-rulebook ansible-core
```

#### Через контейнер (рекомендуется для production)

```bash
# Pull образа Red Hat EDA
podman pull registry.redhat.io/ansible-automation-platform-25/eda-controller-rhel9:latest

# Или использование ee-supported в AAP
ansible-navigator run --execution-environment-image ee-supported:latest
```

### Установка коллекции ansible.eda

```bash
ansible-galaxy collection install ansible.eda
```

С фиксированной версией (рекомендуется для production):

```yaml
# requirements.yml
---
collections:
  - name: ansible.eda
    version: ">=2.0.0"
```

```bash
ansible-galaxy collection install -r requirements.yml
```

### Python-зависимости

Дополнительные Python-зависимости устанавливаются отдельно:

```bash
# Для postgresql-источников
pip install psycopg

# Для конкретных плагинов — см. requirements.txt коллекции
pip install -r requirements.txt
```

---

## Ansible Rulebook

**Rulebook** — это YAML-файл, описывающий связь между источниками и действиями.

### Базовая структура и синтаксис

```yaml
---
- name: Отслеживание событий мониторинга
  hosts: all
  sources:
    - eda.builtin.webhook:
        host: 0.0.0.0
        port: 5000
  filters:
    - eda.builtin.json_filter:
        keys: [status, alertname, instance]
  rules:
    - name: Реагирование на критический алерт
      condition: event.payload.status == "critical"
      action:
        run_playbook:
          name: playbooks/fix_issue.yml
```

### Ключевые различия между Rulebook и Playbook

| Характеристика | Ansible Playbook | Ansible Rulebook |
| :--- | :--- | :--- |
| **Модель выполнения** | Императивная (список задач) | Декларативная (правила条件) |
| **Триггер** | Ручной запуск или cron | Внешнее событие |
| **Движок** | ansible-core (Python) | Drools (Java) + Python |
| **Файл инвентаря** | Обязателен | Опционален (-hosts) |
| **Состояние** | Stateless (кроме fact caching) | Stateful (set_fact, retract_fact) |

### Множественные правила в одном Rulebook

Один Rulebook может содержать несколько определений правил:

```yaml
---
- name: Мониторинг серверов
  hosts: all
  sources:
    - eda.builtin.webhook:
        host: 0.0.0.0
        port: 5000
  rules:
    - name: Критический алерт
      condition: event.payload.severity == "critical"
      action:
        run_playbook:
          name: playbooks/critical_response.yml

    - name: Предупреждение
      condition: event.payload.severity == "warning"
      action:
        run_playbook:
          name: playbooks/warning_response.yml

    - name: Информационное событие
      condition: event.payload.severity == "info"
      action:
        debug:
          msg: "Получено информационное событие: {{ event.payload }}"
```

### Ограничение хостов (Host Restriction)

Правила могут применяться только к определённым хостам:

```yaml
---
- name: Реагирование на события сети
  hosts: network_devices
  sources:
    - eda.builtin.webhook:
        host: 0.0.0.0
        port: 5001
  rules:
    - name: Сбой интерфейса
      condition: event.payload.interface_status == "down"
      action:
        run_playbook:
          name: playbooks/fix_interface.yml
```

---

## Источники событий (Sources)

### Builtin-источники (ansible-rulebook)

| Плагин | Назначение | Параметры |
| :--- | :--- | :--- |
| `eda.builtin.webhook` | Прием HTTP POST (JSON) | `host`, `port`, `token`, `jwt_token` |
| `eda.builtin.generic` | Генерация событий из Python-скрипта | `load`, `plugin_args` |
| `eda.builtin.range` | Генерация последовательности чисел | `limit`, `delay` |
| `eda.builtin.pg_listener` | PostgreSQL LISTEN/NOTIFY | `dsn`, `channels`, `delay` |

### Плагины коллекции ansible.eda / community.eda

| Плагин | Назначение | Особенности |
| :--- | :--- | :--- |
| `ansible.eda.kafka` | Подписка на топики Kafka | Подходит для обработки больших потоков логов/метрик. Требует `aiokafka`. |
| `ansible.eda.alertmanager` | Интеграция с Prometheus | Принимает алерты в нативном формате Alertmanager. |
| `community.eda.journald` | Чтение системного журнала Linux | Позволяет реагировать на специфические ошибки в системных логах. |
| `community.eda.file_watch` | Мониторинг изменений файлов | Реакция на изменение конфигов или запись в лог-файлы. |
| `community.eda.url_check` | Опрос доступности URL | Генерирует событие, если статус-код или содержимое изменились. |

### Разработка собственного плагина-источника

Собственные плагины создаются как Python-файлы с асинхронной функцией `main`. Минимальная структура:

```python
"""
my_custom_source.py
Плагин-источник для EDA.
"""
import asyncio
from typing import Any, Dict


DOCUMENTATION = r"""
---
short_description: Кастомный источник событий
description:
  - Принимает события из внешней системы через HTTP.
options:
  host:
    description: Адрес для прослушивания
    required: false
    type: str
    default: "0.0.0.0"
  port:
    description: Порт для прослушивания
    required: true
    type: int
"""


async def main(queue: asyncio.Queue, args: Dict[str, Any]):
    """
    Основная функция плагина.
    Подключается к внешней системе и помещает события в queue.
    """
    host = args.get("host", "0.0.0.0")
    port = args.get("port", 5000)

    # Пример: простой HTTP-сервер
    from aiohttp import web

    async def handle_event(request):
        data = await request.json()
        await queue.put(data)
        return web.Response(status=200)

    app = web.Application()
    app.router.add_post("/", handle_event)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()

    # Бесконечное ожидание (плагин работает пока активен rulebook)
    try:
        while True:
            await asyncio.sleep(1)
    except asyncio.CancelledError:
        await runner.cleanup()
```

Для использования в Rulebook:

```yaml
---
- name: Тест кастомного плагина
  hosts: all
  sources:
    - my_namespace.my_collection.my_custom_source:
        host: "0.0.0.0"
        port: 8080
  rules:
    - name: Обработка события
      condition: event is defined
      action:
        debug:
          msg: "Получено: {{ event }}"
```

### Event Feedback (Обратная связь)

Механизм обратной связи позволяет источнику получить подтверждение об успешной обработке события. Требует включённой персистентности в ansible-rulebook.

```yaml
---
- name: Пример с обратной связью
  hosts: all
  sources:
    - name: kafka_source
      ansible.eda.kafka:
        bootstrap_servers: "localhost:9092"
        topic: "events"
        group_id: "eda-consumer"
        feedback: true  # Включить обратную связь
  rules:
    - name: Обработка события
      condition: event is defined
      action:
        run_playbook:
          name: playbooks/process.yml
```

Когда `feedback: true`, ansible-rulebook создаёт `asyncio.Queue` и передаёт его плагину через ключ `eda_feedback_queue`. После обработки события плагин подтверждает получение:

```python
await eda_feedback_queue.put({"type": "ack", "event_id": event.get("id")})
```

---

## Фильтры событий (Event Filters)

Фильтры позволяют подготовить данные, снижая нагрузку на память и упрощая условия в правилах.

- **`eda.builtin.json_filter`:** Выбирает только необходимые поля из JSON. Снижает размер события и упрощает условия.
- **`eda.builtin.normalize_keys`:** Заменяет недопустимые символы (дефисы, точки) в именах ключей на подчеркивания.
- **`eda.builtin.dashes_to_underscores`:** Преобразует `kebab-case` в `snake_case`.
- **`eda.builtin.insert_hosts_to_meta`:** Извлекает список хостов из payload и помещает их в `meta.hosts` для ограничения выполнения плейбука.

### Пример использования фильтров

```yaml
---
- name: Фильтрация событий
  hosts: all
  sources:
    - eda.builtin.webhook:
        host: 0.0.0.0
        port: 5000
  filters:
    - eda.builtin.json_filter:
        keys:
          - alertname
          - severity
          - instance
          - description
    - eda.builtin.normalize_keys:
  rules:
    - name: Критический алерт
      condition: event.severity == "critical"
      action:
        run_playbook:
          name: playbooks/critical.yml
```

---

## Условия и логика правил (Rules)

EDA поддерживает сложные условия сопоставления:

### Простые условия

- **Сравнение значений:** `==`, `!=`, `>`, `<`, `>=`, `<=`
- **Поиск по шаблону:** `is search(pattern)` — регулярное выражение
- **Проверка существования:** `is defined`, `is not defined`
- **Проверка типа:** `is number`, `is string`

```yaml
rules:
  - name: Простое сравнение
    condition: event.status == "down"
    action:
      debug:
        msg: "Сервис недоступен"
```

### Множественные события

- **`all`:** Правило сработает, если выполнены **все** условия для набора событий (логическое И).
- **`any`:** Правило сработает при выполнении **любого** из условий (логическое ИЛИ).

```yaml
rules:
  - name: Все условия выполнены
    condition:
      all:
        - event.payload.status == "down"
        - event.payload.severity == "critical"
        - event.payload.retry_count >= 3
    action:
      run_playbook:
        name: playbooks/deep_restart.yml

  - name: Любое условие выполнено
    condition:
      any:
        - event.payload.status == "down"
        - event.payload.status == "degraded"
    action:
      run_playbook:
        name: playbooks/check_service.yml
```

### Ограничение частоты (Throttling)

- **`accumulate_within`:** Ожидание накопления событий в течение времени X (в секундах).
- **`threshold`:** Срабатывание только если событие произошло N раз за период T.
- **`max_loop`:** Максимальное количество циклов накопления.

```yaml
rules:
  - name: Реагировать только при 3+ событиях за 60 секунд
    condition:
      all:
        - event.payload.status == "error"
    throttle:
      threshold: 3
      accumulate_within: 60
    action:
      run_playbook:
        name: playbooks/alert_on_pattern.yml
```

### Использование переменных в условиях

```yaml
rules:
  - name: Динамическое условие
    condition: >
      event.payload.status == "critical" and
      event.payload.service in ["nginx", "apache", "haproxy"]
    action:
      run_playbook:
        name: playbooks/web_critical.yml
```

---

## Действия (Actions)

| Действие | Описание | Применение |
| :--- | :--- | :--- |
| **`run_playbook`** | Локальный запуск плейбука через `ansible-playbook`. | Быстрые исправления, отладка, standalone-режим. |
| **`run_module`** | Запуск модуля Ansible напрямую (без плейбука). | Простые операции (сбор фактов, перезапуск сервиса). |
| **`run_job_template`** | Запуск шаблона в AAP/AWX. | Корпоративный стандарт, RBAC, аудит, централизованное управление. |
| **`set_fact`** | Сохранение состояния в памяти Rulebook (Stateful). | Отслеживание цепочек событий, подсчёт счётчиков. |
| **`retract_fact`** | Удаление ранее установленного факта. | Сброс состояния, очистка устаревших данных. |
| **`post_event`** | Генерация нового внутреннего события. | Сложные логические каскады, передача между правилами. |
| **`debug`** | Вывод структуры события в stdout. | Тестирование и отладка. |
| **`shutdown`** | Завершение работы Rulebook. | Одноразовые сценарии, graceful shutdown. |
| **`noop`** | Ничего не делать (заглушка). | Тестирование правил без реальных действий. |

### Примеры действий

#### run_playbook

```yaml
action:
  run_playbook:
    name: playbooks/fix_issue.yml
    var_root: event.payload          # Корневая переменная для передачи
    json_timeout: 30                 # Таймаут обработки JSON
    verbosity: 1                     # Уровень детализации (-v)
```

#### run_module (прямой запуск модуля)

```yaml
action:
  run_module:
    name: ansible.builtin.systemd
    args:
      name: nginx
      state: restarted
```

#### set_fact и retract_fact (Stateful)

```yaml
rules:
  - name: Запомнить первый алерт
    condition: event.payload.status == "critical"
    action:
      set_fact:
        key: alert_count
        value: "{{ event.alert_count | default(0) | int + 1 }}"

  - name: Сбросить счётчик
    condition: event.payload.status == "ok"
    action:
      retract_fact:
        key: alert_count
```

#### post_event (каскадирование)

```yaml
rules:
  - name: Первичная обработка
    condition: event.payload.status == "down"
    action:
      post_event:
        payload:
          type: "remediation_needed"
          service: "{{ event.payload.service }}"
          original_event: "{{ event }}"

  - name: Вторичная обработка
    condition: event.type == "remediation_needed"
    action:
      run_playbook:
        name: playbooks/remediate.yml
```

### Блокировки (Locks)

Действия могут поддерживать блокировки, чтобы избежать одновременного запуска противоречивых задач на одном целевом хосте:

```yaml
rules:
  - name: Перезапуск сервиса с блокировкой
    condition: event.payload.status == "down"
    action:
      run_playbook:
        name: playbooks/restart_service.yml
        locks:
          - name: "{{ event.payload.service }}"
            hosts: "{{ event.payload.instance }}"
```

---

## Интеграция с Ansible Automation Platform (AAP) 2.5+

В корпоративной среде EDA используется через **EDA Controller**, который является частью **[Ansible Automation Platform (AAP)](./ansible-automation-platform.md)**:

1.  **Platform Gateway:** Единая точка входа для всех событий. Больше не нужно открывать множество портов для разных вебхуков.
2.  **Event Streams:** Маршрутизация событий внутри платформы. Одно событие может инициировать разные наборы правил.
3.  **[Execution Environments (EE)](./ansible-execution-environments.md):** Rulebook запускаются в изолированных контейнерах, содержащих Java, Python-зависимости и коллекции.
4.  **Vault Integration:** Секреты для доступа к источникам (токены Kafka, пароли) хранятся в защищенном хранилище платформы.
5.  **Decision Environments:** Специализированные EE для EDA, содержащие ansible-rulebook и необходимые зависимости.

### Версионирование AAP и миграция

| AAP версия | Ключевые изменения EDA |
| :--- | :--- |
| AAP 2.5 | Первый релиз EDA Controller, Event Streams, Platform Gateway |
| AAP 2.6 | Миграция плагинов `ansible.eda` → `eda.builtin`, новые builtin-модули, mTLS, event bus (Kafka) |
| AAP 2.7 | Удаление RPM-инсталлятора, PostgreSQL 17, Django 5.2, 12 content collections, de-minimal/de-supported образы |

**Пути обновления:**
- AAP 2.4 → 2.6 → 2.7
- AAP 2.5 → 2.6 → 2.7
- AAP 2.6 → 2.7

Прямое обновление с AAP 2.4 или 2.5 на 2.7 **не поддерживается**.

---

## CLI-справочник ansible-rulebook

### Базовое использование

```bash
# Запуск rulebook с указанием файла
ansible-rulebook -i inventory.yml --rulebook rulebook.yml

# Запуск rulebook из коллекции
ansible-rulebook -i inventory.yml -r namespace.collection.rulebook_name

# Запуск с указанием каталога плагинов
ansible-rulebook -i inventory.yml --rulebook rulebook.yml -S /path/to/plugins/

# Запуск с verbose-выводом (для отладки)
ansible-rulebook -i inventory.yml --rulebook rulebook.yml -vv

# Запуск в режиме проверки (dry-run)
ansible-rulebook -i inventory.yml --rulebook rulebook.yml --check
```

### Основные параметры CLI

| Параметр | Описание |
| :--- | :--- |
| `-i`, `--inventory` | Файл или каталог инвентаря |
| `-r`, `--rulebook` | Путь к rulebook или Fully Qualified Collection Name |
| `-S`, `--source-dir` | Каталог с пользовательскими плагинами-источниками |
| `-e`, `--env-vars` | Файл с переменными окружения |
| `-W`, `--workers` | Количество воркеров для обработки событий |
| `-v`, `--verbose` | Уровень детализации (можно указать несколько раз: `-vv`) |
| `--check` | Режим проверки (dry-run) |
| `--cmdline` | Фильтрация хостов из командной строки |
| `--log-level` | Уровень логирования (DEBUG, INFO, WARNING, ERROR) |

### Переменные окружения

```bash
# Установка переменных для rulebook
export EDA_WEBHOOK_PORT=5001
export EDA_KAFKA_BROKER=localhost:9092

ansible-rulebook -i inventory.yml --rulebook rulebook.yml -e env_vars.yml
```

---

## Практические сценарии

### Сценарий 1: Защита от Brute Force (SSH)

Интеграция с `journald` (community.eda) для блокировки IP после неудачных попыток.

**Rulebook:**
```yaml
---
- name: SSH Brute Force Protection
  hosts: all
  sources:
    - community.eda.journald:
        filters:
          _SYSTEMD_UNIT: sshd.service
  rules:
    - name: Detect multiple failures
      condition: event.message is search("Failed password")
      action:
        run_playbook:
          name: playbooks/block_ip.yml
          extra_vars:
            source_ip: "{{ event.message | regex_search('\\d+\\.\\d+\\.\\d+\\.\\d+') }}"
            log_message: "{{ event.message }}"
```

**Плейбук playbooks/block_ip.yml:**
```yaml
---
- name: Block malicious IP
  hosts: "{{ source_ip }}"
  become: true
  tasks:
    - name: Block IP with nftables
      ansible.builtin.nftables:
        table: inet filter
        chain: input
        rule: "{{ 'ip saddr ' + source_ip + ' drop' }}"
        state: present

    - name: Log blocked IP
      ansible.builtin.lineinfile:
        path: /var/log/blocked_ips.log
        line: "{{ ansible_date_time.iso8601 }} Blocked {{ source_ip }} - {{ log_message }}"
        create: true
```

### Сценарий 2: Очистка диска при заполнении

Реакция на алерт от Alertmanager.

```yaml
---
- name: Disk Cleanup on Alert
  hosts: servers
  sources:
    - ansible.eda.alertmanager:
        host: 0.0.0.0
        port: 8000
  rules:
    - name: Cleanup on DiskFull
      condition: event.alert.labels.alertname == "NodeDiskRunningFull"
      action:
        run_job_template:
          name: "System / Disk Cleanup"
          organization: "Default"
          job_type: "run"

    - name: Critical disk space - immediate cleanup
      condition:
        all:
          - event.alert.labels.alertname == "NodeDiskRunningFull"
          - event.alert.labels.severity == "critical"
      action:
        run_playbook:
          name: playbooks/emergency_disk_cleanup.yml
          extra_vars:
            disk_threshold: 95
```

### Сценарий 3: Автоматический перезапуск при зависании сервиса

Мониторинг HTTP-эндпоинта и перезапуск при timeouts.

```yaml
---
- name: HTTP Health Monitor
  hosts: web_servers
  sources:
    - community.eda.url_check:
        urls:
          - "http://{{ inventory_hostname }}:8080/health"
        poll_interval: 10
        timeout: 5
        force_ssl: false
  rules:
    - name: Service unreachable
      condition:
        all:
          - event.status == "down"
          - event.consecutive_failures >= 3
      action:
        run_playbook:
          name: playbooks/restart_unhealthy_service.yml
          extra_vars:
            service_name: "myapp"
            failure_count: "{{ event.consecutive_failures }}"
```

### Сценарий 4: Реакция на Kafka-события

Обработка сообщений из Kafka с фильтрацией и маршрутизацией.

```yaml
---
- name: Kafka Event Processor
  hosts: all
  sources:
    - ansible.eda.kafka:
        bootstrap_servers: "kafka1:9092,kafka2:9092"
        topic: "infrastructure-events"
        group_id: "eda-processors"
        offset_reset: "earliest"
        security_protocol: "SASL_SSL"
        sasl_mechanism: "PLAIN"
        sasl_username: "{{ vault_kafka_user }}"
        sasl_password: "{{ vault_kafka_password }}"
  filters:
    - eda.builtin.json_filter:
        keys: [event_type, payload, timestamp]
  rules:
    - name: Deployment event
      condition: event.event_type == "deployment_started"
      action:
        run_playbook:
          name: playbooks/handle_deployment.yml

    - name: High CPU alert
      condition:
        all:
          - event.event_type == "metric_alert"
          - event.payload.metric == "cpu_usage"
          - event.payload.value > 90
      action:
        run_job_template:
          name: "Infrastructure / Scale Up"
          organization: "Production"
```

### Сценарий 5: Stateful rulebook — отслеживание состояния

```yaml
---
- name: Stateful Alert Processor
  hosts: all
  sources:
    - eda.builtin.webhook:
        host: 0.0.0.0
        port: 5000
  rules:
    - name: Track critical alerts
      condition: event.payload.severity == "critical"
      action:
        set_fact:
          key: "critical_alerts_{{ event.payload.service }}"
          value: "{{ { 'count': (critical_alerts_{{ event.payload.service }}.count | default(0)) | int + 1, 'last_seen': event.payload.timestamp } }}"

    - name: Escalate after 3 critical alerts
      condition:
        all:
          - event.payload.severity == "critical"
          - critical_alerts_{{ event.payload.service }}.count >= 3
      action:
        run_playbook:
          name: playbooks/escalate_alert.yml
```

---

## Лучшие практики и отладка

### Использование Execution Environments и Decision Environments

Всегда используйте Execution Environments (EE) для обеспечения идентичности среды разработки и эксплуатации. В AAP используйте Decision Environments — специализированные EE для EDA. Собирайте кастомные DE только при необходимости подключения плагинов из `community.eda`, не добавляйте лишние зависимости.

### Идемпотентность и безопасность

EDA запускает действия в ответ на события многократно. Обеспечьте идемпотентность плейбуков и модулей, чтобы повторное срабатывание правила не привело к конфликтующим изменениям. Используйте `no_log` для задач с секретами, храните токены и пароли в Ansible Vault или внешних хранилищах секретов, никогда не фиксируйте их в rulebook.

### Дедупликация и throttling

При использовании `run_job_template` в AAP настраивайте политики перекрытия (concurrency), чтобы не запускать одинаковые задачи слишком часто. В rulebook используйте `throttle` с `accumulate_within` и `threshold` для подавления шумных алертов и предотвратии avalanche-эффекта при массовых сбоях.

### Память и Drools

Движок правил на базе Java может потреблять значительный объём RAM при большом количестве фактов. Рекомендации:

- Очищайте неиспользуемые факты через `retract_fact`.
- Ограничивайте количество активных правил.
- Мониторьте потребление памяти java-процесса.
- Используйте `eda.builtin.json_filter` для сокращения объёма передаваемых данных.

### Наблюдаемость для SRE

Для SRE критически важно, чтобы EDA не стала «чёрным ящиком». Настройте следующие метрики и алерты:

- Количество обработанных событий в минуту.
- Количество ошибок при выполнении действий.
- Время выполнения плейбука/модуля с момента события до завершения.
- Потребление RAM и CPU процессом `ansible-rulebook` / `java`.
- Размер очереди необработанных событий.

Добавьте в действия `debug` или `run_module` с `ansible.builtin.assert` для проверки входных данных перед выполнением дорогих операций.

### Отладка фильтров

Используйте действие `debug` после применения фильтров, чтобы убедиться в правильности трансформации JSON-структуры:

```yaml
rules:
  - name: Debug after filter
    condition: event is defined
    action:
      debug:
        msg: "Структура события после фильтрации: {{ event }}"
```

### Логирование

```bash
# Детальный вывод (все уровни)
ansible-rulebook -i inventory.yml --rulebook rulebook.yml -vv

# Только ошибки
ansible-rulebook -i inventory.yml --rulebook rulebook.yml --log-level ERROR

# Логирование в файл
ansible-rulebook -i inventory.yml --rulebook rulebook.yml --log-file /var/log/eda.log
```

---

## Типовые ошибки и их решение (Troubleshooting)

| Проблема | Вероятная причина | Решение |
| :--- | :--- | :--- |
| `ModuleNotFoundError: No module named 'ansible.eda'` | Коллекция ansible.eda не установлена | `ansible-galaxy collection install ansible.eda` |
| `SourcePluginFeedbackMisconfiguredException` | Обратная связь включена без персистентности | Включите персистентность в EDA Server или отключите `feedback: true` |
| Rulebook не реагирует на события | Неверный порт или адрес | Проверьте настройки `host`/`port` в источнике |
| `Connection refused` к Kafka | Неверные параметры подключения | Проверьте `bootstrap_servers`, топик, аутентификацию |
| Высокое потребление RAM | Большое количество фактов в Drools | Оптимизируйте правила, используйте `retract_fact` |
| Событие не срабатывает | Неверный синтаксис условия | Используйте `debug` для просмотра структуры события |
| `TimeoutError` при запуске playbook | Плейбук выполняется дольше таймаута | Увеличьте `json_timeout` или оптимизируйте плейбук |
| Плагин из `community.eda` не найден | DE не содержит community.eda | Создайте кастомный DE с зависимостями community.eda |
| Повторное срабатывание правила при массовых алертах | Отсутствует throttling | Добавьте `throttle` с `accumulate_within` и `threshold` |
| Секреты в логах ansible-rulebook | Отсутствует `no_log` или Vault | Установите `no_log: true`, перенесите секреты в Vault |
| Дерегуляция событий при рестарте rulebook | Отсутствует персистентность | Включите persistence в ansible-rulebook или EDA Controller |
| Несовместимость пространств имён | Устаревшие имена плагинов | Обновите `ansible.eda.*` на `eda.builtin.*` |
| Ошибки аутентификации в AAP при `run_job_template` | Неверный токен или учётные данные | Проверьте RBAC и OAuth токен в AAP Gateway |
| Падение rulebook с `OutOfMemoryError` | Слишком большой объём фактов в Drools | Уменьшите количество правил, добавьте `retract_fact`, увеличьте лимит памяти JVM |

### Диагностические команды

```bash
# Проверить установленные коллекции
ansible-galaxy collection list

# Проверить версию ansible-rulebook
ansible-rulebook --version

# Проверить доступные плагины
ansible-doc -l -t event_source

# Тест rulebook в dry-run режиме
ansible-rulebook -i inventory.yml --rulebook rulebook.yml --check

# Проверка Python-зависимостей
pip list | grep -i ansible
pip list | grep -i aiohttp
pip list | grep -i aiokafka
```

---

## Безопасность

### Общие рекомендации

- **Секреты:** Никогда не храните пароли, токены или ключи API в rulebook. Используйте Ansible Vault или интеграцию с AAP Vault.
- **HMAC-подпись:** При использовании webhook-источников настраивайте проверку подписи (HMAC) для верификации источника событий.
- **Шифрование:** Для Kafka и PostgreSQL используйте SSL/TLS шифрование подключения.
- **RBAC:** В AAP EDA Controller используйте Role-Based Access Control для ограничения доступа к rulebook и их действиям.
- **Сетевая изоляция:** Ограничьте доступ к портам webhook/источников только доверенными системами.
- **Аудит:** В AAP все запуски rulebook логируются и доступны для аудита.

### Для DevOps/SRE/Sysadmin

- **Управление активациями:** Храните rulebook в Git и разворачивайте через AAP проекты, чтобы иметь историю изменений и возможность rollback.
- **Мониторинг самого EDA:** Добавьте в систему мониторинга алерты на недоступность источников событий, высокую задержку обработки и ошибки выполнения действий. EDA не должна быть точкой молчания.
- **Средний czas reakcji (MTTR):** EDA снижает MTTR за счёт реактивного реагирования, но требует тщательного тестирования правил в staging-среде перед production.
- **Факторы отказов:** Исключите из rulebook действия, которые могут вызвать каскадный отказ (например, массовый перезапуск всех сервисов одновременно). Используйте `locks` и ограничивайте `max_concurrent` в AAP.
- **Хранение персистентности:** При использовании `feedback: true` или event persistence убедитесь, что хранилище событий защищено от потери данных и имеет резервное копирование.

---

## Дополнительная информация

### Смотрите также

- **[Ansible Automation Platform (AAP)](./ansible-automation-platform.md)** — управление заданиями, workflow и RBAC в корпоративной среде.
- **[Основные концепции Ansible](./ansible_core_concepts.md)** — база для понимания плейбуков.
- **[Событийно-ориентированная архитектура](../Concepts/event-driven-architecture.md)** — теоретическая основа EDA (хореография, event sourcing, Sagas).

### Дополнительные практические сценарии

#### Сценарий 5: Реакция на изменения конфигурации

Используется `community.eda.file_watch` для отслеживания изменений файлов конфигурации и автоматического перезапуска сервисов. Для работы требуется Decision Environment с `community.eda`.

```yaml
---
- name: Configuration Change Monitor
  hosts: config_servers
  sources:
    - community.eda.file_watch:
        path: /etc/nginx/conf.d/
        recursive: true
  rules:
    - name: Detect nginx config change
      condition: event.type == "modified" and event.path is search("\\.conf$")
      action:
        run_playbook:
          name: playbooks/reload_nginx.yml
          extra_vars:
            changed_file: "{{ event.path }}"
            checksum: "{{ event.checksum }}"
```

#### Сценарий 6: Очистка временных файлов при заполнении

Реакция на заполнение раздела `/tmp` или `/var/tmp` через webhook с метриками от node_exporter.

```yaml
---
- name: Temporary Files Cleanup
  hosts: storage_servers
  sources:
    - eda.builtin.webhook:
        host: 0.0.0.0
        port: 9091
        # node_exporter или кастомный скрипт отправляют метрики при превышении порога
  rules:
    - name: tmp directory full
      condition: event.payload.node_filesystem_avail_bytes{mountpoint="/tmp"} < 1073741824
      action:
        run_playbook:
          name: playbooks/cleanup_tmp.yml
          extra_vars:
            filesystem: "/tmp"
            threshold_bytes: 1073741824
```

#### Сценарий 7: Отслеживание сбоев systemd-сервисов

Реакция на падение или зависание сервисов через системный журнал.

```yaml
---
- name: Systemd Service Failure Monitor
  hosts: all
  sources:
    - community.eda.journald:
        filters:
          _SYSTEMD_UNIT: sshd.service
          PRIORITY: "err"
  rules:
    - name: SSH service failed
      condition: event.message is search("Failed")
      action:
        run_playbook:
          name: playbooks/restart_sshd.yml
          extra_vars:
            host: "{{ inventory_hostname }}"
```

#### Сценарий 8: Stateful-мониторинг последовательных сбоев

Отслеживание количества последовательных сбоев и эскалация при превышении порога.

```yaml
---
- name: Consecutive Failure Tracker
  hosts: web_servers
  sources:
    - community.eda.url_check:
        urls:
          - "http://{{ inventory_hostname }}:8080/health"
        poll_interval: 15
        timeout: 5
  rules:
    - name: Track consecutive failures
      condition: event.status == "down"
      action:
        set_fact:
          key: "health_failures_{{ inventory_hostname }}"
          value: "{{ (health_failures_{{ inventory_hostname }} | default(0)) | int + 1 }}"

    - name: Escalate after 5 failures
      condition:
        all:
          - event.status == "down"
          - health_failures_{{ inventory_hostname }} >= 5
      action:
        run_playbook:
          name: playbooks/escalate_unhealthy_service.yml
          extra_vars:
            service_name: "myapp"
            failure_count: "{{ health_failures_{{ inventory_hostname }} }}"

    - name: Reset counter on recovery
      condition: event.status == "up"
      action:
        retract_fact:
          key: "health_failures_{{ inventory_hostname }}"
```

---
