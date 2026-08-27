# Ansible: продвинутые возможности плейбуков

## Определения

**Статическое включение (`import_tasks`, `import_role`, `import_playbook`)** — механизм, при котором содержимое внешнего файла или роли вставляется в плейбук на этапе предварительного анализа (парсинга). Это работает как прямая вставка кода до начала выполнения.

**Динамическое включение (`include_tasks`, `include_role`)** — механизм подключения задач или ролей непосредственно в процессе выполнения плейбука. Позволяет использовать переменные, факты и результаты предыдущих задач для определения логики на лету.

**Делегирование (`delegate_to`)** — перенос выполнения задачи с целевого хоста на другой узел (например, выполнение API-запроса с контрольного узла или обновление DNS-записи с балансировщика).

**Группировка задач (`block`)** — логическое объединение набора задач для совместной обработки ошибок (`rescue`, `always`) или применения общих директив (`when`, `become`).

**Асинхронное выполнение (`async`)** — запуск задачи в фоновом режиме без блокировки основного потока выполнения. Критично для длительных операций, превышающих таймауты SSH-сессий.

**Lookup-плагины** — инструменты для получения данных из внешних источников (файлы, переменные окружения, HashiCorp Vault, базы данных) на стороне контрольного узла во время выполнения.

**Фильтры (Filters)** — функции Jinja2 для преобразования данных (форматирование, парсинг, математические операции) непосредственно внутри плейбуков и шаблонов.

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

> **Рекомендация:** Используйте `import_*` для фиксированной структуры и `include_*` для гибкой логики (например, выбор задач по результатам сбора фактов). Подробнее в разделе **[Создание и использование ролей](../Roles/usage.md)**.

### Асинхронность и поллинг (Async / Poll)

Применяется для задач, занимающих более 10–15 минут (миграции БД, сборка тяжелого ПО, обновления пакетов на множестве серверов).
*   **`async`**: Максимальное время выполнения (в секундах). Если задача не завершится за этот срок, она будет принудительно остановлена. Значение `0` отключает таймаут.
*   **`poll`**: Частота опроса статуса задачи.
    *   `poll: 0`: Режим «запустил и забыл» (fire-and-forget). Ansible не ждет завершения и переходит к следующему шагу.
    *   `poll: >0`: Ansible блокирует выполнение и опрашивает статус с указанным интервалом (в секундах).

Для контроля фоновых задач используется модуль `ansible.builtin.async_status`.

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

Использование `include_tasks` для кроссплатформенных сценариев.

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

## Валидация и отладка

### Статический анализ

```bash
ansible-playbook site.yml --syntax-check
# → Проверка синтаксиса YAML и структуры плейбука

ansible-lint site.yml
# → Проверка по правилам ansible-lint (включая best practices)
```

### Просмотр без выполнения

```bash
ansible-playbook site.yml --list-tasks
# → Показать все задачи без выполнения

ansible-playbook site.yml --list-tags
# → Показать все доступные теги

ansible-playbook site.yml --list-hosts
# → Показать хосты, затронутые плейбуком
```

### Режим проверки и отладки

```bash
ansible-playbook site.yml --check
# → Dry-run: показать какие изменения были бы сделаны

ansible-playbook site.yml --check --diff
# → Dry-run с показом разницы в файлах

ansible-playbook site.yml --step
# → Пошаговое выполнение с интерактивным подтверждением каждой задачи

ansible-playbook site.yml --start-at-task="Выполнить миграцию"
# → Начать выполнение с указанной задачи

ansible-playbook site.yml -vvv
# → Подробный вывод (максимальная детализация -vvvv)
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

### Проверка подключения и сбор фактов

```bash
ansible all -m ping -i inventory.ini
# → Проверить доступность всех хостов

ansible web_servers -m setup -i inventory.ini
# → Собрать факты о хостах группы web_servers

ansible web_servers -m setup -i inventory.ini -a "filter=ansible_distribution*"
# → Собрать только факты о дистрибутиве
```

## Типичные ошибки и troubleshooting

### Ошибка: "Could not match supplied host pattern"

**Причина:** Группа не определена в инвентаре или имя группы указано неверно.

**Решение:**
```bash
ansible-inventory --list  # Просмотр всех групп и хостов
ansible-inventory --graph  # Визуализация структуры инвентаря
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

**Причина:** Обработчик вызван через `notify`, но не определен в секции `handlers` или вcluded роли.

**Решение:** Убедитесь, что имя обработчика совпадает. Обработчики определяются отдельно и выполняются только один раз.

### Ошибка: "Unexpected failure during module execution" при async

**Причина:** Фоновая задача не завершилась или потерялась при перезапуске Control Node.

**Решение:** Проверьте, что `async_status` корректно опрашивает статус. Используйте `until` с `retries` для надежного ожидания.

## Лучшие практики

### Структура плейбука

1. **Один плей = одна цель.** Не смешивайте установку, конфигурацию и деплой в одном плее.
2. **Плейбуки-оркестраторы.** Верхнеуровневые плейбуки должны вызывать роли через `import_playbook` или `roles`, а не содержать задачи напрямую.
3. **FQCN.** Всегда используйте полные имена модулей (`ansible.builtin.apt` вместо `apt`).
4. **Идиоматичность.** Используйте специализированные модули вместо `shell`/`command` для обеспечения идемпотентности.

