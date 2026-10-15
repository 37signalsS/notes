# Ansible: продвинутые возможности плейбуков

## Определения

**Статическое включение (`import_tasks`, `import_role`, `import_playbook`)** — механизм, при котором содержимое внешнего файла или роли вставляется в плейбук на этапе предварительного анализа (парсинга). Это работает как прямая вставка кода до начала выполнения.

**Динамическое включение (`include_tasks`, `include_role`, `include_playbook`)** — механизм подключения задач или ролей непосредственно в процессе выполнения плейбука. Позволяет использовать переменные, факты и результаты предыдущих задач для определения логики на лету.

**Делегирование (`delegate_to`)** — перенос выполнения задачи с целевого хоста на другой узел (например, выполнение API-запроса с контрольного узла или обновление DNS-записи с балансировщика).

**Группировка задач (`block`)** — логическое объединение набора задач для совместной обработки ошибок (`rescue`, `always`) или применения общих директив (`when`, `become`).

**Асинхронное выполнение (`async`)** — запуск задачи в фоновом режиме без блокировки основного потока выполнения. Критично для длительных операций, превышающих таймауты SSH-сессий.

**Lookup-плагины** — инструменты для получения данных из внешних источников (файлы, переменные окружения, базы данных) на стороне контрольного узла во время выполнения.

**Фильтры (Filters)** — функции Jinja2 для преобразования данных (форматирование, парсинг, математические операции) непосредственно внутри плейбуков и шаблонов.

**`listen`** — альтернативное имя для обработчика (`handler`), позволяющее нескольким задачам уведомлять один и тот же обработчик по разным именам.

**`vars_prompt`** — механизм интерактивного запроса переменных у пользователя во время выполнения плейбука через CLI.

**`check_mode`** — режим проверки (`--check`), в котором Ansible прогнозирует изменения без их фактического применения. Не все модули поддерживают этот режим.

**`force_handlers`** — параметр плейбука, принудительно выполняющий обработчики даже при наличии ошибок в задачах. Критично для критичных сервисов (базы данных, балансировщики).

**Callback-плагины** — модули расширения, перехватывающие события выполнения Ansible (start, ok, failed, skipped) для отправки в SIEM, логирование или метрики.

## Базовые концепции

### Включения: Import vs Include

| Характеристика | `import_*` (Статика) | `include_*` (Динамика) |
| :--- | :--- | :--- |
| **Время считывания** | При запуске (Parsing time) | При выполнении (Execution time) |
| **Использование переменных** | Только из `vars`, `vars_files` | Любые, включая факты и `register` |
| **Циклы (`loop`)** | Запрещены | Разрешены |
| **Обработка условий (`when`)** | Применяется к каждой задаче внутри | Применяется к самому включению |
| **Параметр `apply`** | Не поддерживается | Позволяет применять атрибуты к вложенным задачам |
| **Видимость тегов** | Наследуются всеми вложенными задачами | Теги на `include` не видны вложенным задачам |
| **Обработка ошибок** | Ошибка в любой задаче останавливает парсинг | Ошибка обрабатывается в контексте текущего play |
| **Переменные в имени файла** | Запрещены (только строковые литералы) | Разрешены (динамический выбор файла) |

**Примеры использования `apply` в `include_role`:**

Параметр `apply` позволяет применить атрибуты (`become`, `tags`, `ignore_errors`, `delegate_to`) ко всем задачам внутри подключаемой роли без явного указания в каждой задаче:

```yaml
- name: Подключить роль с правами root
  ansible.builtin.include_role:
    name: web_server
    apply:
      become: true
      tags: [nginx, config]
      ignore_errors: true
      environment:
        http_proxy: "http://proxy.example.com:3128"
```

**Пример ошибки при использовании `import_tasks` с переменными:**

```yaml
# ОШИБКА: нельзя использовать переменные в import_tasks
- ansible.builtin.import_tasks: "{{ ansible_facts['os_family'] }}_tasks.yml"
# → Fatal error: 'import_tasks' does not accept a dynamic filename

# ПРАВИЛЬНО: использовать include_tasks для динамического выбора
- ansible.builtin.include_tasks: "{{ ansible_facts['os_family'] }}_tasks.yml"
```

**Видимость тегов при включении:**

```yaml
# import_tasks: теги наследуются всеми задачами внутри
- ansible.builtin.import_tasks: install.yml
  tags: [install]  # Все задачи в install.yml получат тег "install"

# include_tasks: тег apply не виден вложенным задачам
- ansible.builtin.include_tasks: configure.yml
  tags: [configure]  # Только сам include получает тег, задачи внутри - нет
```

> **Рекомендация:** Используйте `import_*` для фиксированной структуры и `include_*` для гибкой логики (например, выбор задач по результатам сбора фактов). Подробнее в разделе **[Создание и использование ролей](../Roles/usage.md)**. Для сравнения `import_role`/`include_role` см. **[Роли Ansible](../ansible_roles.md)**.

**`include_playbook`** — динамическое включение целого плейбука во время выполнения. В отличие от `import_playbook`, позволяет использовать переменные и факты для выбора плейбука:

```yaml
- name: Подключить окружение-зависимый плейбук
  ansible.builtin.include_playbook: "{{ env_type }}_deploy.yml"
```

`include_playbook` наследует контекст текущего плейбука, но задачи внутри него выполняются как отдельный play.

### Асинхронность и поллинг (Async / Poll)

Применяется для задач, занимающих более 10–15 минут (миграции БД, сборка тяжелого ПО, обновления пакетов на множестве серверов).
*   **`async`**: Максимальное время выполнения (в секундах). Если задача не завершится за этот срок, она будет принудительно остановлена. Значение `0` отключает таймаут.
*   **`poll`**: Частота опроса статуса задачи.
    *   `poll: 0`: Режим «запустил и забыл» (fire-and-forget). Ansible не ждет завершения и переходит к следующему шагу.
    *   `poll: >0`: Ansible блокирует выполнение и опрашивает статус с указанным интервалом (в секундах).

