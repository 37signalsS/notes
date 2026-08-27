# Ansible: Модули выполнения команд

## Определения

**Модули выполнения команд** — это группа специализированных императивных инструментов Ansible (преимущественно `ansible.builtin`), предназначенных для запуска произвольных бинарных файлов, командных строк и сценариев на управляемых узлах.

В отличие от декларативных модулей (например, `ansible.builtin.copy`), описывающих *желаемое состояние*, данные модули описывают *конкретные действия*. Они являются «последним средством» (last resort) и признаком «технического долга», так как:
1.  **Не обладают идемпотентностью** по умолчанию (Ansible всегда возвращает `changed: true`, так как не может отследить внутренние изменения).
2.  **Скрывают детали изменений**: Система не знает, что именно произошло внутри команды (какие файлы изменены, какие параметры настроены).
3.  **Несут риски безопасности**: Уязвимы для инъекций команд (**Command Injection**) при неправильной передаче переменных из внешних источников.

### Возвращаемые данные (Return Values)

Все модули команд возвращают стандартный набор данных, доступных через `register`:

| Параметр | Тип | Описание |
|----------|-----|----------|
| `stdout` | string | Стандартный вывод команды |
| `stderr` | string | Стандартный поток ошибок |
| `rc` | integer | Код возврата команды (0 = успех) |
| `cmd` | list | Выполненная команда (в виде списка) |
| `start` | string | Время начала выполнения |
| `end` | string | Время завершения выполнения |
| `delta` | string | Длительность выполнения |
| `changed` | boolean | Были ли произведены изменения |

## Основные концепции

### Сравнение модулей выполнения

| Модуль | Интерпретатор | Ключевые особенности и ограничения |
| :--- | :--- | :--- |
| **`ansible.builtin.command`** | Нет (прямой вызов `exec`) | **Самый безопасный**. Не поддерживает конвейеры (`|`), перенаправления (`>`), подстановку переменных оболочки (`$VAR`) и glob-символы (`*`). Аргументы передаются как есть. |
| **`ansible.builtin.shell`** | `/bin/sh` (по умолчанию) | Полная поддержка возможностей оболочки. Риск Command Injection при использовании переменных без фильтра `quote`. Можно сменить оболочку через параметр `executable`. |
| **`ansible.builtin.raw`** | Нет (транспорт напрямую) | Выполняет команду «как есть» без использования Python на хосте. Незаменим для **Bootstrapping** и управления сетевым оборудованием или IoT-устройствами. |
| **`ansible.builtin.script`** | Оболочка на хосте | Передает локальный скрипт с контрольного узла на хост и запускает его. Автоматически удаляет временный файл после выполнения. Поддерживает `creates` и `removes`. |
| **`ansible.builtin.expect`** | `pexpect` на Python | Автоматизация интерактивных диалогов (вопрос-ответ). Требует установленную Python-библиотеку **`pexpect`** (версия >= 3.3) на целевом хосте. |

### Руководство по выбору модуля

```
Нужна идемпотентность?
├── Да → Используйте декларативные модули (file, lineinfile, package, etc.)
└── Нет → Продолжайте ниже

Это простая команда без спецсимволов?
├── Да → ansible.builtin.command
└── Нет → Нужна оболочка (конвейеры, перенаправления)?
    ├── Да → ansible.builtin.shell
    └── Нет → Это скрипт на контрольном узле?
        ├── Да → ansible.builtin.script
        └── Нет → Нет Python на хосте?
            ├── Да → ansible.builtin.raw
            └── Нет → Интерактивный диалог?
                ├── Да → ansible.builtin.expect
                └── Нет → ansible.builtin.command
```

### Параметры идемпотентности и управления

Для предотвращения повторного выполнения и управления поведением используются параметры:
- **`creates`**: Путь к файлу. Если файл уже существует, команда **не** будет выполнена. Это основной способ обеспечить идемпотентность для команд создания ресурсов.
- **`removes`**: Путь к файлу. Команда выполнится только в том случае, если файл **существует**. Используется для задач очистки.
- **`chdir`**: Смена рабочей директории перед выполнением команды.
- **`argv`**: (Рекомендуется) Передача команды в виде списка строк. Это исключает проблемы с экранированием пробелов и спецсимволов. Несовместим с ключом `cmd`.
- **`stdin`**: Позволяет передать строку данных напрямую в стандартный ввод процесса (аналог `echo "data" | command`).
- **`executable`**: (Только для `shell`) Путь к альтернативному интерпретатору (например, `/bin/bash` для использования массивов или специфичных функций).
- **`removes`**: Путь к файлу. Команда выполнится только если файл существует (обратный `creates`).

### Управление окружением (environment)
Директива `environment` на уровне задачи позволяет задавать переменные окружения, необходимые для работы команды, без использования `export` в `shell`.