### Import vs Include

5. **`import_*` по умолчанию.** Используйте статические включения для фиксированной структуры — это быстрее и проще для отладки.
6. **`include_*` только при необходимости.** Динамические включения используйте только когда нужна условная логика или циклы.
7. **Избегайте `include_role` в циклах.** Множественные `include_role` замедляют выполнение. Рассмотрите `loop` на уровне задач.

### Делегирование и асинхронность

8. **`delegate_to` + `run_once`.** Для скачивания артефактов комбинируйте делегирование на localhost с `run_once: true`.
9. **`async` + `poll: 0`.** Для фоновых задач всегда используйте `poll: 0`, чтобы не блокировать выполнение.
10. **`throttle` для API.** Ограничивайте конкурентность задач, обращающихся к внешним API, через `throttle`.

### Безопасность

11. **`no_log: true`.** Скрывайте задачи, содержащие пароли, ключи API и другие секреты.
12. **`diff: false`.** Отключайте вывод различий для задач с секретами, чтобы избежать утечки в логах.
13. **`become` только когда необходимо.** Не поднимайте привилегии на весь плейбук, если это не требуется для каждой задачи.

### Обработка ошибок

14. **`block/rescue/always`.** Используйте блоки для критичных операций с возможностью отката.
15. **`changed_when` / `failed_when`.** Переопределяйте статусы задач для корректной отчетности.
16. **`assert` для валидации.** Проверяйте переменные и условия перед критичными операциями.

### Strategy Plugins: продвинутое использование

#### free strategy

Стратегия `free` позволяет каждому хосту проходить плейбук максимально быстро и независимо от других хостов. В отличие от `linear`, хосты не ждут друг друга на границах задач.

**Особенности с `serial`:**
- При использовании `serial` в комбинации с `free` — хосты в текущей пачке выполняются параллельно, но пачки обрабатываются последовательно
- Если `serial` не задан, все хосты запускаются одновременно

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

#### host_pinned стратегия

`host_pinned` фиксирует хост в текущем слоте до полного завершения его сценария. Отличается от `free` тем, что хост не освобождает слот до конца выполнения (а не после каждой задачи).

**Контроль параллелизма и ограничение слотов:**
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

#### linear vs free: когда что использовать

| Сценарий | Рекомендуемая стратегия | Обоснование |
| :--- | :--- | :--- |
| Rolling update с проверкой здоровья | `linear` + `serial` | Гарантирует последовательность и контроль на каждом этапе |
| Массовый деплой (независимые хосты) | `free` | Максимальная скорость, хосты не блокируют друг друга |
| Миграция БД на кластере | `serial` + `linear` | Последовательное обновление с возможностью отката |
| Разнородные задачи (длинные + короткие) | `free` | Короткие задачи не ждут длинные |
| Ограниченные ресурсы API | `serial` + `throttle` | Контроль нагрузки на внешние системы |

**Интеграция с serial:**
```yaml
---
# Linear + serial: предсказуемое поэтапное выполнение
- name: Rolling Update
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

#### Custom strategy plugins

Кастомные strategy plugins создаются для специфических сценариев, не покрытых встроенными стратегиями.

**Структура:**
```
strategy_plugins/
├── my_strategy.py
└── __init__.py
```

**Минимальный шаблон:**
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

**Когда нужно:**
- Кастомный порядок выполнения (например, round-robin)
- Интеграция с внешними планировщиками
- Специфичная логика обработки ошибок

#### Интеграция strategy с блокированием (throttle)

`throttle` работает на уровне задач и ограничивает количество хостов, выполняющих задачу одновременно, независимо от выбранной strategy.

```yaml
---
- name: Пример throttle с разными стратегиями
  hosts: all
  strategy: free
  tasks:
    - name: Запрос к API (ограничение 5 одновременных)
      ansible.builtin.uri:
        url: https://api.example.com/deploy
        method: POST
      throttle: 5

    - name: Долгая задача без ограничений
      ansible.builtin.command: /opt/scripts/task.sh
      # throttle не установлен — все хосты выполняют параллельно

    - name: Работа с БД (ограничение 2)
      ansible.builtin.command: /opt/scripts/db_op.sh
      throttle: 2
```

**Важные нюансы:**
- `throttle` применяется **после** определения strategy
- При `serial` + `throttle` — `throttle` может уменьшить фактическую параллельность внутри пачки
- `throttle` на уровне блока (`block: throttle: 3`) применяется ко всем задачам внутри блока

## Дополнительная информация

* [Основы структуры плейбуков](basics.md) — компоненты, иерархия выполнения и FQCN.
* [Управление ходом выполнения](flow_control.md) — подробнее об условиях `when`, циклах `loop` и тегах.
* [Переменные и факты](variables.md) — детальная иерархия приоритетов и использование системных данных.
* [Оптимизация производительности](../ansible_performance_tuning.md) — тюнинг SSH, `pipelining` и стратегии выполнения.
* [Антипаттерны Ansible](../ansible_bad_practices.md) — типичные ошибки при проектировании продвинутой логики.
* [Шаблонизация Jinja2](../ansible_jinja_templating.md) — продвинутая обработка данных (JMESPath, сложные фильтры и lookups).