Для контроля фоновых задач используется модуль `ansible.builtin.async_status`. Основы синхронного выполнения описаны в **[Основы структуры плейбуков](basics.md)**.

**Паттерн 1: Фоновая задача с ожиданием завершения:**

```yaml
- name: Запуск длительной операции в фоне
  ansible.builtin.command: /usr/local/bin/heavy_task.sh
  async: 3600  # Максимум 1 час
  poll: 0      # Не ждать, сразу перейти дальше
  register: async_job

- name: Выполнение других независимых задач
  ansible.builtin.debug:
    msg: "Пока выполняется тяжелая задача..."

- name: Ожидание завершения фоновой задачи
  ansible.builtin.async_status:
    jid: "{{ async_job.ansible_job_id }}"
  register: job_result
  until: job_result.finished
  retries: 30    # Максимум 30 попыток
  delay: 10      # Интервал проверки 10 секунд
```

**Паттерн 2: Несколько параллельных фоновых задач:**

```yaml
- name: Запуск нескольких длительных операций
  ansible.builtin.command: "{{ item }}"
  async: 7200
  poll: 0
  register: parallel_jobs
  loop:
    - /usr/local/bin/migration_step1.sh
    - /usr/local/bin/migration_step2.sh

- name: Ожидание завершения всех задач
  ansible.builtin.async_status:
    jid: "{{ item.ansible_job_id }}"
  register: job_results
  until: job_results.finished
  retries: 60
  delay: 30
  loop: "{{ parallel_jobs.results }}"
```

**Паттерн 3: Обработка ошибок фоновой задачи:**

```yaml
- name: Запуск операции с возможным сбоем
  ansible.builtin.command: /usr/local/bin/risky_update.sh
  async: 1800
  poll: 0
  register: risky_job

- name: Ожидание завершения
  ansible.builtin.async_status:
    jid: "{{ risky_job.ansible_job_id }}"
  register: job_status
  until: job_status.finished
  retries: 30
  delay: 10

- name: Проверка результата и обработка ошибки
  ansible.builtin.fail:
    msg: "Фоновая задача завершилась с ошибкой: {{ job_status.stderr }}"
  when: job_status.rc != 0
```

**Типичные ошибки:**

*   Задача с `async` и `poll: >0` (по умолчанию `poll: 10`) будет блокировать выполнение до завершения или таймаута. Для фоновых задач всегда используйте `poll: 0`.
*   Если `async` не задан, задача выполняется синхронно без возможности фонового выполнения.
*   При перезапуске Ansible Control Node фоновые задачи теряются. Используйте `ansible.builtin.set_fact` с persistent storage для критичных операций.

### Делегирование и управление контекстом

*   **`delegate_to`**: Указывает хост, на котором будет выполнен модуль. Чаще всего используется `localhost` для задач на контрольном узле или специфичных серверов (DNS, API, мониторинг).
*   **`local_action`**: Устаревшая сокращенная форма для `delegate_to: localhost`. Рекомендуется использовать полную форму.
*   **`delegate_facts`**: Если `true`, факты, собранные в делегированной задаче (модуль `setup`), будут привязаны к хосту, на который делегировали, а не к текущему. По умолчанию `false`.
*   **`run_once`**: Гарантирует выполнение задачи только один раз на первом доступном хосте в группе. Идеально для миграций БД или однократного скачивания артефактов. Результат доступен через `hostvars[inventory_hostname]` для остальных хостов.
*   **`throttle`**: Лимит конкурентности на уровне конкретной задачи или блока. В отличие от `serial`, позволяет ограничивать нагрузку на внешние ресурсы (API, БД) без изменения общей стратегии плея.

**Важные ограничения делегирования:**

1.  `delegate_to` не изменяет целевой хост для модулей `setup` и `gather_facts` по умолчанию. Используйте `delegate_facts: true` для привязки фактов к делегированному хосту.
2.  При делегировании на `localhost` модули выполняются на контрольном узле, но переменные берутся из контекста текущего хоста (не целевого).
3.  `delegate_to` работает на уровне задачи, а не плея. Для делегирования всех задач используйте `hosts: localhost` или специальный play.

**Пример делегирования с привязкой фактов:**

```yaml
# Сбор фактов с целевого хоста и делегирование на другой сервер
- name: Собрать факты целевого хоста
  ansible.builtin.setup:
  delegate_facts: true
  delegate_to: "{{ groups['monitoring'][0] }}"

# Теперь факты доступны на мониторинговом сервере для этого хоста
- name: Зарегистрировать хост в мониторинге
  ansible.builtin.uri:
    url: "https://monitoring.example.com/api/hosts"
    method: POST
    body_format: json
    body:
      name: "{{ inventory_hostname }}"
      ip: "{{ ansible_default_ipv4.address }}"
  delegate_to: "{{ groups['monitoring'][0] }}"
```

**Типичные сценарии делегирования:**

*   **DNS-обновление:** `delegate_to` на DNS-сервер для обновления записей после изменения IP.
*   **Балансировщик:** `delegate_to` на HAProxy/Nginx для переконфигурации upstream.
*   **API-вызовы:** `delegate_to: localhost` для запросов к внешним API без установки инструментов на целевые серверы.
*   **Локальное скачивание:** `delegate_to: localhost` + `run_once: true` для скачивания артефактов один раз на контрольный узел.

### Управление состоянием задачи (Custom Conditions)

*   **`changed_when`**: Позволяет вручную определить, когда задача считается изменившей систему. Важно для модулей `command` и `shell`, которые по умолчанию всегда возвращают статус `changed`.
*   **`failed_when`**: Переопределяет условия ошибки. Позволяет игнорировать специфические коды возврата или искать ошибки в строках вывода (`stdout`).

Детальные паттерны использования `changed_when`/`failed_when` для идемпотентности и отладки приведены в **[Управление ходом выполнения](flow_control.md)**.

### Блоки и обработка исключений

