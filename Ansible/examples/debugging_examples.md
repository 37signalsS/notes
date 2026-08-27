# Примеры отладки типовых проблем в Ansible

## Определения

**Отладка в Ansible** — систематический процесс идентификации и устранения неисправностей в коде автоматизации (плейбуки, роли), конфигурации инвентаря или сетевом взаимодействии.

**Основные категории ошибок:**
- **Синтаксические:** нарушение структуры YAML (YAML Ain't Markup Language) или правил Jinja2 (например, незакрытые кавычки или скобки).
- **Логические:** ошибки в условиях `when`, неправильное использование фильтров, неверный порядок выполнения задач или проблемы идемпотентности.
- **Инфраструктурные:** проблемы SSH (Secure Shell) соединения, таймауты, отсутствие Python-зависимостей на целевых хостах или ошибки прав доступа (sudo/become).
- **Среда исполнения:** несоответствие версий коллекций, ядра Ansible или конфликты интерпретаторов Python.

**Примечание:** подробное описание инструментов отладки (флаги CLI, модуль `debug`, интерактивный отладчик) находится в основном разделе **[Отладка плейбуков](../PlaybookStructure/advanced.md#сценарий-3-отладка-плейбуков)**. Данный файл содержит практические сценарии и "работу над ошибками".

## Базовые концепции

### Предварительные требования (Prerequisites)

| Компонент | Минимальная версия | Проверка |
|---|---|---|
| Ansible | 2.15+ (рекомендуется ≥ 10.x) | `ansible --version` |
| Python | 3.10+ | `python3 --version` |
| SSH-доступ | Протестирован | `ansible all -m ping` |
| Права `sudo` | Настроен `NOPASSWD` | `ansible all -m command -a "sudo whoami"` |

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
| **Переменные окружения** | Глобальное включение отладки или смена вывода для лучшей читаемости. | `ANSIBLE_DEBUG=1`, `ANSIBLE_STDOUT_CALLBACK=yaml` |
| **Статический анализ** | Проверка синтаксиса, типичных ошибок и антипаттернов без запуска кода. | `ansible-lint`, `ansible-playbook --syntax-check` |
| **Интерактивный отладчик** | Остановка выполнения при ошибке для инспекции переменных и выполнения команд. | `debugger: on_failed` (в плейбуке или задаче) |
| **Анализ инвентаря** | Визуализация иерархии групп и переменных для отладки приоритетов. | `ansible-inventory --graph --vars` |
| **Модуль debug** | Вывод значений переменных или произвольных сообщений. | `ansible.builtin.debug: var=my_var` |
| **Callback-плагины** | Дополнительный вывод (JSON, YAML,的时间戳) для CI/CD и логирования. | `ANSIBLE_STDOUT_CALLBACK=yaml` или `callback_whitelist` |

### Алгоритм изоляции проблемы

1.  **Сужение области поиска**: используйте `--limit <hostname>` для запуска на одном хосте, где возникла проблема.
2.  **Пошаговое выполнение**: флаг `--step` позволяет подтверждать каждую задачу вручную, что помогает локализовать момент сбоя.
3.  **Проверка изменений (Dry Run)**: `--check` в сочетании с `--diff` показывает, какие именно строки в файлах были бы изменены, не применяя их.
4.  **Запуск с определенной задачи**: `--start-at-task="Name"` экономит время при отладке длинных плейбуков, пропуская уже выполненные шаги.
5.  **Просмотр отчета**: форматирование результата в JSON для анализа в CI/CD: `ansible-playbook site.yml -vvv --timeout=30 2>&1 | tee ansible_debug.log`.

---

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
    content: "base_path={{ base_path }}/data"
```

- **Правильно:**
```yaml
- name: Копирование конфигурации
  ansible.builtin.copy:
    dest: /etc/app/config.ini
    content: "base_path={{ base_path }}/data"  # Не забудьте кавычки вокруг всей строки
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

**Причина:** опечатка в IP, закрытый порт 22, блокировка Firewall или проблемы с `ControlPersist` в SSH.

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

**Причина:** не все модули поддерживают режим проверки. Некоторые модули (command, shell) всегда возвращают `changed` в режиме `--check`.

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
# →攉ing web1:
#   - воt changed
```

---

## Запуск и структура проекта

### Пример инвентаря (inventory)

**Файл `inventory.ini`:**
```ini
[dev]
web1 ansible_host=10.0.5.20 ansible_user=deploy
web2 ansible_host=10.0.5.21 ansible_user=deploy

[prod]
db1 ansible_host=10.0.5.30 ansible_user=deploy
db2 ansible_host=10.0.5.31 ansible_user=deploy

[dev:vars]
ansible_python_interpreter=/usr/bin/python3
ansible_become=true
```

### Команды запуска отладки

```bash
# Полный вывод отладки
ansible-playbook site.yml -vvvv --limit web1

# Только проверка синтаксиса
ansible-playbook site.yml --syntax-check

# Статический анализ (требуется ansible-lint)
ansible-lint site.yml

# Запуск с определенной задачи
ansible-playbook site.yml --start-at-task="Установка пакетов"

# Пошаговое выполнение
ansible-playbook site.yml --step

# Dry Run с показом различий
ansible-playbook site.yml --check --diff --limit web1

# Отладка интерактивным отладчиком
ansible-playbook site.yml --limit web1  # debugger сработает автоматически при ошибке

# Просмотр переменных хоста
ansible-inventory --host web1

# Просмотр структуры инвентаря
ansible-inventory --graph

# Отладка конкретной переменной
ansible web1 -m debug -a "var=my_var"

# Просмотр зарегистрированных переменных
ansible web1 -m debug -a "var=registered_var.stdout"
```

### Чек-лист валидации после отладки

| Проверка | Команда | Ожидаемый результат |
|---|---|---|
| Синтаксис YAML | `ansible-playbook site.yml --syntax-check` | `OK` без ошибок |
| Синтаксис Jinja2 | `ansible-lint site.yml` | 0 ошибок |
| Связность SSH | `ansible all -m ping` | `pong` для всех хостов |
| Python доступен | `ansible web1 -m setup -a "filter=ansible_python_version"` | Python 3.10+ |
| become работает | `ansible web1 -m command -a "whoami" --become` | `root` |
| Vault расшифровывается | `ansible-vault view secrets.yml` | Содержимое отображается |
| Теги работают | `ansible-playbook site.yml --tags "test" --list-tasks` | Список задач |
| Дисковое пространство | `ansible all -m shell -a "df -h / \| tail -1"` | Свободное место > 1GB |
| Handler запускается | `ansible-playbook site.yml --list-handlers` | Обработчик в списке |

---

## Дополнительная информация

- **Тестирование ролей**: автоматизация проверок с использованием Molecule — **[ansible_testing_with_molecule.md](../ansible_testing_with_molecule.md)**.
- **Безопасность**: лучшие практики настройки прав и пользователей — **[ansible_security_best_practices.md](../ansible_security_best_practices.md)**.
- **Структура проекта**: рекомендации по организации файлов — **[example_project_layout.md](example_project_layout.md)**.
- **Общие антипаттерны**: причины логических ошибок и плохие практики — **[ansible_bad_practices.md](../ansible_bad_practices.md)**.
- **Переменные и факты**: глубокое погружение в приоритеты и иерархию — **[variables.md](../PlaybookStructure/variables.md)**.

## Смотрите также

- [Отладка плейбуков: Основные инструменты](../PlaybookStructure/advanced.md#сценарий-3-отладка-плейбуков)
- [Официальная документация: Debugging modules](https://docs.ansible.com/ansible/latest/user_guide/playbooks_debugger.html)
- [Ansible Inventory CLI: Справочник](https://docs.ansible.com/ansible/latest/cli/ansible-inventory.html)
