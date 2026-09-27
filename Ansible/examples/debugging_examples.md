# Примеры отладки типовых проблем в Ansible

## Определения

**Отладка в Ansible** — систематический процесс идентификации и устранения неисправностей в коде автоматизации (плейбуки, роли), конфигурации инвентаря, шаблонов или сетевом взаимодействии между контрольным узлом (Control Node) и managed node.

**Managed node** — целевой хост, на котором Ansible выполняет задачи через SSH (или другой транспорт). Не требует установки агента.

**Control Node** — рабочая станция или сервер, с которого запускаются плейбуки. Требует установленного Python 3 и Ansible.

**Идемпотентность** — свойство плейбука давать одинаковый результат при многократном запуске. Нарушение идемпотентности является частой причиной логических ошибок.

**Регистрация (`register`)** — механизм захвата вывода задачи в переменную для последующего использования в условиях `when` или отладке.

**Основные категории ошибок:**
- **Синтаксические:** нарушение структуры YAML или правил Jinja2 (незакрытые кавычки, отступы, опечатки в фигурных скобках).
- **Логические:** ошибки в условиях `when`, неправильное использование фильтров, неверный порядок выполнения задач, нарушение идемпотентности.
- **Инфраструктурные:** проблемы SSH-соединения, таймауты, отсутствие Python-зависимостей на managed node, ошибки прав доступа (sudo/become).
- **Среда исполнения:** несоответствие версий коллекций, ansible-core или конфликты интерпретаторов Python.
- **Данные:** неверные типы переменных, проблемы с приоритетом переменных, ошибки в шаблонах Jinja2.