Конструкция `block` реализует логику `try-catch-finally`:
*   **`block`**: Основной набор задач. Если хотя одна завершается с ошибкой, управление переходит в `rescue`.
*   **`rescue`**: Задачи, выполняемые только при сбое в основном блоке. Позволяют реализовать откат (Rollback).
*   **`always`**: Задачи, выполняемые независимо от успеха или сбоя (например, удаление временных файлов).

**Вложенные блоки:**

Блоки могут быть вложенными друг в друга. При ошибке во внутреннем блоке управление переходит в `rescue` этого блока. Если `rescue` тоже завершается ошибкой, управление переходит в `rescue` внешнего блока:

```yaml
- name: Внешний блок
  block:
    - name: Шаг 1
      ansible.builtin.command: step1.sh

    - name: Внутренний блок
      block:
        - name: Шаг 2a
          ansible.builtin.command: step2a.sh
        - name: Шаг 2b
          ansible.builtin.command: step2b.sh
      rescue:
        - name: Восстановление после ошибки внутреннего блока
          ansible.builtin.command: recover_internal.sh
  rescue:
    - name: Восстановление после ошибки внешнего блока
      ansible.builtin.command: recover_external.sh
  always:
    - name: Очистка
      ansible.builtin.file: path=/tmp/work state=absent
```

**Поведение `always` при ошибке в `rescue`:**

Если задача в `rescue` также завершается ошибкой, `always` все равно выполняется. Это обеспечивает гарантированную очистку ресурсов даже в случае каскадных сбоев:

```yaml
block:
  - ansible.builtin.command: risky_operation.sh
rescue:
  - ansible.builtin.command: might_also_fail.sh  # Ошибка здесь
always:
  - ansible.builtin.file:  # Выполнится ВСЕГДА
      path: /tmp/lock
      state: absent
```

**Использование `rescue` для отката изменений:**

```yaml
- name: Применение и откат конфигурации
  block:
    - name: Копирование нового конфига
      ansible.builtin.copy:
        src: nginx.conf.new
        dest: /etc/nginx/nginx.conf
      notify: Рестарт Nginx

    - name: Валидация конфигурации
      ansible.builtin.command: nginx -t
      changed_when: false
  rescue:
    - name: Восстановление старого конфига
      ansible.builtin.copy:
        src: nginx.conf.backup
        dest: /etc/nginx/nginx.conf

    - name: Рестарт с восстановленным конфигом
      ansible.builtin.systemd:
        name: nginx
        state: restarted
  always:
    - name: Удаление временного конфига
      ansible.builtin.file:
        path: /tmp/nginx.conf.new
        state: absent
```

### Стратегии выполнения (Strategy Plugins)

Стратегия определяет, как хосты проходят по задачам плейбука. Встроенные стратегии: `linear` (по умолчанию), `free`, `host_pinned`.

**Linear (по умолчанию):** Ansible ждет завершения текущей задачи на всех хостах перед переходом к следующей. Гарантирует предсказуемость, но снижает скорость при разнородных задачах.

**Free:** Каждый хост проходит по задачам плейбука с максимально возможной скоростью, не дожидаясь остальных. Подходит для независимых хостов. При использовании `serial` хосты обрабатываются пачками, но внутри пачки двигаются независимо.

**Host Pinned:** Хост остается в своем слоте (fork) до завершения всего плейбука. Оптимизирует использование SSH-соединений для длительных плейбуков, но снижает общую пропускную способность.

**Когда использовать:**

| Сценарий | Рекомендуемая стратегия | Обоснование |
| :--- | :--- | :--- |
| Rolling update с проверкой здоровья | `linear` + `serial` | Гарантирует последовательность и контроль на каждом этапе |
| Массовый деплой (независимые хосты) | `free` | Максимальная скорость, хосты не блокируют друг друга |
| Миграция БД на кластере | `serial` + `linear` | Последовательное обновление с возможностью отката |
| Разнородные задачи (длинные + короткие) | `free` | Короткие задачи не ждут длинные |
| Ограниченные ресурсы API | `serial` + `throttle` | Контроль нагрузки на внешние системы |

**Пример free стратегии с serial:**

```yaml
---
- name: Free стратегия с serial
  hosts: webservers
  strategy: free
  serial: 10  # 10 хостов за раз
  tasks:
    - name: Долгая операция
      ansible.builtin.command: /opt/scripts/long_task.sh
    - name: Быстрая операция
      ansible.builtin.ping:
# Хосты движутся с разной скоростью в пределах каждой пачки
```

**Пример host_pinned стратегии:**

```yaml
---
- name: Host Pinned стратегия
  hosts: database_servers
  strategy: host_pinned
  serial: 5  # Максимум 5 хостов одновременно
  tasks:
    - name: Миграция БД (занимает всё время хоста)
      ansible.builtin.command: /opt/scripts/db_migrate.sh
    - name: Проверка миграции
      ansible.builtin.command: /opt/scripts/verify_migration.sh
# Каждый хост занимает слот на всё время выполнения всех задач
```

**Интеграция с throttle:**

```yaml
---
- name: Linear + serial: предсказуемое поэтапное выполнение
  hosts: all
  strategy: linear
  serial: "25%"
  tasks:
    - name: Обновление
      ansible.builtin.apt:
        name: "*"
        state: latest
      throttle: 10  # Ограничение на уровне задачи

---
# Free + serial: быстрое выполнение с контролем пачек
- name: Fast Parallel Execution
  hosts: all
  strategy: free
  serial: 20
  tasks:
    - name: Параллельная операция
      ansible.builtin.command: /opt/fast_task.sh
```

Детальный разбор стратегий, их влияния на производительность и выбор параметров `forks`/`serial` приведен в **[Оптимизация производительности](../ansible_performance_tuning.md)**.

**Важные нюансы throttle:**
*   `throttle` применяется **после** определения strategy.
*   При `serial` + `throttle` — `throttle` может уменьшить фактическую параллельность внутри пачки.
*   `throttle` на уровне блока (`block: throttle: 3`) применяется ко всем задачам внутри блока.