```yaml
- name: "Запуск сборки с кастомным путем"
  ansible.builtin.command: make all
  environment:
    PATH: "/opt/toolchain/bin:{{ ansible_env.PATH }}"
    LD_LIBRARY_PATH: "/opt/toolchain/lib"
```

### Безопасность: Предотвращение Command Injection
При использовании `ansible.builtin.shell` необходимо всегда экранировать переменные, содержимое которых может быть получено извне (факты, пользовательский ввод).
- **Небезопасно**: `ansible.builtin.shell: echo {{ user_input }}`
- **Безопасно**: `ansible.builtin.shell: echo {{ user_input | quote }}`
- **Лучшая практика**: Использовать `ansible.builtin.command` с `argv`, так как он не интерпретирует спецсимволы оболочки.

**Дополнительные меры безопасности:**
- Используйте `no_log: true` для команд, содержащих секреты
- Валидируйте переменные перед использованием в командах
- Избегайте конкатенации строк для построения команд

### Переопределение статусов (changed_when, failed_when)

Так как модули команд всегда сообщают об изменениях, необходимо явно управлять их статусом:
- **`changed_when: false`**: Для команд, которые только читают информацию (например, `grep` или `ls`).
- **`changed_when: result.rc == 0 and 'Created' in result.stdout`**: Изменение регистрируется только при наличии ключевого слова в выводе.
- **`failed_when`**: Позволяет игнорировать ошибки (например, если `exit code 1` является ожидаемым поведением для `grep`).

**Расширенные паттерны:**
```yaml
- name: "Проверка是否存在服务"
  ansible.builtin.command: systemctl is-active nginx
  register: nginx_status
  changed_when: false
  failed_when: nginx_status.rc not in [0, 3]  # 0=active, 3=inactive

- name: "Проверка是否已安装 пакета"
  ansible.builtin.command: dpkg -l nginx
  register: dpkg_result
  changed_when: false
  failed_when: dpkg_result.rc not in [0, 1]  # 0=installed, 1=not installed
```

### Обработка ошибок и восстановление

**Паттерны обработки ошибок:**
```yaml
- name: "Запуск команды с обработкой ошибок"
  ansible.builtin.command: /opt/app/deploy.sh
  register: deploy_result
  ignore_errors: yes

- name: "Восстановление при ошибке"
  ansible.builtin.command: /opt/app/rollback.sh
  when: deploy_result.rc != 0

- name: "Логирование ошибки"
  ansible.builtin.debug:
    msg: "Ошибка деплоя: {{ deploy_result.stderr }}"
  when: deploy_result.rc != 0
```

**Использование block/rescue/always:**
```yaml
- block:
    - name: "Критическая операция"
      ansible.builtin.command: /opt/app/critical_operation.sh
      register: critical_result
  
  rescue:
    - name: "Восстановление"
      ansible.builtin.command: /opt/app/recovery.sh
  
  always:
    - name: "Очистка"
      ansible.builtin.command: /opt/app/cleanup.sh
```

### Привилегированный доступ (become)

Для выполнения команд от имени другого пользователя:

```yaml
- name: "Выполнение команды от root"
  ansible.builtin.command: /usr/sbin/useradd newuser
  become: yes
  become_user: root
  become_method: sudo

- name: "Выполнение от имени другого пользователя"
  ansible.builtin.command: whoami
  become: yes
  become_user: deploy
  become_method: su
```

### Асинхронное выполнение

Для длительных операций используйте `async` для запуска в фоновом режиме:

```yaml
- name: "Длительная операция в фоне"
  ansible.builtin.command: /opt/app/long_running_task.sh
  async: 3600  # Таймаут 1 час
  poll: 0      # Не ждать завершения
  register: long_task

- name: "Проверка статуса"
  ansible.builtin.async_status:
    jid: "{{ long_task.ansible_job_id }}"
  register: job_result
  until: job_result.finished
  retries: 60
  delay: 60
```

### Работа с разными оболочками

**Использование bash вместо sh:**
```yaml
- name: "Использование bash-специфичных функций"
  ansible.builtin.shell:
    cmd: |
      if [[ $VAR =~ ^[0-9]+$ ]]; then
        echo "Это число"
      fi
    executable: /bin/bash
  vars:
    VAR: "12345"
```

**Использование zsh или fish:**
```yaml
- name: "Использование zsh"
  ansible.builtin.shell:
    cmd: echo $path
    executable: /bin/zsh
```

### Кросс-платформенные особенности

**Linux vs Windows:**
```yaml
# Linux
- name: "Список файлов (Linux)"
  ansible.builtin.command: ls -la /tmp
  when: ansible_os_family == "Debian" or ansible_os_family == "RedHat"

# Windows (требуется ansible.windows)
- name: "Список файлов (Windows)"
  ansible.windows.win_command: dir C:\temp
  when: ansible_os_family == "Windows"
```