**Примечание:** подробное описание инструментов отладки (флаги CLI, модуль `ansible.builtin.debug`, интерактивный отладчик) находится в разделе [Точки останова и отладка (Debugger)](../PlaybookStructure/advanced.md#сценарий-6-точки-останова-и-отладка-debugger). Данный файл содержит практические сценарии устранения проблем и работу над ошибками.

## Базовые концепции

### Архитектура отладки

Процесс отладки в Ansible строится на трех уровнях:
1. **Статический анализ** — проверка синтаксиса без запуска (`ansible-playbook --syntax-check`, `ansible-lint`).
2. **Диагностика выполнения** — сбор фактов, просмотр переменных, проверка связности (`ansible-inventory`, `ansible -m setup`, `-vvvv`).
3. **Интерактивный анализ** — пошаговое выполнение (`--step`), интерактивный отладчик (`debugger: on_failed`), dry-run (`--check --diff`).

### Предварительные требования (Prerequisites)

| Компонент | Минимальная версия | Проверка |
|---|---|---|
| ansible-core | 2.15+ (рекомендуется ≥ 2.20) | `ansible --version` |
| Python (Control Node) | 3.11+ | `python3 --version` |
| SSH-доступ | Протестирован | `ansible all -m ping` |
| Права `sudo` | Настроен `NOPASSWD` | `ansible all -m command -a "sudo whoami"` |
| jmespath (опционально) | Любая | `pip3 install jmespath` |

**Проверка зависимостей (однострочник):**

```bash
# Проверка Ansible и Python
ansible --version && python3 --version

# Проверка доступности хостов
ansible all -m ping --timeout=10

# Проверка версий коллекций
ansible-galaxy collection list 2>/dev/null | grep -E "community\.|ansible\."
```

### Инструменты диагностики

| Инструмент / Метод | Описание | Команда / Параметр |
|---|---|---|
| **Уровни детализации** | Вывод отладочной информации модулей и SSH. `-vvvv` включает логирование соединений. | `-v`, `-vv`, `-vvv`, `-vvvv` |
| **Переменные окружения** | Глобальное включение отладки или смена вывода для читаемости. | `ANSIBLE_DEBUG=1`, `ANSIBLE_STDOUT_CALLBACK=yaml` |
| **Статический анализ** | Проверка синтаксиса, типичных ошибок и антипаттернов без запуска кода. | `ansible-lint`, `ansible-playbook --syntax-check` |
| **Интерактивный отладчик** | Остановка выполнения при ошибке для инспекции переменных и выполнения команд. | `debugger: on_failed` (в плейбуке или задаче) |
| **Анализ инвентаря** | Визуализация иерархии групп и переменных для отладки приоритетов. | `ansible-inventory --graph --vars` |
| **Модуль `ansible.builtin.debug`** | Вывод значений переменных или произвольных сообщений. | `ansible.builtin.debug: var=my_var` |
| **Callback-плагины** | Дополнительный вывод (JSON, YAML, временные метки) для CI/CD и логирования. | `ANSIBLE_STDOUT_CALLBACK=yaml` или `callback_whitelist` в `ansible.cfg` |
| **Анализ фактов** | Сбор и фильтрация фактов для диагностики окружения. | `ansible <host> -m setup -a "filter=ansible_os_family"` |

### Алгоритм изоляции проблемы

1.  **Сужение области поиска**: используйте `--limit <hostname>` для запуска на одном хосте, где возникла проблема.
2.  **Пошаговое выполнение**: флаг `--step` позволяет подтверждать каждую задачу вручную, что помогает локализовать момент сбоя.
3.  **Проверка изменений (Dry Run)**: `--check` в сочетании с `--diff` показывает, какие именно строки в файлах были бы изменены, не применяя их.
4.  **Запуск с определенной задачи**: `--start-at-task="Name"` экономит время при отладке длинных плейбуков, пропуская уже выполненные шаги.
5.  **Просмотр отчета**: форматирование результата в JSON для анализа в CI/CD: `ansible-playbook site.yml -vvv --timeout=30 2>&1 | tee ansible_debug.log`.

## Практические сценарии

### Сценарий 1: Ошибка синтаксиса YAML (кавычки в выражениях Jinja2)

**Симптом:** выполнение прерывается ошибкой `Syntax Error while loading YAML`.

**Причина:** в YAML значения, начинающиеся с `{{`, должны быть заключены в кавычки, иначе парсер считает это началом словаря.

**Диагностика:**
```bash
# Статическая проверка синтаксиса (без выполнения)
ansible-playbook site.yml --syntax-check
# → site.yml:3: ERROR! Syntax Error while loading YAML
```

**Решение:**
- **Неправильно:**
```yaml
- name: Копирование конфигурации
  ansible.builtin.copy:
    dest: /etc/app/config.ini
    content: base_path={{ base_path }}/data
```

- **Правильно:**
```yaml
- name: Копирование конфигурации
  ansible.builtin.copy:
    dest: /etc/app/config.ini
    content: "base_path={{ base_path }}/data"
```

**Валидация:**
```bash
# После исправления проверяем синтаксис
ansible-playbook site.yml --syntax-check
# → site.yml: OK
```

### Сценарий 2: Конфликт приоритетов переменных

**Симптом:** Ansible использует неверное значение переменной, пропуская те, что указаны в `group_vars/all`.

**Причина:** переменная переопределена в более приоритетном месте (например, `host_vars` или передана через `-e`).

**Диагностика:**
```bash
# Просмотр итоговых переменных для хоста (все источники)
ansible-inventory --host web1

# Просмотр переменных с указанием источника
ansible-inventory --host web1 -vvv 2>&1 | grep "variable_module"

# Просмотр всех групп хоста
ansible-inventory --graph web1
```

**Решение:** используйте команду для проверки итогового состояния:
```bash
ansible-inventory --host <hostname> # → вывод всех переменных, примененных к хосту
```

**Валидация:**
```bash
# Проверка приоритетов переменных (от низшего к высшему):
# 1. role defaults (roles/x/defaults/main.yml)
# 2. inventory vars
# 3. play vars
# 4. role vars
# 5. include vars
# 6. set_facts / registered vars
# 7. extra vars (-e)
#
# Убедитесь, что переменная не переопределена на более высоком уровне
ansible-inventory --host web1 | grep my_var
# → "my_var": "expected_value"
```

### Сценарий 3: Ошибка SSH через Jump Host

**Симптом:** `Failed to connect to the host via ssh: Host key verification failed`.

**Причина:** при использовании цепочки подключений ключи промежуточного хоста не проверены или не проброшены.

**Диагностика:**
```bash
# Проверка SSH-соединения напрямую
ssh -o ProxyJump=user@jump-host:22 user@target-host echo "OK"

# Проверка доступности порта 22
nc -zv target-host 22

# Просмотр логов SSH (уровень -vvvv)
ansible web1 -m ping -vvvv 2>&1 | grep -A5 "SSH"
```

**Решение:** используйте `ProxyJump` в `ansible.cfg` или SSH-конфигурации.
```ini
[ssh_connection]
ssh_args = -o ProxyJump=user@jump-host:22 -o StrictHostKeyChecking=accept-new
```

**Валидация:**
```bash
# После изменения ansible.cfg проверяем соединение
ansible web1 -m ping
# → web1 | SUCCESS => {
#     "changed": false,
#     "ping": "pong"
# }
```

### Сценарий 4: Ошибка типов данных (NoneType / Undefined)

**Симптом:** `fatal: ... => {'msg': "The task includes an option with an undefined variable..."}`.

**Причина:** переменная не определена в инвентаре или её значение пустое (YAML трактует пустоту как `None`).

**Диагностика:**
```bash
# Проверка переменной через отладчик
ansible web1 -m debug -a "var=my_var"

# Включение отладки переменных в плейбуке
ansible-playbook site.yml -vvv 2>&1 | grep "my_var"
```

**Решение:** используйте фильтр `default` или проверяйте наличие ключей в словарях.
```yaml
# Безопасное обращение к вложенным структурам
result: "{{ my_dict.get('sub_key', 'default_value') }}"

# Использование значения по умолчанию для фильтров
items: "{{ my_list | default([]) | select('defined') | list }}"

# Проверка существования переменной перед использованием
- name: Проверка переменной
  ansible.builtin.debug:
    msg: "Значение: {{ my_var | default('НЕ ОПРЕДЕЛЕНА') }}"
  when: my_var is defined
```

**Валидация:**
```bash
# Проверка через инвентарь
ansible-inventory --host web1 | grep my_var
# → "my_var": "some_value"  (или отсутствует, если используется default)

# Проверка через ad-hoc
ansible web1 -m debug -a "var=my_var | default('НЕ ОПРЕДЕЛЕНА')"
```

### Сценарий 5: Ошибки автоматического преобразования типов

**Симптом:** в конфигурационный файл записывается `True` вместо `yes`, что ломает парсеры стороннего ПО.

**Причина:** Ansible/YAML автоматически конвертирует `yes`, `no`, `true`, `false` в булевы значения.

**Диагностика:**
```bash
# Проверка типа переменной в шаблоне
ansible web1 -m debug -a "var=config_option | type_debug"
# → "bool"  (ожидается "str")
```

**Решение:** принудительно используйте строковый тип.
```yaml
config_option: "yes" # Кавычки гарантируют строковый тип

# Проверка типа в плейбуке
- name: Проверка типа переменной
  ansible.builtin.debug:
    msg: "Тип: {{ config_option | type_debug }}, Значение: {{ config_option }}"
```

**Валидация:**
```bash
# После исправления проверяем результат
ansible web1 -m debug -a "var=config_option | type_debug"
# → "str"

# Проверка записанного файла
ansible web1 -m command -a "grep 'config_option' /etc/app/config.ini"
# → config_option=yes
```

### Сценарий 6: Проблемы сетевой связности (UNREACHABLE)

**Симптом:** статус `UNREACHABLE` для части хостов.

**Причина:** опечатка в IP, закрытый порт 22, блокировка firewall или проблемы с `ControlPersist` в SSH.

**Диагностика:**
```bash
# Проверка через ad-hoc
ansible all -m ping --limit <hostname>

# Проверка порта
nc -zv <hostname> 22

# Проверка SSH вручную
ssh -o ConnectTimeout=5 user@<hostname> echo "OK"

# Просмотр полного лога SSH
ansible <hostname> -m ping -vvvv 2>&1 | tee /tmp/ssh_debug.log
```

**Решение:**
1. Проверка через ad-hoc: `ansible all -m ping --limit <hostname>`.
2. Если ping проходит, но плейбук падает — проверьте права `become` или таймауты SSH в `ansible.cfg`.
3. Настройка ControlPersist для ускорения повторных подключений:
```ini
[ssh_connection]
pipelining = True
control_path_dir = /tmp/.ansible-cp
```

**Валидация:**
```bash
# После исправления проверяем все хосты
ansible all -m ping
# → host1 | SUCCESS => { "ping": "pong" }
# → host2 | SUCCESS => { "ping": "pong" }
```

### Сценарий 7: Обработчики (Handlers) не запускаются

**Симптом:** задача вернула `changed`, но уведомленный обработчик не выполнился.

**Причина:**
1. Плейбук упал до завершения `play`. По умолчанию обработчики запускаются только в конце успешного прогона.
2. Несоответствие имен в `notify` и `handlers` (регистр, лишние пробелы).
3. Обработчик уже был вызван ранее в том же play (обработчики вызываются только один раз).

**Диагностика:**
```bash
# Проверка зарегистрированных обработчиков
ansible-playbook site.yml -vvv 2>&1 | grep -i "handler"

# Проверка совпадения имен notify и handlers
grep -n "notify:" site.yml
grep -n "handlers:" site.yml -A 20
```

**Решение:** используйте `force_handlers: true` в плейбуке для запуска обработчиков даже при ошибках в других задачах.
```yaml
- hosts: all
  force_handlers: true
  tasks:
    - name: Update config
      ansible.builtin.template:
        src: config.j2
        dest: /etc/app.conf
      notify: Restart App

  handlers:
    - name: Restart App
      ansible.builtin.systemd:
        name: app
        state: restarted
```

**Валидация:**
```bash
# Проверка сработавших обработчиков
ansible-playbook site.yml --list-handlers
# → handlers:
#   - Restart App

# Проверка через debug
ansible-playbook site.yml -vvv 2>&1 | grep -A2 "Running handler"
```

### Сценарий 8: Ошибка интерпретатора Python (Discovery)

**Симптом:** `/usr/bin/python: not found` или ошибки импорта модулей, которые точно установлены.

**Причина:** Ansible не смог автоматически определить правильный путь к Python или выбрал Python 2 вместо Python 3 на старых системах.

**Диагностика:**
```bash
# Проверка доступных интерпретаторов
which python3 python2 python

# Проверка версии Python
python3 --version

# Проверка, какой Python использует Ansible
ansible web1 -m ping -vvv 2>&1 | grep "python"

# Проверка факта python version
ansible web1 -m setup -a "filter=ansible_python_version"
```

**Решение:** явно укажите интерпретатор в инвентаре для конкретного хоста или группы.
```ini
[all:vars]
ansible_python_interpreter=/usr/bin/python3

# Или для конкретного хоста
[centos7:vars]
ansible_python_interpreter=/usr/bin/python3
```

**Валидация:**
```bash
# Проверка интерпретатора
ansible web1 -m setup -a "filter=ansible_python_version"
# → web1 | SUCCESS => {
#     "ansible_python_version": "3.10.12"
# }

# Проверка модуля
ansible web1 -m ping
# → web1 | SUCCESS => { "changed": false, "ping": "pong" }
```

### Сценарий 9: Проблемы с Ansible Vault (Missing Password)

**Симптом:** `Attempting to decrypt but no vault secrets found` или `Decryption failed`.

**Причина:** не указан пароль для Vault, либо используется неверный Vault ID при работе с несколькими паролями.

**Диагностика:**
```bash
# Проверка зашифрованных файлов
grep -l "ANSIBLE_VAULT" *.yml *.yaml group_vars/* host_vars/*

# Проверка Vault ID в переменных
ansible-playbook site.yml -vvv 2>&1 | grep "vault"

# Попытка прочитать файл без пароля
ansible-vault view secrets.yml 2>&1 | head -5
```

**Решение:**
```bash
# Проверка с указанием конкретного ID
ansible-playbook site.yml --vault-id prod@.vault_pass_prod --vault-id dev@.vault_pass_dev

# Использование Vault Password File
ansible-playbook site.yml --vault-password-file .vault_pass

# Просмотр зашифрованного содержимого
ansible-vault view secrets.yml --vault-id prod@prompt
```

**Валидация:**
```bash
# Проверка что Vault работает
ansible-vault encrypt_string --vault-id prod@prompt 'test_value' --name 'test_var'
# → test_var: !vault |
#   $ANSIBLE_VAULT;1.1;AES256
#   ...

# Дешифровка
ansible-vault decrypt secrets.yml --vault-id prod@prompt
```

### Сценарий 10: Ошибки доступа при повышении привилегий (Become)

**Симптом:** `Timeout (12s) waiting for privilege escalation prompt`.

**Причина:** `sudo` требует пароль, но Ansible не настроен на его ввод, либо включен `requiretty` в `/etc/sudoers`.

**Диагностика:**
```bash
# Проверка настроек become
ansible web1 -m command -a "sudo whoami" --become --ask-become-pass

# Проверка sudoers
ansible web1 -m command -a "cat /etc/sudoers.d/*" --become

# Просмотр логов become
ansible web1 -m ping -vvv --become 2>&1 | grep -A5 "become"
```

**Решение:**
1. Запуск с флагом `-K` (`--ask-become-pass`).
2. Проверка настроек в `ansible.cfg`:
```ini
[privilege_escalation]
become_method = sudo
become_ask_pass = False # Если настроен NOPASSWD в sudoers
```

3. Проверка конфигурации sudoers:
```bash
# Проверка наличия requiretty
ansible web1 -m shell -a "grep -r requiretty /etc/sudoers*"
```

**Валидация:**
```bash
# Проверка become
ansible web1 -m command -a "whoami" --become
# → root

# Проверка прав
ansible web1 -m shell -a "id -un" --become
# → root
```

### Сценарий 11: Проблемы с тегами (Tags)

**Симптом:** задачи не выполняются при запуске с определенным тегом или выполняются задачи, которые не должны были запускаться.

**Причина:** неправильное использование тегов, конфликт тегов в `import_*` vs `include_*`, отсутствие тегов на подключаемых задачах.

**Диагностика:**
```bash
# Просмотр всех тегов в плейбуке
ansible-playbook site.yml --list-tags

# Просмотр задач, которые будут выполнены с конкретным тегом
ansible-playbook site.yml --tags "deploy" --list-tasks

# Запуск с несколькими тегами
ansible-playbook site.yml --tags "config,deploy"
```

**Решение:**
```yaml
# Правильно: тег на задаче
- name: Установка пакетов
  ansible.builtin.apt:
    name: nginx
    state: present
  tags: [install, nginx]

# Правильно: исключение тега
- name: Настройка (только при первом запуске)
  ansible.builtin.template:
    src: nginx.conf.j2
    dest: /etc/nginx/nginx.conf
  tags: [config, never]  # never — задача не выполнится без явного указания

# Неправильно: тег на include_tasks (тег не передается внутрь)
- ansible.builtin.include_tasks: deploy.yml
  tags: [deploy]  # Задачи внутри deploy.yml НЕ получат этот тег
```

**Валидация:**
```bash
# Проверка какие задачи запустятся
ansible-playbook site.yml --tags "config" --list-tasks
# → play #1 (all): config tasks:
#   - Configure nginx

# Проверка что теги включены в include
ansible-playbook site.yml --tags "deploy" --list-tasks 2>&1 | grep "deploy"
# → Вывод всех задач из deploy.yml
```

### Сценарий 12: Ошибки при запуске с `--check` (Dry Run)

**Симптом:** `--check` не показывает ожидаемых изменений или показывает ложные срабатывания.

**Причина:** не все модули поддерживают режим проверки. Некоторые модули (`command`, `shell`) всегда возвращают `changed` в режиме `--check`.

**Диагностика:**
```bash
# Проверка модулей, поддерживающих check
ansible-doc -l | head -20

# Запуск с check + diff
ansible-playbook site.yml --check --diff --limit web1

# Просмотр изменений без выполнения
ansible-playbook site.yml --check --diff -vvv
```

**Решение:**
```yaml
# Модуль command не поддерживает check mode
- name: Проверка версии
  ansible.builtin.command: app --version
  register: version
  check_mode: false  # Всегда выполняет команду

# Модуль copy поддерживает check mode корректно
- name: Копирование конфига
  ansible.builtin.copy:
    src: app.conf
    dest: /etc/app/app.conf
    backup: yes
```

**Валидация:**
```bash
# Проверка что check mode работает
ansible-playbook site.yml --check --diff --limit web1
# → Playing web1:
#   - not changed
```

### Сценарий 13: Нарушение идемпотентности

**Симптом:** при повторном запуске плейбук возвращает `changed: true`, хотя система уже находится в желаемом состоянии.

**Причина:** использование императивных модулей (`shell`, `command`) без корректного `changed_when`, или отсутствие проверки состояния в декларативных модулях.

**Диагностика:**
```bash
# Запуск в check mode
ansible-playbook site.yml --check --diff
# → Если видите changed для уже настроенных ресурсов — проблема в идемпотентности

# Проверка конкретной задачи
ansible-playbook site.yml --start-at-task="Настройка Nginx" --check
```

**Решение:** используйте декларативные модули с параметром `state` или корректный `changed_when`.
```yaml
# Плохо: shell без changed_when
- name: Add setting
  ansible.builtin.shell: echo "Setting=true" >> /etc/app.conf

# Хорошо: lineinfile гарантирует идемпотентность
- name: Ensure setting is present
  ansible.builtin.lineinfile:
    path: /etc/app.conf
    line: "Setting=true"
    state: present

# Проверка идемпотентности
- name: Verify idempotency
  ansible.builtin.assert:
    that:
      - not result is changed
    fail_msg: "Задача не идемпотентна"
```

**Валидация:**
```bash
# Второй запуск не должен показывать changed
ansible-playbook site.yml --check --diff 2>&1 | grep -c "changed:"
# → 0 (идемпотентно)
```

### Сценарий 14: Ошибки асинхронных задач (async/poll)

**Симптом:** длительные задачи завершаются таймаутом, или статус фоновой задачи не отслеживается.

**Причина:** недостаточное значение `async` для длительной операции, отсутствие опроса `async_status`, или ошибка в `jid`.

**Диагностика:**
```bash
# Просмотр запущенных фоновых задач
ansible web1 -m async_status -a "jid=<job_id>"

# Проверка результата асинхронной задачи
ansible web1 -m fetch -a "src=/tmp/async_result.txt dest=./ flat=yes"
```

**Решение:** настройте корректные значения `async` и `poll`.
```yaml
- name: Запуск длительной миграции
  ansible.builtin.command: /opt/scripts/migrate.sh
  async: 7200       # Максимум 2 часа
  poll: 0           # Fire-and-forget
  register: migration_job

- name: Ожидание завершения миграции
  ansible.builtin.async_status:
    jid: "{{ migration_job.ansible_job_id }}"
  register: job_result
  until: job_result.finished
  retries: 60
  delay: 30
```

**Валидация:**
```bash
# Проверка статуса задачи
ansible web1 -m async_status -a "jid=<job_id>"
# → {"finished": 1, "rc": 0, "stdout": "Migration complete"}
```

### Сценарий 15: Проблемы с callback-плагинами

**Симптом:** вывод плейбука нечитаем, или данные не поступают в систему мониторинга/логирования.

**Причина:** не настроен `ANSIBLE_STDOUT_CALLBACK`, конфликт callback-плагинов, или ошибка в конфигурации плагина.

**Диагностика:**
```bash
# Проверка активного callback
ansible-config dump | grep stdout_callback

# Проверка доступных callback-плагинов
ls /usr/share/ansible/collections/ansible_collections/ansible/posix/plugins/callback/
```

**Решение:** настройте callback в `ansible.cfg` или через переменные окружения.
```ini
# ansible.cfg
[defaults]
stdout_callback = yaml
# Для CI/CD:
# stdout_callback = json

# Или через переменную окружения
export ANSIBLE_STDOUT_CALLBACK=yaml
```

**Валидация:**
```bash
# Запуск с YAML-выводом
ANSIBLE_STDOUT_CALLBACK=yaml ansible-playbook site.yml --limit web1
# → Структурированный YAML-вывод
```

## Операции и команды

### Таблица команд отладки

| Команда | Назначение | Пример |
|---|---|---|
| `ansible-playbook --syntax-check` | Проверка YAML-синтаксиса | `ansible-playbook site.yml --syntax-check` |
| `ansible-lint` | Статический анализ кода | `ansible-lint site.yml` |
| `ansible-playbook -vvvv` | Максимальная детализация | `ansible-playbook site.yml -vvvv --limit web1` |
| `ansible-playbook --check --diff` | Dry-run с показом изменений | `ansible-playbook site.yml --check --diff` |
| `ansible-playbook --step` | Пошаговое выполнение | `ansible-playbook site.yml --step` |
| `ansible-playbook --start-at-task` | Запуск с конкретной задачи | `ansible-playbook site.yml --start-at-task="Deploy"` |
| `ansible-inventory --graph` | Визуализация инвентаря | `ansible-inventory --graph --vars` |
| `ansible-inventory --host` | Переменные хоста | `ansible-inventory --host web1` |
| `ansible <host> -m setup` | Сбор фактов | `ansible web1 -m setup -a "filter=ansible_os_family*"` |
| `ansible <host> -m debug` | Просмотр переменной | `ansible web1 -m debug -a "var=my_var"` |
| `ansible-playbook --list-tasks` | Просмотр задач без выполнения | `ansible-playbook site.yml --list-tasks` |
| `ansible-playbook --list-tags` | Просмотр тегов | `ansible-playbook site.yml --list-tags` |
| `ansible-playbook --list-hosts` | Просмотр хостов | `ansible-playbook site.yml --list-hosts` |
| `ansible-playbook --list-handlers` | Просмотр обработчиков | `ansible-playbook site.yml --list-handlers` |
| `ANSIBLE_DEBUG=1` | Включение отладки | `ANSIBLE_DEBUG=1 ansible-playbook site.yml` |
| `ANSIBLE_STDOUT_CALLBACK=yaml` | Форматирование вывода | `ANSIBLE_STDOUT_CALLBACK=yaml ansible-playbook site.yml` |

## Диагностика и устранение неисправностей

### Типовые ошибки и их решение

| # | Ошибка | Причина | Решение |
|---|---|---|---|
| 1 | `Syntax Error while loading YAML` | Нарушение структуры YAML, незакрытые кавычки в Jinja2 | Заключите `{{ ... }}` в кавычки, проверьте отступы |
| 2 | `The task includes an option with an undefined variable` | Переменная не определена или имеет неверный тип | Используйте `default()`, проверьте приоритет переменных через `ansible-inventory` |
| 3 | `UNREACHABLE!` | Проблемы с SSH, firewall, опечатка в IP | Проверьте `ansible all -m ping --limit <host>`, `nc -zv <host> 22` |
| 4 | `FAILED! => {"msg": "Failed to connect to the host via ssh"}` | Нет доступа по SSH, неверный ключ | Проверьте `ssh -v deploy@host`, `ansible.cfg` |
| 5 | `Permission denied` / `Missing sudo password` | `become` не настроен, `requiretty` включен | Настройте `NOPASSWD` в sudoers, проверьте `ansible_become` |
| 6 | `Timeout waiting for privilege escalation prompt` | `sudo` требует пароль | Используйте `-K` или настройте `become_ask_pass=False` |
| 7 | `module xyz was not found in module_utils` | Модуль не установлен | `ansible-galaxy collection install <namespace.collection>` |
| 8 | `No such file or directory` при `include_tasks` | Неверный путь к файлу задач | Укажите относительный путь от плейбука или настройте `roles_path` |
| 9 | `Handler 'X' not found` | Обработчик не определен или опечатка в имени | Проверьте `notify` и `handlers`, используйте `--list-handlers` |
| 10 | `--check` показывает ложные изменения | Модули `command`/`shell` не поддерживают check mode | Установите `check_mode: false` или используйте `changed_when` |
| 11 | `Decryption failed` | Неверный пароль Vault или Vault ID | Проверьте `--vault-id` и парольные файлы |
| 12 | `Could not match supplied host pattern` | Группа не определена в инвентаре | `ansible-inventory --list`, проверьте синтаксис inventory |
| 13 | `The field X is not allowed` | Директива на неправильном уровне | `become`, `serial` задаются на уровне Play или Task |
| 14 | `Undefined variable` при `import_tasks` | `import_tasks` видит только статические переменные | Используйте `include_tasks` для динамических данных |
| 15 | `changed: true` при повторном запуске | Нарушение идемпотентности | Используйте декларативные модули, добавьте `changed_when` |

### Диагностика переменных и фактов

```bash
# Просмотр всех переменных хоста
ansible-inventory --host web1

# Просмотр с фильтром
ansible web1 -m debug -a "var=hostvars['web1.example.com']"

# Сбор фактов с фильтром
ansible web1 -m setup -a "filter=ansible_distribution*"

# Проверка типа переменной
ansible web1 -m debug -a "var=config_option | type_debug"
```

### Диагностика выполнения плейбука

```bash
# Просмотр задач без выполнения
ansible-playbook site.yml --list-tasks

# Просмотр тегов
ansible-playbook site.yml --list-tags

# Просмотр обработчиков
ansible-playbook site.yml --list-handlers

# Просмотр хостов
ansible-playbook site.yml --list-hosts
```

## Рекомендации

### Best Practices

1. **Используйте декларативные модули** вместо `shell`/`command` wherever possible. Это гарантирует идемпотентность и поддерживаемость.
2. **Включайте `--check --diff`** перед первым запуском в production. Это позволяет увидеть точные изменения без риска.
3. **Настройте `ansible.cfg`** с разумными таймаутами и `ControlPersist` для ускорения повторных подключений.
4. **Используйте `debugger: on_failed`** только в debug-сборках плейбуков. Удаляйте перед коммитом в репозиторий.
5. **Настраивайте `no_log: true`** для задач с секретами. Это предотвращает утечку данных в логи CI/CD.
6. **Документируйте переменные** в `README.md` роли или в `vars/main.yml` с комментариями.
7. **Используйте `block/rescue/always`** вместо `ignore_errors: true` для осмысленной обработки ошибок.
8. **Проверяйте идемпотентность** через `molecule idempotence` при разработке ролей.
9. **Не смешивайте логику и данные**: выносите значения в `defaults/main.yml` и `vars/`.
10. **Используйте FQCN** (`ansible.builtin.copy` вместо `copy`) для совместимости с разными коллекциями.

### Чек-лист валидации после отладки

| Проверка | Команда | Ожидаемый результат |
|---|---|---|
| Синтаксис YAML | `ansible-playbook site.yml --syntax-check` | `OK` без ошибок |
| Статический анализ | `ansible-lint site.yml` | 0 ошибок (или только info/warn) |
| Связность SSH | `ansible all -m ping` | `pong` для всех хостов |
| Python доступен | `ansible web1 -m setup -a "filter=ansible_python_version"` | Python 3.9+ |
| Become работает | `ansible web1 -m command -a "whoami" --become` | `root` |
| Vault расшифровывается | `ansible-vault view secrets.yml` | Содержимое отображается |
| Теги работают | `ansible-playbook site.yml --tags "test" --list-tasks` | Список задач |
| Дисковое пространство | `ansible all -m shell -a "df -h / | tail -1"` | Свободное место > 1GB |
| Handler запускается | `ansible-playbook site.yml --list-handlers` | Обработчик в списке |
| Идемпотентность | `ansible-playbook site.yml --check --diff` | 0 changed |

## Дополнительная информация

### Смотрите также

- [Отладка плейбуков: Основные инструменты](../PlaybookStructure/advanced.md#сценарий-6-точки-останова-и-отладка-debugger)
- [Официальная документация: Debugging modules](https://docs.ansible.com/ansible/latest/user_guide/playbooks_debugger.html)
- [Ansible Inventory CLI: Справочник](https://docs.ansible.com/ansible/latest/cli/ansible-inventory.html)

### Связанные разделы

- **Тестирование ролей**: автоматизация проверок с использованием Molecule — **[ansible_testing_with_molecule.md](../ansible_testing_with_molecule.md)**.
- **Безопасность**: лучшие практики настройки прав и пользователей — **[ansible_security_best_practices.md](../ansible_security_best_practices.md)**.
- **Структура проекта**: рекомендации по организации файлов — **[example_project_layout.md](example_project_layout.md)**.
- **Общие антипаттерны**: причины логических ошибок и плохие практики — **[ansible_bad_practices.md](../ansible_bad_practices.md)**.
- **Переменные и факты**: глубокое погружение в приоритеты и иерархию — **[variables.md](../PlaybookStructure/variables.md)**.