**Custom strategy plugins:**

Кастомные стратегии создаются для специфических сценариев, не покрытых встроенными стратегиями (например, round-robin, интеграция с внешними планировщиками).

```python
# strategy_plugins/my_strategy.py
from ansible.plugins.strategy.linear import StrategyModule

class StrategyModule(StrategyModule):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "my_strategy"

    def run(self, iterator, play_context):
        # Кастомная логика распределения задач
        pass
```

Активация в `ansible.cfg`:
```ini
[defaults]
strategy_plugins = ./strategy_plugins
```

### Инструменты валидации и отладки

*   **`ansible.builtin.assert`**: Прекращает выполнение, если условие не выполняется ("fail-fast" проверки). Полезен для валидации переменных и условий перед критичными операциями.
*   **`ansible.builtin.debug`**: Вывод переменных или сообщений. Основной инструмент отладки плейбуков.
*   **`debugger`**: Интерактивная консоль при сбоях. Позволяет исследовать переменные и состояние в момент ошибки.

**Режимы работы `debugger`:**

| Режим | Описание |
| :--- | :--- |
| `on_failed` | Запуск отладчика при ошибке задачи (по умолчанию) |
| `on_unreachable` | Запуск при недостижимости хоста |
| `on_skipped` | Запуск при пропуске задачи |
| `always` | Запуск перед каждой задачей |
| `never` | Отладчик отключен |

**Команды интерактивного отладчика:**

| Команда | Описание |
| :--- | :--- |
| `p task` | Показать информацию о текущей задаче |
| `p task.args` | Показать аргументы задачи |
| `p host` | Показать текущий хост |
| `p vars` | Показать все переменные |
| `p result` | Показать результат выполнения |
| `c` | Продолжить выполнение |
| `q` | Выйти из отладчика |
| `continue` | Продолжить до следующей ошибки |

**Пример использования debugger:**

```yaml
- name: Задача, склонная к ошибкам
  ansible.builtin.command: /usr/local/bin/risky_script.sh
  register: result
  debugger: on_failed

- name: Вывод отладочной информации
  ansible.builtin.debug:
    var: result
```

При ошибке Ansible остановится и предоставит интерактивную консоль, где можно исследовать переменные и понять причину сбоя.

## Практические сценарии

### Сценарий 1: Динамическое подключение ролей и задач по ОС

Использование `include_tasks` для кроссплатформенных сценариев. Для детального разбора кроссплатформенного проектирования см. **[Кроссплатформенные концепции Ansible](../CrossPlatform/concepts.md)**.

```yaml
- name: Подключить задачи для текущего семейства ОС
  ansible.builtin.include_tasks: "{{ ansible_facts['os_family'] | lower }}_tasks.yml"
```

### Сценарий 2: Оркестрация и делегирование (Скачивание артефакта)

Скачивание архива один раз на контрольный узел и последующее распространение.

```yaml
- name: Скачать дистрибутив на контрольный узел
  ansible.builtin.get_url:
    url: "https://artifactory.example.com/app.tar.gz"
    dest: "/tmp/app.tar.gz"
  delegate_to: localhost
  run_once: true

- name: Распаковать на целевых серверах
  ansible.builtin.unarchive:
    src: "/tmp/app.tar.gz"
    dest: "/opt/app"
    remote_src: false # Файл берется с контрольного узла
```

### Сценарий 3: Атомарная миграция и обработка ошибок (Block/Rescue)

Использование `run_once` и логики восстановления состояния.

```yaml
- name: Миграция БД с откатом
  block:
    - name: Создать бэкап перед миграцией
      ansible.builtin.command: /usr/bin/db_backup
      run_once: true
      register: db_backup

    - name: Выполнить миграцию
      ansible.builtin.command: /usr/bin/db_migrate
      run_once: true

  rescue:
    - name: Откат БД из бэкапа
      ansible.builtin.command: "/usr/bin/db_restore --file {{ db_backup.stdout }}"
      run_once: true
```

### Сценарий 4: Ограничение нагрузки на API через throttle

```yaml
- name: Регистрация узлов во внешнем реестре
  ansible.builtin.uri:
    url: https://registry.example.com/api/nodes
    method: POST
    body_format: json
    body: { name: "{{ inventory_hostname }}" }
  throttle: 5 # Не более 5 одновременных запросов
```

### Сценарий 5: Сбор фактов и fail-fast проверка (Assert)

Использование встроенных модулей валидации состояния системы.

```yaml
- name: Собрать информацию о пакетах и сервисах
  ansible.builtin.package_facts:
  ansible.builtin.service_facts:

- name: Валидация состояния
  ansible.builtin.assert:
    that:
      - "'nginx' in ansible_facts.packages"
      - ansible_facts.services['nginx.service'].state == 'running'
    fail_msg: "Nginx не установлен или не запущен"
```

### Сценарий 6: Точки останова и отладка (Debugger)

Использование интерактивного отладчика для анализа переменных в момент сбоя.

```yaml
- name: Задача, склонная к ошибкам
  ansible.builtin.command: /usr/local/bin/risky_script.sh
  debugger: on_failed

- name: Вывод отладочной информации
  ansible.builtin.debug:
    var: result_of_command
```

### Сценарий 6a: Общие обработчики через `listen`

Использование `listen` для создания общих обработчиков, вызываемых из нескольких ролей или задач по разным именам.

```yaml
handlers:
  - name: Перезапустить все сервисы
    ansible.builtin.systemd:
      state: restarted
      daemon_reload: yes
    listen: "reload application"

tasks:
  - name: Обновить конфиг Nginx
    ansible.builtin.template:
      src: nginx.conf.j2
      dest: /etc/nginx/nginx.conf
    notify: Перезапустить все сервисы

  - name: Обновить конфиг App
    ansible.builtin.template:
      src: app.conf.j2
      dest: /etc/app/app.conf
    notify: reload application  # Вызывает тот же обработчик
```

