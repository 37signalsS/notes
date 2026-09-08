# Ansible: управление ходом выполнения

## Определения

**Управление ходом выполнения (Flow Control)** — механизмы Ansible, позволяющие динамически определять логику выполнения задач в зависимости от состояния системы, результатов предыдущих шагов или внешних условий.

**Условная конструкция (`when`)** — директива, определяющая выполнение задачи на основе логического выражения Jinja2. Поддерживает сложные составные условия.

**Цикл (`loop`)** — итератор, позволяющий выполнять одну задачу многократно для списка элементов. Современный стандарт, заменивший устаревшие конструкции `with_*`.

**Цикл ожидания (`until`)** — механизм повторного выполнения задачи до тех пор, пока не будет выполнено определенное условие или не истечет количество попыток.

**Регистрация (`register`)** — механизм захвата и сохранения полного JSON-ответа модуля в переменную для последующего анализа и использования в логике плейбука.

**Тег (Tag)** — метка, позволяющая выборочно запускать или пропускать части плейбука при запуске через командную строку.

**Блок (Block)** — логическая группировка задач для совместной обработки ошибок и применения общих параметров.

**Директива ошибок блока (`errors`)** — параметр блока, определяющий политику обработки ошибок: `ignore` (продолжить как будто ошибки не было), `result` (продолжить, но сохранить статус ошибки в переменной `block_result`), `fatal` (прекратить выполнение, поведение по умолчанию).

## Базовые концепции

### Условные конструкции (when)

*   Принимает логические выражения в синтаксисе Jinja2.
*   **Безопасность (2.17+):** Использование фигурных скобок `{{ }}` внутри `when` считается плохой практикой и может привести к ошибкам безопасности (CVE-2023-5764). Используйте прямые обращения к переменным: `when: my_var == "value"`.
*   Если передается список условий, они трактуются как логическое «И» (AND). Для «ИЛИ» используйте оператор `or`.
*   Полезные тесты: `is defined`, `is subset`, `is match('regex')`, `is success`.

**Примеры использования тестов в `when`:**

```yaml
# Проверка существования переменной перед использованием
- name: Настройка только если переменная определена
  ansible.builtin.debug:
    msg: "Значение: {{ custom_value }}"
  when: custom_value is defined

# Проверка формата строки через регулярное выражение
- name: Валидация версии приложения
  ansible.builtin.assert:
    that:
      - app_version is match('^v[0-9]+\.[0-9]+\.[0-9]+$')
    fail_msg: "app_version должен быть в формате vX.Y.Z"

# Проверка успешности предыдущей задачи
- name: Установка пакетов с retry
  ansible.builtin.apt:
    name: nginx
    state: present
  register: apt_result
  until: apt_result is success
  retries: 3
  delay: 10

# Проверка принадлежности к списку
- name: Установка пакетов только для определенных ОС
  ansible.builtin.apt:
    name: apache2
    state: present
  when: ansible_facts['os_family'] is subset(['Debian', 'Ubuntu'])

# Составные условия
- name: Комплексная проверка окружения
  ansible.builtin.debug:
    msg: "Продакшн окружение готово"
  when:
    - target_env is defined
    - target_env == "production"
    - ansible_facts['os_family'] in ['Debian', 'RedHat']
```

### Циклы и итерация

1.  **`loop`**: Основной итератор. Для работы со сложными структурами данных используются фильтры `dict2items`, `subelements`, `flatten`.

**Примеры использования фильтров в `loop`:**