### Отладка и логирование

**Управление уровнем детализации:**
```yaml
- name: "Команда с выводом подробной информации"
  ansible.builtin.command: /opt/app/check.sh
  register: check_result
  verbosity: 1  # Показывать только при -v или выше

- name: "Вывод результата"
  ansible.builtin.debug:
    var: check_result.stdout_lines
  when: check_result.rc != 0
```

**Фильтрация вывода:**
```yaml
- name: "Получение IP-адреса"
  ansible.builtin.command: hostname -I
  register: ip_result
  changed_when: false

- name: "Извлечение первого IP"
  ansible.builtin.set_fact:
    server_ip: "{{ ip_result.stdout | first }}"
```

## Практические сценарии

### Безопасное использование переменных в shell
Всегда используйте фильтр `quote` для защиты от выполнения произвольного кода.

```yaml
- name: "Поиск в файле по пользовательскому запросу"
  ansible.builtin.shell:
    cmd: "grep {{ search_pattern | quote }} /var/log/app.log"
  register: grep_result
  changed_when: false
  failed_when: grep_result.rc > 1 # grep возвращает 1, если ничего не найдено
```

### Использование stdin для инициализации БД
Передача SQL-запроса напрямую в клиент без создания временных файлов на диске.

```yaml
- name: "Создание базы данных"
  ansible.builtin.command:
    cmd: mysql -u root
    stdin: "CREATE DATABASE IF NOT EXISTS app_db CHARACTER SET utf8mb4;"
  register: mysql_res
  changed_when: "'1 row affected' in mysql_res.stdout"
```

### Начальная настройка (Bootstrapping) через raw
Использование `raw` на системах без Python (например, «чистый» Debian).

```yaml
- name: "Установка Python на управляемый узел"
  ansible.builtin.raw: "apt-get update && apt-get install -y python3"
  become: true
  changed_when: true
  gather_facts: false # Факты невозможно собрать, пока нет Python
```

### Современный синтаксис с argv
Избавляет от проблем с пробелами и спецсимволами в аргументах.

```yaml
- name: "Запуск кастомной утилиты с аргументами"
  ansible.builtin.command:
    argv:
      - /usr/local/bin/mytool
      - "--name"
      - "Complex Name With Spaces"
      - "--data"
      - "{{ sensitive_data }}"
    creates: /var/lib/mytool/initialized.lock
```

### Автоматизация интерактивного ввода (expect)
Для команд, которые не поддерживают неинтерактивные флаги. Требует установленного `pexpect`.

```yaml
- name: "Смена пароля системного пользователя"
  ansible.builtin.expect:
    command: passwd myuser
    responses:
      (?i)new password: "{{ user_password }}"
      (?i)retype new password: "{{ user_password }}"
    echo: no
  no_log: true # Критично для защиты паролей в логах
```

### Выполнение скрипта с проверкой состояния
Использование `script` для запуска сложной локальной логики.

```yaml
- name: "Миграция данных через локальный скрипт"
  ansible.builtin.script:
    cmd: scripts/data_migration.py --env prod
    chdir: /tmp
    creates: /var/log/migration_complete.log
```

### Пакетное выполнение команд

**Параллельный запуск на нескольких хостах:**
```yaml
- name: "Обновление пакетов на всех хостах"
  ansible.builtin.command: apt-get update
  become: yes
  async: 300
  poll: 0
  register: update_jobs

- name: "Ожидание завершения на всех хостах"
  ansible.builtin.async_status:
    jid: "{{ update_jobs.ansible_job_id }}"
  register: job_result
  until: job_result.finished
  retries: 30
  delay: 10
```

### Работа с большими объемами вывода

**Построчный вывод:**
```yaml
- name: "Получение списка процессов"
  ansible.builtin.command: ps aux
  register: ps_result
  changed_when: false

- name: "Вывод построчно"
  ansible.builtin.debug:
    msg: "{{ item }}"
  loop: "{{ ps_result.stdout_lines }}"
  when: "'nginx' in item"
```

**Сохранение вывода в файл:**
```yaml
- name: "Сохранение логов"
  ansible.builtin.copy:
    content: "{{ command_result.stdout }}"
    dest: "/var/log/ansible/{{ ansible_date_time.date }}_command.log"
    mode: '0644'
  when: command_result.stdout | length > 0
```

### Условное выполнение на основе вывода

```yaml
- name: "Проверка версии Python"
  ansible.builtin.command: python3 --version
  register: python_version
  changed_when: false
  failed_when: false

- name: "Установка дополнительных пакетов"
  ansible.builtin.command: pip3 install virtualenv
  become: yes
  when: 
    - python_version.rc == 0
    - "'Python 3.8' in python_version.stdout or 'Python 3.9' in python_version.stdout"
```