### Сценарий 7: Асинхронное обновление с ожиданием завершения

Запуск тяжелой операции и проверка её статуса через некоторое время.

```yaml
- name: Запуск длительной операции в фоне
  ansible.builtin.command: /usr/local/bin/heavy_task.sh
  async: 3600
  poll: 0
  register: async_job

- name: Выполнение других независимых задач
  ansible.builtin.debug:
    msg: "Делаем что-то еще, пока идет тяжелая задача..."

- name: Ожидание завершения фоновой задачи
  ansible.builtin.async_status:
    jid: "{{ async_job.ansible_job_id }}"
  register: job_result
  until: job_result.finished
  retries: 30
  delay: 10
```

### Сценарий 8: Делегирование фактов при регистрации в Zabbix

Сбор данных о хосте и их использование при делегировании на сервер мониторинга.

```yaml
- name: Собрать локальные факты хоста
  ansible.builtin.setup:

- name: Регистрация в Zabbix через API сервера
  ansible.builtin.uri:
    url: "https://zabbix.example.com/api_jsonrpc.php"
    method: POST
    body: 
      host: "{{ ansible_hostname }}"
      ip: "{{ ansible_default_ipv4.address }}"
  delegate_to: zabbix_server
  delegate_facts: true
```

### Сценарий 9: Кастомная логика успешности и изменений

Обработка вывода скриптов, которые не возвращают стандартные коды или статусы.

```yaml
- name: Выполнение самописного скрипта проверки
  ansible.builtin.command: /usr/local/bin/check_app_health.sh
  register: health_result
  # Ошибка, только если в выводе есть слово ERROR
  failed_when: "'ERROR' in health_result.stdout"
  # Статус changed, только если скрипт вывел слово UPDATED
  changed_when: "'UPDATED' in health_result.stdout"
```

### Сценарий 10: Формирование конфига через Filters и Lookups

Использование Jinja2-фильтров и внешних данных для генерации динамической конфигурации.

```yaml
- name: Генерация конфига из шаблона с обработкой данных
  ansible.builtin.template:
    src: app_config.json.j2
    dest: /etc/app/config.json
  vars:
    # Получение секрета из переменной окружения
    db_pass: "{{ lookup('env', 'APP_DB_PASS') | default('admin', true) }}"
    # Преобразование списка хостов в JSON-массив
    backend_nodes: "{{ groups['web_servers'] | map('extract', hostvars, ['ansible_host']) | list | to_json }}"
```

**Фильтр `map('extract', ...)` — извлечение вложенных полей:**

```yaml
# Получение IP-адресов всех веб-серверов
- name: Список IP веб-серверов
  ansible.builtin.debug:
    msg: "{{ groups['web_servers'] | map('extract', hostvars, ['ansible_default_ipv4', 'address']) | list }}"

# Фильтрация серверов по тегу и извлечение имен
- name: Имена серверов с ролью database
  ansible.builtin.debug:
    msg: "{{ groups['all'] | map('extract', hostvars) | selectattr('roles', 'intersect', ['database']) | map(attribute='inventory_hostname') | list }}"
```

**Фильтр `selectattr` / `rejectattr` — фильтрация списков словарей:**

```yaml
# Выбор работающих сервисов
- name: Запущенные сервисы
  ansible.builtin.debug:
    var: ansible_facts.services | selectattr('state', 'equalto', 'running') | list

# Фильтрация хостов по значению переменной
- name: Серверы с высокой нагрузкой
  ansible.builtin.debug:
    msg: "{{ groups['all'] | map('extract', hostvars) | selectattr('cpu_load', 'gt', 8) | map(attribute='inventory_hostname') | list }}"
```

**Lookup `first_found` — выбор файла на основе приоритета:**

```yaml
- name: Загрузка переменных для текущей ОС
  ansible.builtin.include_vars:
    "{{ lookup('first_found', params) }}"
  vars:
    params:
      files:
        - "{{ ansible_facts['os_family'] | lower }}_vars.yml"
        - "default_vars.yml"
      paths:
        - "vars"
        - "defaults"

- name: Задачи для текущей ОС
  ansible.builtin.include_tasks:
    "{{ lookup('first_found', task_params) }}"
  vars:
    task_params:
      files:
        - "{{ ansible_facts['os_family'] | lower }}_tasks.yml"
        - "default_tasks.yml"
      paths:
        - "tasks"
```

**Lookup `dict` — создание словаря из списков:**

```yaml
# Объединение двух списков в словарь
- name: Создание карты портов
  ansible.builtin.debug:
    msg: "{{ dict(['http', 'https', 'ssh'] | zip([80, 443, 22])) }}"
    # Результат: {"http": 80, "https": 443, "ssh": 22}
```

**Фильтр `json_query` (требуется библиотека `jmespath`):**

```yaml
# Извлечение данных из сложной структуры API
- name: Получение списка работающих инстансов
  ansible.builtin.debug:
    var: api_response | json_query("instances[?status=='running'].ip_address")

# Группировка данных
- name: Уникальные значения из массива
  ansible.builtin.debug:
    var: api_response | json_query("users[*].groups[]") | unique
```

> **Примечание:** Для работы `json_query` установите библиотеку `jmespath` на контрольном узле: `pip3 install jmespath`. Подробнее в разделе [Шаблонизация Jinja2](../ansible_jinja_templating.md).

### Сценарий 11: Интерактивный ввод переменных (vars_prompt)

Запрос credentials или параметров у оператора во время выполнения. Подходит для одноразовых операций, не для automation-пайплайнов.

```yaml
- name: Деплой с подтверждением оператора
  hosts: app_servers
  vars_prompt:
    - name: deploy_version
      prompt: "Введите версию для деплоя"
      private: no
    - name: db_password
      prompt: "Пароль базы данных"
      private: yes
      encrypt: "sha512_crypt"  # Хеширование ввода в память
      confirm: yes
  tasks:
    - name: Деплой приложения
      ansible.builtin.command: /opt/deploy.sh "{{ deploy_version }}"
```