```yaml
# dict2items — преобразование словаря в список для итерации
- name: Создание пользователей из словаря
  ansible.builtin.user:
    name: "{{ item.key }}"
    uid: "{{ item.value.uid }}"
  loop: "{{ users_dict | dict2items }}"
  vars:
    users_dict:
      alice: { uid: 1001 }
      bob:   { uid: 1002 }

# flatten — «сплющивание» вложенных списков в один
- name: Установка пакетов из вложенных списков
  ansible.builtin.package:
    name: "{{ item }}"
    state: present
  loop: "{{ [web_packages, db_packages] | flatten }}"
  vars:
    web_packages: [nginx, php-fpm]
    db_packages: [mysql-server, php-mysql]

# subelements — итерация по вложенным элементам внутри списка словарей
- name: Добавление SSH-ключей для пользователей
  ansible.builtin.authorized_key:
    user: "{{ item.0.name }}"
    key: "{{ item.1 }}"
  loop: "{{ users | subelements('ssh_keys') }}"
  vars:
    users:
      - name: alice
        ssh_keys:
          - "ssh-ed25519 AAAA... alice@work"
          - "ssh-ed25519 BBBB... alice@home"
      - name: bob
        ssh_keys:
          - "ssh-ed25519 CCCC... bob@office"

# Комбинирование фильтров
- name: Установка всех зависимостей из групп
  ansible.builtin.package:
    name: "{{ item }}"
    state: present
  loop: "{{ dependency_groups | map(attribute='packages') | flatten | unique }}"
  vars:
    dependency_groups:
      - name: web
        packages: [nginx, openssl]
      - name: db
        packages: [mysql, openssl]
```
2.  **`until`, `retries`, `delay`**: Используются для ожидания события (например, доступности порта или завершения фонового процесса). Задача будет повторяться до выполнения условия в `until`.
3.  **`loop_control`**:
    *   `loop_var`: Изменение имени переменной итерации (по умолчанию `item`). Критично для вложенных циклов.
    *   `pause`: Задержка между итерациями цикла.
    *   `label`: Ограничение объема вывода в консоль (скрывает длинные JSON-структуры).
    *   `index_var`: Доступ к текущему порядковому номеру итерации.

**Пример использования `index_var`:**

```yaml
- name: Вывод порядкового номера итерации
  ansible.builtin.debug:
    msg: "Итерация {{ idx }}: {{ item }}"
  loop: ["first", "second", "third"]
  loop_control:
    index_var: idx

# Результат:
# Итерация 0: /first
# Итерация 1: /second
# Итерация 2: /third
```

**Примечание:** `loop.index` (начинается с 1) и `loop.index0` (начинается с 0) также доступны без явного указания `index_var`. Однако `index_var` предпочтителен для вложенных циклов, где `loop.*` переменные перезаписываются внешним циклом.

### Запуск задачи N раз с разными параметрами

Для генерации числовой последовательности используйте `lookup('sequence', ...)`:

```yaml
- name: Запуск таски с 10 параметрами
  ansible.builtin.command: /opt/script.sh --param {{ item }}
  loop: "{{ lookup('sequence', 'start=1', 'end=10') | list }}"
  register: results
```

Или с использованием простого списка:

```yaml
- name: Обработка списка хостов
  ansible.builtin.command: /opt/check.sh {{ item }}
  loop:
    - host1.example.com
    - host2.example.com
    - host3.example.com
```

Подробнее: **[Переменные и приоритеты](../../Ansible/PlaybookStructure/variables.md)**.

### Регистрация и переопределение статусов

Ansible определяет успешность задачи по коду возврата (RC). Это поведение можно переопределить:
*   **`register`**: Захватывает полный объект ответа модуля (`changed`, `failed`, `stdout`, `rc`).
*   **`changed_when`**: Задает условие, при котором задача считается изменившей систему. Важно для модулей `command` и `shell`.
*   **`failed_when`**: Задает специфическое условие сбоя, перекрывая стандартную проверку RC.

### Обработка ошибок и контроль выполнения

*   **`ignore_errors: true`**: Продолжение выполнения плейбука при сбое задачи.
*   **`any_errors_fatal: true`**: Немедленная остановка всего плейбука на всех хостах, если задача упала хотя бы на одном.
*   **`max_fail_percentage`**: Лимит падений хостов, после которого весь плей останавливается. Работает только совместно с `serial`. Значение `0` останавливает при первой ошибке.
*   **`ignore_unreachable: true`**: Игнорирование ошибок сетевой доступности хоста.
*   **`throttle`**: Лимит одновременных задач для конкретного шага (полезно для обхода rate limits внешних API).
*   **`check_mode`**: Директива `check_mode: false` позволяет задаче выполняться даже при запуске `ansible-playbook --check`.

**`ignore_errors` vs `block/rescue` — когда что использовать:**

| Сценарий | Рекомендация | Причина |
| :--- | :--- | :--- |
| Ожидаемый non-zero exit code | `failed_when` | Тонкий контроль, без логики восстановления |
| Однократная проверка, не критичная | `ignore_errors: true` | Минимальный оверхед |
| Критичная операция с возможностью отката | `block/rescue` | Гарантированное восстановление состояния |
| Необходимость очистки ресурсов | `block/always` | `always` выполняется всегда, даже при ошибке |
| Скрытие реальных проблем | **Антипаттерн** | `ignore_errors` маскирует ошибки, которые требуют расследования |