### Цепочка задач с зависимостями

```yaml
- name: "Деплой приложения"
  block:
    - name: "Остановка сервиса"
      ansible.builtin.command: systemctl stop myapp
      become: yes
      register: stop_result
      changed_when: "'inactive' in stop_result.stdout"

    - name: "Резервное копирование"
      ansible.builtin.command: tar -czf /backup/app_{{ ansible_date_time.epoch }}.tar.gz /opt/app
      become: yes
      when: stop_result.rc == 0

    - name: "Копирование новых файлов"
      ansible.builtin.copy:
        src: /tmp/app_new/
        dest: /opt/app/
        remote_src: yes
      become: yes

    - name: "Запуск миграций"
      ansible.builtin.command: /opt/app/migrate.sh
      become: yes
      become_user: appuser
      register: migrate_result
      changed_when: "'migrated' in migrate_result.stdout"

    - name: "Запуск сервиса"
      ansible.builtin.command: systemctl start myapp
      become: yes
      when: migrate_result.rc == 0

  rescue:
    - name: "Восстановление из бэкапа"
      ansible.builtin.command: tar -xzf /backup/app_latest.tar.gz -C /
      become: yes

    - name: "Запуск сервиса"
      ansible.builtin.command: systemctl start myapp
      become: yes
```

### Безопасная работа с секретами

```yaml
- name: "Использование Vault для паролей"
  ansible.builtin.command: >
    mysql -u root -p{{ vault_mysql_password }}
    -e "CREATE USER 'app'@'localhost' IDENTIFIED BY '{{ vault_app_password }}'"
  no_log: true
  register: user_result
  changed_when: "'Query OK' in user_result.stdout"
  failed_when: "'already exists' not in user_result.stderr and user_result.rc != 0"
```

### Интеграция с другими модулями

```yaml
- name: "Сбор фактов о системе"
  ansible.builtin.setup:
  register: setup_facts

- name: "Настройка на основе типа ОС"
  ansible.builtin.command: "{{ 'systemctl' if setup_facts.ansible_os_family == 'Debian' else 'service' }} nginx restart"
  become: yes
  when: setup_facts.ansible_distribution in ['Ubuntu', 'Debian']
```

## Оптимизация производительности

### Параллельное выполнение

```yaml
- name: "Параллельный запуск на нескольких хостах"
  ansible.builtin.command: /opt/app/process.sh {{ item }}
  loop: "{{ large_list_of_items }}"
  async: 600
  poll: 0
  register: process_results

- name: "Ожидание завершения всех задач"
  ansible.builtin.async_status:
    jid: "{{ item.ansible_job_id }}"
  loop: "{{ process_results.results }}"
  register: async_final
  until: async_final.finished
  retries: 120
  delay: 30
```

### Кэширование результатов

```yaml
- name: "Проверка с кэшированием"
  ansible.builtin.command: expensive_operation
  register: cached_result
  cacheable: yes
  changed_when: false
```

## Обработка ошибок

### Типичные ошибки и их решение

| Ошибка | Причина | Решение |
|--------|---------|---------|
| `Permission denied` | Недостаточно прав | Используйте `become: yes` |
| `No such file or directory` | Файл не существует | Проверьте путь или используйте `creates` |
| `Module failed` | Невалидная команда | Проверьте синтаксис команды |
| `Timeout` | Команда выполняется слишком долго | Увеличьте `async` таймаут |
| `Connection closed` | Разрыв соединения | Проверьте стабильность сети |

### Паттерны обработки ошибок

```yaml
- name: "Выполнение с повторными попытками"
  ansible.builtin.command: /opt/app/retry_operation.sh
  register: retry_result
  until: retry_result.rc == 0
  retries: 3
  delay: 10
  changed_when: retry_result.rc == 0
```

## Дополнительная информация

- **[Антипаттерны Ansible](../ansible_bad_practices.md)** — глубокий разбор причин, по которым стоит избегать модулей команд.
- **[Обзор модулей Ansible](ansible_modules_overview.md)** — выбор правильного инструмента для задачи.
- **[Идемпотентность в Ansible](../../Concepts/idempotency.md)** — теоретические основы декларативного подхода.
- **[Основные концепции Ansible](../ansible_core_concepts.md)** — архитектура и идемпотентность.
- **[Action-плагины](../ansible-action-plugins.md)** — как работают модули команд на уровне плагинов.
- **[Тестирование с Molecule](../ansible_testing_with_molecule.md)** — проверка кода автоматизации.
- **[Официальная документация (builtin)](https://docs.ansible.com/ansible/latest/collections/ansible/builtin/index.html)** — полный список параметров и примеров.