### Сценарий 12: Canary deployment с проверкой здоровья

Поэтапный деплой с автоматической проверкой здоровья сервиса перед переходом к следующему хосту.

```yaml
- name: Canary deployment
  hosts: web_servers
  serial: 1
  vars:
    health_url: "http://{{ inventory_hostname }}:8080/health"
  tasks:
    - name: Деплой новой версии
      ansible.builtin.command: /opt/deploy_canary.sh

    - name: Проверка здоровья после деплоя
      ansible.builtin.uri:
        url: "{{ health_url }}"
        status_code: 200
        timeout: 30
      register: health_check
      retries: 5
      delay: 10
      until: health_check.status == 200
```

### Сценарий 13: Централизованный аудит через callback-плагин

Настройка отправки событий выполнения в SIEM для compliance и расследования инцидентов.

```yaml
# ansible.cfg
[defaults]
callback_whitelist = timer, profile_tasks, community.general.json

[callback_json]
# Путь к файлу с событиями выполнения
destination = /var/log/ansible/events.json
```

```bash
# Просмотр последних событий выполнения
cat /var/log/ansible/events.json | jq '.[] | select(.event=="runner_on_failed")'
# → Извлечь все failed-события для расследования
```

## Операции и команды

### Статический анализ и проверка синтаксиса

```bash
ansible-playbook site.yml --syntax-check
# → Проверка синтаксиса YAML и структуры плейбука

ansible-lint site.yml
# → Проверка по правилам ansible-lint (включая best practices)
# Пример вывода: site.yml:15: [warning] Use shell only when shell functionality is required
```

### Просмотр без выполнения

```bash
ansible-playbook site.yml --list-tasks
# → Показать все задачи без выполнения

ansible-playbook site.yml --list-tags
# → Показать все доступные теги

ansible-playbook site.yml --list-hosts
# → Показать хосты, затронутые плейбуком

ansible-playbook site.yml --list-hosts --limit web_servers
# → Показать хосты только группы web_servers
```

### Режим проверки и отладки

```bash
ansible-playbook site.yml --check
# → Dry-run: показать какие изменения были бы сделаны

ansible-playbook site.yml --check --diff
# → Dry-run с показом разницы в файлах

ansible-playbook site.yml --step
# → Пошаговое выполнение с интерактивным подтверждением каждой задачи
# Вывод: Perform task: name (GATHERING FACTS) => y/n/q/c

ansible-playbook site.yml --start-at-task="Выполнить миграцию"
# → Начать выполнение с указанной задачи

ansible-playbook site.yml -vvv
# → Подробный вывод (максимальная детализация -vvvv)
# Пример: <web_servers> ESTABLISH SSH CONNECTION FOR USER: deploy
```

### Проверка подключения и сбор фактов

```bash
ansible all -m ping -i inventory.ini
# → Проверить доступность всех хостов
# Пример: web01 | SUCCESS => {"changed": false, "ping": "pong"}

ansible web_servers -m setup -i inventory.ini
# → Собрать факты о хостах группы web_servers

ansible web_servers -m setup -i inventory.ini -a "filter=ansible_distribution*"
# → Собрать только факты о дистрибутиве

ansible-doc -l | grep -i package
# → Показать все модули для работы с пакетами

ansible-doc ansible.builtin.apt
# → Показать документацию модуля apt с примерами
```

### Просмотр инвентаря

```bash
ansible-inventory --list
# → Показать все группы и хосты в JSON

ansible-inventory --graph
# → Визуализировать структуру инвентаря
# Пример: @all:
#           |_@ungrouped:
#           |_web_servers:
#             |_web01
#             |_web02

ansible-inventory --host web01
# → Показать переменные конкретного хоста
```

### Отладка переменных и фактов

```yaml
# Вывод конкретной переменной
- name: Отладка переменной
  ansible.builtin.debug:
    var: my_variable

# Вывод сообщения с интерполяцией
- name: Отладка сообщения
  ansible.builtin.debug:
    msg: "Значение: {{ my_variable }}"

# Вывод всех фактов хоста
- name: Все факты
  ansible.builtin.debug:
    var: hostvars[inventory_hostname]

# Вывод переменных из group_vars
- name: Переменные группы
  ansible.builtin.debug:
    var: hostvars[inventory_hostname]['group_names']
```

## Типичные ошибки и troubleshooting

### Ошибка: "Could not match supplied host pattern"

**Причина:** Группа не определена в инвентаре или имя группы указано неверно.

**Решение:** Просмотрите инвентарь:
```bash
ansible-inventory --list
# → Показать все группы и хосты в JSON

ansible-inventory --graph
# → Визуализировать структуру инвентаря
```

### Ошибка: "FAILED! => {'msg': 'The field X is not allowed'}"

**Причина:** Использование директивы на неподходящем уровне (например, `become` внутри `tasks` вместо `play` или `task`).

**Решение:** Проверьте уровень использования директивы. `become`, `serial`, `strategy` задаются на уровне Play или Task.

### Ошибка: "Undefined variable" при использовании `import_tasks`

**Причина:** `import_tasks` выполняется на этапе парсинга и не видит переменные из `register` или факты хостов.

**Решение:** Используйте `include_tasks` для динамического включения с переменными.

### Ошибка: "No such file or directory" при `include_tasks`

**Причина:** Файл задач не найден. Укажите относительный путь от расположения плейбука или используйте `ansible.cfg` с `roles_path`.

**Решение:**
```yaml
# Правильно: относительный путь от плейбука
- ansible.builtin.include_tasks: tasks/configure.yml

# Или через roles_path
- ansible.builtin.include_role:
    name: my_role
```

### Ошибка: "Handler 'X' not found"

**Причина:** Обработчик вызван через `notify`, но не определен в секции `handlers` или included роли.

**Решение:** Убедитесь, что имя обработчика совпадает. Обработчики определяются отдельно и выполняются только один раз.

### Ошибка: "Unexpected failure during module execution" при async