```yaml
# Паттерн 1: ignore_errors для не критичной проверки
- name: Проверка наличия опционального сервиса
  ansible.builtin.command: systemctl is-active monitoring-agent
  register: agent_status
  ignore_errors: true
  changed_when: false

# Паттерн 2: block/rescue для критичной операции
- name: Применение конфигурации с откатом
  block:
    - name: Копирование нового конфига
      ansible.builtin.copy:
        src: app.conf.new
        dest: /etc/app/app.conf
    - name: Валидация конфигурации
      ansible.builtin.command: /usr/bin/app --validate
  rescue:
    - name: Восстановление старого конфига
      ansible.builtin.copy:
        src: app.conf.backup
        dest: /etc/app/app.conf
```

### Блоки и обработка исключений

Конструкция `block` реализует логику `try-rescue-always`:
*   `block`: Основная логика.
*   `rescue`: Выполняется при ошибке в `block`. Позволяет реализовать откат (rollback).
*   `always`: Выполняется всегда (очистка временных файлов, закрытие соединений).

**Директива `errors` в блоке:**

Позволяет настроить политику обработки ошибок на уровне всего блока:

*   `errors: fatal` (по умолчанию) — ошибка в `block` прерывает выполнение и переходит в `rescue`.
*   `errors: ignore` — ошибка в `block` игнорируется, выполнение продолжается со следующей задачи. `rescue` не выполняется.
*   `errors: result` — ошибка в `block` игнорируется, но статус ошибки сохраняется в переменную `block_result`. `rescue` не выполняется.

```yaml
# errors: ignore — игнорировать ошибки без перехода в rescue
- name: Проверка необязательных зависимостей
  block:
    - name: Проверка наличия опционального пакета
      ansible.builtin.command: rpm -q optional-package
    errors: ignore

# errors: result — игнорировать, но сохранить статус
- name: Проверка с фиксацией результата
  block:
    - name: Попытка подключения к сервису
      ansible.builtin.uri:
        url: "http://{{ service_host }}:{{ service_port }}/health"
        status_code: 200
      register: health_check
    errors: result

- name: Логирование результата проверки
  ansible.builtin.debug:
    msg: "Сервис доступен: {{ health_check is success }}"
  when: health_check is defined
```

### Тегирование

*   `always`: Задача выполняется всегда, если не пропущена через `--skip-tags always`.
*   `never`: Задача никогда не выполняется, если не вызвана через `--tags never`.

## Практические сценарии

### Сценарий 1: Умная проверка состояния (changed_when / failed_when)

Переопределение логики для `grep`, который возвращает 1, если строка не найдена.

```yaml
- name: Проверить настройку в конфигурации
  ansible.builtin.command: grep -q 'StrictHostKeyChecking no' /etc/ssh/ssh_config
  register: grep_result
  failed_when: grep_result.rc > 1
  changed_when: false

- name: Добавить настройку при отсутствии
  ansible.builtin.lineinfile:
    path: /etc/ssh/ssh_config
    line: 'StrictHostKeyChecking no'
  when: grep_result.rc == 1
```

### Сценарий 2: Цикл ожидания доступности сервиса (until)

```yaml
- name: Ожидание готовности API
  ansible.builtin.uri:
    url: http://localhost:8080/health
    status_code: 200
  register: api_res
  until: api_res.status == 200
  retries: 12
  delay: 10
```

### Сценарий 3: Гарантированная очистка ресурсов (Block-Always)

```yaml
- name: Работа с временными данными
  block:
    - name: Создать временную директорию
      ansible.builtin.file:
        path: /tmp/app_build
        state: directory
    - name: Сборка приложения
      ansible.builtin.command: /usr/bin/make_build --dir /tmp/app_build
  always:
    - name: Удалить временную директорию
      ansible.builtin.file:
        path: /tmp/app_build
        state: absent
```

### Сценарий 4: Сложные циклы с loop_control (label)

```yaml
- name: Создание пользователей из словаря
  ansible.builtin.user:
    name: "{{ item.key }}"
    uid: "{{ item.value.uid }}"
    state: present
  loop: "{{ users_dict | dict2items }}"
  loop_control:
    label: "User: {{ item.key }}"
  vars:
    users_dict:
      alice: { uid: 1001 }
      bob:   { uid: 1002 }
```

### Сценарий 5: Вложенные циклы через include_tasks и loop_var

**Главный плейбук:**
```yaml
- name: Обработка приложений
  ansible.builtin.include_tasks: process_app.yml
  loop: ['frontend', 'backend']
  loop_control:
    loop_var: app_name
```