**Причина:** Фоновая задача не завершилась или потерялась при перезапуске Control Node.

**Решение:** Проверьте, что `async_status` корректно опрашивает статус. Используйте `until` с `retries` для надежного ожидания:
```yaml
- name: Ожидание завершения фоновой задачи
  ansible.builtin.async_status:
    jid: "{{ async_job.ansible_job_id }}"
  register: job_status
  until: job_status.finished
  retries: 30
  delay: 10
```

### Ошибка: `delegate_to` на недоступный хост

**Причина:** Целевой хост для делегирования не в инвентаре или недоступен по SSH.

**Решение:** Убедитесь, что хост для делегирования доступен:
```bash
ansible zabbix_server -m ping
# → Проверить доступность сервера мониторинга
```

### Ошибка: `strategy: free` с разделяемым состоянием

**Причина:** В стратегии `free` задачи не ждут друг друга на границах, что может привести к race condition при доступе к общим ресурсам (файлы, БД).

**Решение:** Используйте `linear` для зависимых операций или синхронизируйте доступ через `wait_for`:
```yaml
- name: Ожидание освобождения ресурса
  ansible.builtin.wait_for:
    path: /var/run/migration.lock
    state: absent
    timeout: 300
```

### Управление состоянием между плейбуками

По умолчанию переменные `set_fact` и `register` живут только в рамках одного плея. При запуске нескольких плейбуков подряд состояние теряется. Для передачи данных между этапами используйте файлы-артефакты или внешнее хранилище.

**Паттерн 1: Файл состояния (JSON/YAML)**

```yaml
# playbooks/deploy_app.yml — сохранение состояния
- name: Собрать информацию о деплое
  ansible.builtin.set_fact:
    deploy_info:
      version: "{{ app_version }}"
      timestamp: "{{ ansible_date_time.iso8601 }}"
      commit: "{{ lookup('env', 'GITHUB_SHA') | default('unknown', true) }}"

- name: Записать состояние в файл
  ansible.builtin.copy:
    content: "{{ deploy_info | to_nice_json }}"
    dest: "/var/tmp/ansible_state/{{ inventory_hostname }}_deploy.json"
    mode: "0644"
  delegate_to: "{{ inventory_hostname }}"

# playbooks/health_check.yml — чтение состояния
- name: Прочитать состояние деплоя
  ansible.builtin.slurp:
    src: "/var/tmp/ansible_state/{{ inventory_hostname }}_deploy.json"
  register: deploy_state

- name: Парсинг JSON
  ansible.builtin.set_fact:
    previous_deploy: "{{ deploy_state.content | b64decode | from_json }}"

- name: Проверка версии
  ansible.builtin.assert:
    that:
      - previous_deploy.version is defined
    fail_msg: "Состояние деплоя не найдено"
```

**Паттерн 2: Fact Caching между плейбуками**

Включите кэширование фактов в `ansible.cfg`:

```ini
[defaults]
fact_caching = jsonfile
fact_caching_connection = /tmp/ansible_facts_cache
fact_caching_timeout = 86400
```

Теперь факты, помеченные `cacheable: true`, доступны в последующих запусках:

```yaml
- name: Сохранить версию приложения в кэш
  ansible.builtin.set_fact:
    app_deployed_version: "{{ app_version }}"
    cacheable: true
    cache_timeout: 3600
```

**Паттерн 3: Артефакты в CI/CD**

При запуске через CI/CD передавайте данные через артефакты пайплайна:

```yaml
# Сохранение артефакта
- name: Записать версию деплоя
  ansible.builtin.copy:
    content: "{{ app_version }}"
    dest: "{{ playbook_dir }}/../../artifacts/version.txt"
  delegate_to: localhost
  run_once: true

# Загрузка артефакта в следующем джобе
# В CI/CD: download-artifact → передача как extra_var
ansible-playbook playbooks/health_check.yml -e "expected_version=2.3.1"
```

**Паттерн 4: Централизованное хранилище (Redis)**

Для крупных инвентарей используйте Redis для фактов и состояния:

```ini
[defaults]
fact_caching = redis
fact_caching_connection = localhost:6379:0
fact_caching_timeout = 86400
```

**Ограничения и рекомендации:**
- Файлы состояния должны быть идемпотентными: повторный запуск не должен ломать парсинг.
- Используйте `delegate_to: localhost` для записи артефактов, чтобы не перегружать управляемые узлы.
- Для секретов никогда не записывайте их в файлы состояния без шифрования.
- Очищайте устаревшие state-файлы через `find` + `mtime` или `tmpfiles.d`.

### Ошибка: `async` задача потеряна после перезапуске Control Node

**Причина:** Фоновые задачи хранятся в памяти Control Node. При перезапуске все `async` задачи с `poll: 0` теряются.

**Решение:** Для критичных операций используйте внешний трекинг:
```yaml
- name: Сохранить job ID во внешнее хранилище
  ansible.builtin.copy:
    content: "{{ async_job.ansible_job_id }}"
    dest: "/var/run/ansible_jobs/{{ inventory_hostname }}.jid"
  delegate_to: localhost
  run_once: true
```

### Ошибка: `include_role` в цикле вызывает каскадные ошибки

**Причина:** Множественные `include_role` в `loop` создают отдельные экземпляры роли для каждого элемента, что замедляет выполнение и может исчерпать лимиты.

**Решение:** Используйте `loop` на уровне задач внутри роли или запускайте роль один раз с `run_once`:
```yaml
# Вместо include_role в loop:
- name: Выполнить роль один раз
  ansible.builtin.include_role:
    name: my_role
  run_once: true
  vars:
    targets: "{{ groups['all'] }}"
```

## Лучшие практики

### Безопасность и аудит