**Файл `process_app.yml`:**
```yaml
- name: "Настройка компонентов для {{ app_name }}"
  ansible.builtin.debug:
    msg: "App: {{ app_name }}, Component: {{ item }}"
  loop: ['config', 'service']
```

### Сценарий 6: Обработка режима проверки (check_mode)

```yaml
- name: Получить статус (всегда выполнять)
  ansible.builtin.command: /usr/bin/check_tool
  check_mode: false
  register: tool_status
  changed_when: false

- name: Применить изменения
  ansible.builtin.template:
    src: config.j2
    dest: /etc/app/config.conf
  when: tool_status.stdout == "NEED_UPDATE"
```

### Сценарий 7: Фатальные ошибки на критических этапах

```yaml
- name: Критическая миграция БД
  ansible.builtin.command: /usr/bin/db_migrate
  run_once: true
  any_errors_fatal: true
```

### Сценарий 8: Сложные условия в `when` с тестами Jinja2

```yaml
- name: Настройка только для production окружения с валидной версией
  block:
    - name: Валидация версии приложения
      ansible.builtin.assert:
        that:
          - app_version is defined
          - app_version is match('^v[0-9]+\.[0-9]+\.[0-9]+$')
          - target_env == "production"
        fail_msg: "Невалидная версия или окружение"

    - name: Применение конфигурации
      ansible.builtin.template:
        src: "config/{{ target_env }}.j2"
        dest: /etc/app/config.yml
  when:
    - ansible_facts['os_family'] is defined
    - ansible_facts['os_family'] in ['Debian', 'RedHat']
    - "'web_servers' in group_names"
```

### Сценарий 9: Управление SSH-ключами через `subelements`

```yaml
- name: Настройка SSH-ключей для пользователей
  hosts: all
  become: true
  vars:
    users:
      - name: deploy
        ssh_keys:
          - "ssh-ed25519 AAAA... deploy@ci"
          - "ssh-ed25519 BBBB... deploy@backup"
      - name: monitor
        ssh_keys:
          - "ssh-ed25519 CCCC... monitor@zabbix"

  tasks:
    - name: Добавление SSH-ключей
      ansible.builtin.authorized_key:
        user: "{{ item.0.name }}"
        key: "{{ item.1 }}"
        state: present
      loop: "{{ users | subelements('ssh_keys') }}"
      loop_control:
        label: "{{ item.0.name }}: {{ item.1[:20] }}..."
```

### Сценарий 10: `ignore_errors` vs `block/rescue` в реальном сценарии

```yaml
- name: Деплой приложения с обработкой ошибок
  hosts: app_servers
  become: true

  tasks:
    # Не критичная проверка — используем ignore_errors
    - name: Проверка версии текущего приложения
      ansible.builtin.command: /opt/app/bin/version
      register: current_version
      ignore_errors: true
      changed_when: false

    # Критичная операция — используем block/rescue
    - name: Обновление приложения
      block:
        - name: Скачивание новой версии
          ansible.builtin.get_url:
            url: "https://releases.example.com/app-{{ app_version }}.tar.gz"
            dest: /tmp/app.tar.gz

        - name: Распаковка
          ansible.builtin.unarchive:
            src: /tmp/app.tar.gz
            dest: /opt/app/
            remote_src: true

        - name: Валидация конфигурации
          ansible.builtin.command: /opt/app/bin/validate-config
          register: config_check

        - name: Перезапуск сервиса
          ansible.builtin.systemd:
            name: myapp
            state: restarted

      rescue:
        - name: Восстановление предыдущей версии
          ansible.builtin.copy:
            src: /opt/app/backup/
            dest: /opt/app/
            remote_src: true

        - name: Перезапуск с предыдущей версией
          ansible.builtin.systemd:
            name: myapp
            state: restarted

        - name: Уведомление об ошибке
          ansible.builtin.uri:
            url: "{{ slack_webhook }}"
            method: POST
            body_format: json
            body:
              text: "Ошибка деплоя на {{ inventory_hostname }}"

      always:
        - name: Очистка временных файлов
          ansible.builtin.file:
            path: /tmp/app.tar.gz
            state: absent
```

### Сценарий 11: Фоновое выполнение с ожиданием (async + until)