1.  **`no_log: true`.** Скрывайте задачи, содержащие пароли, ключи API и другие секреты. Внимание: `--diff` может раскрыть содержимое секретов в файловых операциях; используйте `diff: false`.
2.  **Vault для секретов.** Используйте `ansible-vault encrypt` для зашифровки файлов с секретами. Никогда не коммитьте ключи Vault в Git.
3.  **`become` только когда необходимо.** Не поднимайте привилегии на весь плейбук, если это не требуется для каждой задачи. Используйте `become_user` для точного контроля.
4.  **Callback-плагины для аудита.** Настройте `callbacks_enabled = timer, profile_tasks` или внешние плагины (`community.general.logstash`, `community.general.splunk`) для отправки событий выполнения в SIEM.
5.  **Защита `ansible.cfg`.** Убедитесь, что файл защищен от записи (`0644` или `0600`), чтобы предотвратить подмену путей к библиотекам или вредоносные callback-плагины.

### Производительность и масштабирование

6.  **`gather_facts: false`.** Отключайте сбор фактов, если они не используются. Для частичного сбора используйте `gather_subset`.
7.  **`serial` для больших инвентарей.** Используйте пакетную обработку для контроля нагрузки и предотвращения перегрузки управляемых узлов. Для production рекомендуется `forks = 10` в `ansible.cfg`.
8.  **`pipelining = true`.** Включите в `ansible.cfg` для ускорения выполнения (требует `requiretty` в sudoers или его отключение).
9.  **Fact Caching.** Используйте `fact_caching = jsonfile` или `redis` для ускорения повторных запусков на больших инвентарях. Таймаут кэша: `fact_caching_timeout = 86400` (24 часа).
10. **`throttle` для внешних API.** Ограничивайте конкурентность задач, обращающихся к внешним API, через `throttle` для избежания rate limits.

### Надежность и отладка

11. **`--syntax-check`.** Всегда проверяйте синтаксис перед запуском.
12. **`--check --diff`.** Используйте dry-run перед реальными изменениями. Для production-деплоя это обязательный шаг.
13. **`debug` и `assert`.** Проверяйте переменные и условия в плейбуках. Используйте `debugger: on_failed` для интерактивного анализа ошибок.
14. **Drift Detection.** Периодически запускайте плейбуки в режиме `--check` для обнаружения несанкционированных изменений (configuration drift). Интегрируйте в CI/CD пайплайн.
15. **`changed_when` / `failed_when`.** Переопределяйте статусы задач для корректной отчетности о состоянии системы. Это критично для модулей `command` и `shell`, которые по умолчанию всегда возвращают `changed`.
16. **`any_errors_fatal` для критичных операций.** Используйте для миграций БД и других необратимых операций, где ошибка на одном хосте должна остановить весь плей.
17. **`force_handlers: true`.** Для критичных сервисов (базы данных, балансировщики) настройте принудительное выполнение обработчиков даже при ошибках плейбука.

### Тестирование и валидация

18. **Статический анализ в CI.** Добавьте `ansible-lint` и `--syntax-check` в пайплайн. Используйте профиль `security` для проверки SECURITY.md правил.
19. **Теги для окружений.** Используйте теги `--tags deploy --skip-tags test` для разделения логики между staging и production.
20. **Версионирование плейбуков.** Храните плейбуки в Git. Каждое изменение должно проходить через Pull Request с ревью.
21. **Модульное тестирование ролей.** Используйте Molecule + Testinfra для тестирования ролей на изолированных окружениях (Docker, Podman). Подробнее: **[Тестирование Ansible-ролей](../ansible_testing_with_molecule.md)**.

### Импорты и включения

22. **`import_*` по умолчанию.** Используйте статические включения для фиксированной структуры — это быстрее и проще для отладки.
23. **`include_*` только при необходимости.** Динамические включения используйте только когда нужна условная логика или циклы.
24. **Избегайте `include_role` в циклах.** Множественные `include_role` замедляют выполнение. Рассмотрите `loop` на уровне задач.
25. **`include_playbook` для условных плейбуков.** Используйте для динамического подключения целых плейбуков по результатам проверок.
26. **`listen` для общих обработчиков.** Используйте `listen` для создания общих обработчиков, доступных из нескольких ролей по разным именам `notify`.

### Документация и поддерживаемость

27. **Один плей = одна цель.** Не смешивайте установку, конфигурацию и деплой в одном плее.
28. **Плейбуки-оркестраторы.** Верхнеуровневые плейбуки должны вызывать роли через `import_playbook` или `roles`, а не содержать задачи напрямую.
29. **FQCN.** Всегда используйте полные имена модулей (`ansible.builtin.apt` вместо `apt`) для исключения конфликтов имен.
30. **Идемпотентность.** Используйте специализированные модули вместо `shell`/`command` для обеспечения идемпотентности. Документируйте неидемпотентные операции.
31. **Переменные в `defaults/`.** Значения по умолчанию определяйте в `roles/x/defaults/main.yml` — это самый низкий приоритет и легко переопределяется через `group_vars/`.
32. **Атомарность изменений.** Каждая задача должна выполнять одно атомарное изменение. Используйте `block/rescue/always` для группировки связанных изменений с возможностью отката.
33. **Валидация перед применением.** Для критичных операций используйте `validate` параметр модулей (`template`, `copy`) для проверки конфигурации до применения (например, `nginx -t`).

## Дополнительная информация

* [Основы структуры плейбуков](basics.md) — компоненты, иерархия выполнения и FQCN.
* [Управление ходом выполнения](flow_control.md) — подробнее об условиях `when`, циклах `loop` и тегах.
* [Переменные и факты](variables.md) — детальная иерархия приоритетов и использование системных данных.
* [Валидация и тестирование структуры плейбуков](testing_and_validation.md) — статический анализ, dry-run и идемпотентность.
* [Оптимизация производительности](../ansible_performance_tuning.md) — тюнинг SSH, `pipelining` и стратегии выполнения.
* [Антипаттерны Ansible](../ansible_bad_practices.md) — типичные ошибки при проектировании продвинутой логики.
* [Шаблонизация Jinja2](../ansible_jinja_templating.md) — продвинутая обработка данных (JMESPath, сложные фильтры и lookups).