```yaml
- name: Длительное обновление ОС в фоне
  block:
    - name: Запуск обновления в фоне
      ansible.builtin.yum:
        name: "*"
        state: latest
      async: 3600
      poll: 0
      register: update_job

    - name: Выполнение других задач во время обновления
      ansible.builtin.debug:
        msg: "Обновление выполняется в фоне..."

    - name: Ожидание завершения обновления
      ansible.builtin.async_status:
        jid: "{{ update_job.ansible_job_id }}"
      register: job_status
      until: job_status.finished
      retries: 60
      delay: 60

    - name: Проверка необходимости перезагрузки
      ansible.builtin.stat:
        path: /var/run/reboot-required
      register: reboot_required

    - name: Перезагрузка при необходимости
      ansible.builtin.reboot:
      when: reboot_required.stat.exists

  rescue:
    - name: Откат обновления
      ansible.builtin.shell: |
        yum history undo last -y
      args:
        executable: /bin/bash
```

### Сценарий 12: Ограничение нагрузки на API (throttle) и контроль ошибок

```yaml
- name: Массовая регистрация серверов в внешнем сервисе
  hosts: app_servers
  serial: "25%"
  max_fail_percentage: 5

  tasks:
    - name: Регистрация в API мониторинга
      ansible.builtin.uri:
        url: "https://monitoring.example.com/api/v1/hosts"
        method: POST
        body_format: json
        body:
          hostname: "{{ inventory_hostname }}"
          ip: "{{ ansible_default_ipv4.address }}"
          groups: "{{ group_names }}"
        status_code: [200, 201]
      register: registration
      until: registration.status in [200, 201]
      retries: 3
      delay: 5
      throttle: 5  # Не более 5 одновременных запросов к API

    - name: Регистрация в балансировщике
      ansible.builtin.uri:
        url: "https://lb.example.com/api/backends"
        method: POST
        body_format: json
        body:
          host: "{{ ansible_default_ipv4.address }}"
          port: 8080
      throttle: 1  # Строго по одному запросу для сохранения кворума
```

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

# Проверка условий перед выполнением
- name: Отладка условия when
  ansible.builtin.debug:
    msg: "Условие выполнится: {{ target_env is defined and target_env == 'production' }}"
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

### Ошибка: "Undefined variable" при `when` или `register`

**Причина:** Переменная не определена или не собрана (например, факты не собраны через `gather_facts`).

**Решение:**
```yaml
# Проверка существования перед использованием
- name: Безопасное использование переменной
  ansible.builtin.debug:
    msg: "Значение: {{ my_var | default('не задано') }}"
  when: my_var is defined

# Или с обязательной проверкой через assert
- name: Валидация обязательных переменных
  ansible.builtin.assert:
    that:
      - my_var is defined
      - my_var | length > 0
    fail_msg: "Переменная my_var не определена или пуста"
```

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

### Ошибка: "Unexpected failure during module execution" при async

**Причина:** Фоновая задача не завершилась или потерялась при перезапуске Control Node.

**Решение:** Проверьте, что `async_status` корректно опрашивает статус. Используйте `until` с `retries` для надежного ожидания. Увеличьте `async` таймаут при необходимости.

### Ошибка: "Variable is not defined" в `loop`

**Причина:** Итерируемая переменная не определена или пуста.

**Решение:**
```yaml
- name: Безопасный цикл
  ansible.builtin.debug:
    msg: "{{ item }}"
  loop: "{{ my_list | default([]) }}"
  when: my_list is defined
```

### Ошибка: `max_fail_percentage` не останавливает плей

**Причина:** `max_fail_percentage` работает только совместно с `serial`. Без `serial` параметр игнорируется.

**Решение:**
```yaml
# Правильно: max_fail_percentage + serial
- name: Обновление с контролем ошибок
  hosts: web_servers
  serial: "25%"
  max_fail_percentage: 10
  tasks:
    - name: Обновление
      ansible.builtin.package:
        name: "*"
        state: latest
```

## Edge cases и ограничения

### `when` с undefined переменными

При использовании `when` с переменными, которые могут быть не определены, Ansible выбросит ошибку. Используйте `is defined` перед обращением:

```yaml
# ОШИБКА: переменная может быть не определена
- name: Опасное условие
  ansible.builtin.debug:
    msg: "Найдено"
  when: optional_var == "value"

# ПРАВИЛЬНО: сначала проверить существование
- name: Безопасное условие
  ansible.builtin.debug:
    msg: "Найдено"
  when: optional_var is defined and optional_var == "value"
```

### `loop` с пустым списком

Пустой список в `loop` не вызывает ошибку — задача просто не выполняется ни разу. Это безопасно и не требует дополнительных проверок:

```yaml
# Если package_list пуст, задача не выполнится ни разу
- name: Установка пакетов
  ansible.builtin.package:
    name: "{{ item }}"
    state: present
  loop: "{{ package_list | default([]) }}"
```

### `until` без `retries`

Параметр `until` без `retries` приводит к выполнению задачи только один раз. Всегда указывайте `retries` и `delay`:

```yaml
# ОШИБКА: задача выполнится только один раз
- name: Проверка сервиса
  ansible.builtin.uri:
    url: http://localhost:8080/health
  until: result.status == 200

# ПРАВИЛЬНО: с указанием retries и delay
- name: Ожидание сервиса
  ansible.builtin.uri:
    url: http://localhost:8080/health
  register: result
  until: result.status == 200
  retries: 12
  delay: 10
```

### `loop_var` во вложенных циклах

При использовании `include_tasks` с циклом во внутреннем файле необходимо переименовывать `loop_var`, иначе переменная `item` будет перезаписана:

```yaml
# Внешний цикл — используем loop_var: app
- ansible.builtin.include_tasks: process_app.yml
  loop: [frontend, backend]
  loop_control:
    loop_var: app

# Внутренний цикл в process_app.yml — использует стандартный item
- ansible.builtin.debug:
    msg: "App: {{ app }}, Config: {{ item }}"
  loop: [config, service]
```

### `async` и потеря фоновых задач

Фоновые задачи (`async` + `poll: 0`) теряются при перезапуске Ansible Control Node. Для критичных операций используйте персистентное хранение статуса или избегайте фоновых задач.

### Вложенные `block` и каскадные ошибки

При ошибке во вложенном `block` управление переходит в его `rescue`. Если `rescue` тоже падает, управление переходит в `rescue` внешнего блока. `always` выполняется всегда, даже при каскадных ошибках:

```yaml
- name: Внешний блок
  block:
    - name: Внутренний блок
      block:
        - name: Операция
          ansible.builtin.command: risky_op
      rescue:
        - name: Восстановление внутреннее
          ansible.builtin.command: recover_internal
  rescue:
    - name: Восстановление внешнее
      ansible.builtin.command: recover_external
  always:
    - name: Очистка (выполнится ВСЕГДА)
      ansible.builtin.file: path=/tmp/work state=absent
```

## Лучшие практики

### Условная логика

1. **Избегайте `{{ }}` в `when`.** Используйте прямые обращения к переменным: `when: my_var == "value"` вместо `when: "{{ my_var }}" == "value"`.
2. **Проверяйте существование.** Всегда используйте `is defined` перед обращением к потенциально не определенным переменным.
3. **Используйте `assert` для валидации.** Проверяйте обязательные переменные и условия перед критичными операциями.

### Циклы

4. **`loop_var` для вложенных циклов.** При использовании `include_tasks` с циклом всегда задавайте уникальное имя переменной.
5. **`label` для читаемости.** Ограничивайте вывод в консоль при работе со сложными структурами данных.
6. **`until` + `retries` + `delay`.** Всегда комбинируйте эти три параметра для надежного ожидания.

### Обработка ошибок

7. **`block/rescue/always` для критичных операций.** Используйте блоки для операций, требующих отката или гарантированной очистки.
8. **`changed_when` / `failed_when` для отчетности.** Переопределяйте статусы задач для корректной информации об изменениях.
9. **`any_errors_fatal` для критичных плеев.** Останавливайте весь плейбук при ошибке на одном хосте для критичных операций (миграции БД).

### Производительность

10. **`throttle` для API.** Ограничивайте конкурентность задач, обращающихся к внешним API.
11. **`serial` для rolling updates.** Используйте пакетную обработку для контроля нагрузки и возможности отката.
12. **`max_fail_percentage` + `serial`.** Устанавливайте порог ошибок для автоматической остановки при массовых сбоях.

### Безопасность

13. **`no_log: true` для секретов.** Скрывайте задачи, содержащие пароли и ключи API.
14. **`check_mode` для тестирования.** Используйте dry-run перед реальными изменениями.
15. **FQCN модулей.** Всегда используйте полные имена модулей (`ansible.builtin.command` вместо `command`).

## Дополнительная информация

* [Основы структуры плейбуков](basics.md) — базовые компоненты плейбука, FQCN и иерархия выполнения.
* [Продвинутые возможности](advanced.md) — детали делегирования, асинхронные задачи и отладка.
* [Переменные и факты](variables.md) — приоритеты переменных и фильтры Jinja2.
* [Антипаттерны Ansible](../ansible_bad_practices.md) — типичные ошибки в управлении логикой выполнения.
