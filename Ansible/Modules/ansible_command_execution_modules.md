# Ansible: Модули выполнения команд

## Определения

**Модули выполнения команд** — это группа специализированных императивных инструментов Ansible (преимущественно `ansible.builtin`), предназначенных для запуска произвольных бинарных файлов, командных строк и сценариев на управляемых узлах.

В отличие от декларативных модулей (например, `ansible.builtin.copy`), описывающих *желаемое состояние*, данные модули описывают *конкретные действия*. Они являются «последним средством» (last resort) и признаком «технического долга», так как:
1.  **Не обладают идемпотентностью** по умолчанию (Ansible всегда возвращает `changed: true`, так как не может отследить внутренние изменения).
2.  **Скрывают детали изменений**: Система не знает, что именно произошло внутри команды (какие файлы изменены, какие параметры настроены).
3.  **Несут риски безопасности**: Уязвимы для инъекций команд (**Command Injection**) при неправильной передаче переменных из внешних источников.

### Ключевые термины

- **Императивный модуль** — модуль, который выполняет конкретную команду или скрипт, не проверяя целевое состояние системы.
- **Идемпотентность** — свойство, при котором повторный запуск задачи не изменяет систему, если она уже находится в целевом состоянии. Для модулей команд достигается через параметры `creates`/`removes` и директивы `changed_when`. Подробнее: **[Основные концепции Ansible](../ansible_core_concepts.md#идемпотентность-глубокий-анализ)**.
- **Command Injection** — уязвимость, возникающая при неэкранированной подстановке пользовательских данных в команды оболочки.
- **Bootstrapping** — процесс первоначальной настройки управляемого узла, при котором на нем отсутствует Python и невозможно использовать стандартные модули Ansible.
- **Ad-hoc команда** — одноразовая команда, выполняемая без плейбука через интерфейс CLI (`ansible <hosts> -m <module> -a "<args>"`).

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

### Требования к окружению

Начиная с **ansible-core 2.19**, для работы модулей управления файлами требуется **Python 3.10+** на управляемых узлах. Поддержка Python 2.7 и 3.6 была прекращена в ansible-core 2.17, поддержка Python 3.7 — в ansible-core 2.18.

## Основные концепции

### Сравнение модулей выполнения

| Модуль | Интерпретатор | Ключевые особенности и ограничения |
| :--- | :--- | :--- |
| **`ansible.builtin.command`** | Нет (прямой вызов `exec`) | **Самый безопасный**. Не поддерживает конвейеры (`|`), перенаправления (`>`), подстановку переменных оболочки (`$VAR`) и glob-символы (`*`). Аргументы передаются как есть. |
| **`ansible.builtin.shell`** | `/bin/sh` (по умолчанию) | Полная поддержка возможностей оболочки. Риск Command Injection при использовании переменных без фильтра `quote`. Можно сменить оболочку через параметр `executable`. |
| **`ansible.builtin.raw`** | Нет (транспорт напрямую) | Выполняет команду «как есть» без использования Python на хосте. Незаменим для **Bootstrapping** и управления сетевым оборудованием или IoT-устройствами. |
| **`ansible.builtin.script`** | Оболочка на хосте | Передает локальный скрипт с контрольного узла на хост и запускает его. Автоматически удаляет временный файл после выполнения. Поддерживает `creates` и `removes`. |
| **`ansible.builtin.expect`** | `pexpect` на Python | Автоматизация интерактивных диалогов (вопрос-ответ). Требует установленную Python-библиотеку **pexpect** на целевом хосте. |

### Жизненный цикл выполнения команды

1.  **Подготовка**: Узел управления упаковывает код модуля, его аргументы и зависимости (`module_utils`) в zip-архив.
2.  **Передача**: Архив копируется на управляемый узел через настроенный транспорт (обычно SSH + SFTP/SCP) во временную директорию (по умолчанию `~/.ansible/tmp/`).
3.  **Исполнение**: Код распаковывается и запускается в интерпретаторе Python (или PowerShell для Windows) на целевом узле. Для `command` — прямой системный вызов `exec()`; для `shell` — запуск через `/bin/sh -c` (или альтернативный `executable`).
4.  **Ответ**: Модуль выводит JSON-структуру в `stdout`.
5.  **Очистка**: Временные файлы удаляются автоматически, если выполнение завершилось успешно (и не включен режим отладки `ANSIBLE_KEEP_REMOTE_FILES=1`).

### Руководство по выбору модуля

```text
Нужна идемпотентность?
├── Да → Используйте декларативные модули (file, lineinfile, package, service, etc.)
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
- **`chdir`**: Смена рабочей директории перед выполнением команды. Эквивалент `cd /path && command`.
- **`cmd`**: (Традиционный) Передача команды в виде строки. Требует аккуратного экранирования пробелов и спецсимволов.
- **`argv`**: (Рекомендуется) Передача команды в виде списка строк. Это исключает проблемы с экранированием пробелов и спецсимволов. Несовместим с ключом `cmd`.
- **`stdin`**: Позволяет передать строку данных напрямую в стандартный ввод процесса (аналог `echo "data" | command`).
- **`executable`**: (Только для `shell`) Путь к альтернативному интерпретатору (например, `/bin/bash` для использования массивов или специфичных функций).

### Управление окружением (environment)

Директива `environment` на уровне задачи позволяет задавать переменные окружения, необходимые для работы команды, без использования `export` в `shell`. Подробнее о приоритетах переменных: **[Основные концепции Ansible](../ansible_core_concepts.md#переменные-и-области-видимости-variable-scopes)**.

```yaml
- name: "Запуск сборки с кастомным путем"
  ansible.builtin.command: make all
  environment:
    PATH: "/opt/toolchain/bin:{{ ansible_env.PATH }}"
    LD_LIBRARY_PATH: "/opt/toolchain/lib"
```

### Безопасность: предотвращение Command Injection

При использовании `ansible.builtin.shell` необходимо всегда экранировать переменные, содержимое которых может быть получено извне (факты, пользовательский ввод, ответы API).

- **Небезопасно**: `ansible.builtin.shell: echo {{ user_input }}`
- **Безопасно**: `ansible.builtin.shell: echo {{ user_input | quote }}`
- **Лучшая практика**: Использовать `ansible.builtin.command` с `argv`, так как он не интерпретирует спецсимволы оболочки.

**Дополнительные меры безопасности:**
- Используйте `no_log: true` для команд, содержащих секреты (см. **[Безопасность в Ansible](../ansible_security_best_practices.md)**)
- Валидируйте переменные перед использованием в командах
- Избегайте конкатенации строк для построения команд
- Используйте FQCN для всех модулей

### Переопределение статусов (changed_when, failed_when)

Так как модули команд всегда сообщают об изменениях (`changed: true`), необходимо явно управлять их статусом. Подробнее: **[Основные концепции Ansible](../ansible_core_concepts.md#changed_when-и-failed_when-ручная-настройка-идемпотентности)**.

- **`changed_when: false`**: Для команд, которые только читают информацию (например, `grep` или `ls`).
- **`changed_when: result.rc == 0 and 'Created' in result.stdout`**: Изменение регистрируется только при наличии ключевого слова в выводе.
- **`failed_when`**: Позволяет игнорировать ошибки (например, если `exit code 1` является ожидаемым поведением для `grep`).

**Важно:** `changed_when` и `failed_when` влияют только на **отчётность** (статус задачи в выводе), но не отменяют фактическое выполнение команды. Для настоящей идемпотентности необходимо использовать специализированные модули или параметры `creates`/`removes`.

### Асинхронное выполнение

Для длительных операций используйте `async` для запуска в фоновом режиме. Подробнее: **[Обзор модулей Ansible](ansible_modules_overview.md#асинхронное-выполнение)**.

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

### Обработка ошибок и восстановление

Для критических операций используйте конструкции `block`/`rescue`/`always`. Подробнее: **[Основные концепции Ansible](../ansible_core_concepts.md#обработчики-handlers)** и **[Антипаттерны Ansible](../ansible_bad_practices.md#неправильная-обработка-ошибок-в-блоках)**.

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

Для выполнения команд от имени другого пользователя используйте `become`. Подробнее: **[Основные концепции Ansible](../ansible_core_concepts.md)**.

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

Модули выполнения команд работают на разных платформах, но с отличиями:

**Linux (Debian/Ubuntu, RHEL/CentOS, Alpine):**
- Стандартный вызов через `/bin/sh` или указанный `executable`
- Требуется Python 3.7+ (3.10+ для ansible-core 2.19) для стандартных модулей
- Для минимальных образов (Alpine, Docker) используйте `ansible.builtin.raw` для bootstrap

**Windows:**
- Используйте `ansible.windows.win_command` вместо `ansible.builtin.command`
- Используйте `ansible.windows.win_shell` вместо `ansible.builtin.shell`
- Требуется установка коллекции `ansible.windows`

**Сетевое оборудование (Cisco, Juniper, Arista):**
- Используйте `ansible.netcommon.network_cli` или `ansible.netcommon.httpapi` как connection plugin
- Модули `command` и `shell` работают через network_cli, но предпочитайте специализированные сетевые модули

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

### Начальная настройка (Bootstrapping) через raw

Использование `ansible.builtin.raw` на системах без Python (например, «чистый» Debian или Alpine). Подробнее: **[Основные концепции Ansible](../ansible_core_concepts.md#начальная-загрузка-хостов-bootstrapping)**.

```yaml
- name: "Установка Python на управляемый узел (Debian/Ubuntu)"
  ansible.builtin.raw: "apt-get update && apt-get install -y python3"
  become: true
  changed_when: true
  gather_facts: false # Факты невозможно собрать, пока нет Python

- name: "Установка Python на Alpine Linux"
  ansible.builtin.raw: "apk add python3"
  become: true
  changed_when: true

- name: "Установка Python на CentOS/RHEL 7"
  ansible.builtin.raw: "yum install -y python3"
  become: true
  changed_when: true

- name: "Проверка установленного Python"
  ansible.builtin.raw: python3 --version
  register: python_check
  changed_when: false
```

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

### Проверка здоровья systemd-сервисов

Использование `systemctl is-active` для проверки состояния служб с правильной обработкой кодов возврата.

```yaml
- name: "Проверка состояния Nginx"
  ansible.builtin.command: systemctl is-active nginx
  register: nginx_status
  changed_when: false
  failed_when: nginx_status.rc not in [0, 3]  # 0=active, 3=inactive

- name: "Перезапуск только при остановленном сервисе"
  ansible.builtin.service:
    name: nginx
    state: started
  when: nginx_status.rc == 3
```

### Управление правилами iptables/nft

Добавление правил брандмауэра с проверкой их существования.

```yaml
- name: "Проверка существования правила iptables"
  ansible.builtin.command: iptables -C INPUT -p tcp --dport 22 -j ACCEPT
  register: iptables_rule
  changed_when: false
  failed_when: iptables_rule.rc not in [0, 1]

- name: "Добавление правила iptables"
  ansible.builtin.command: iptables -A INPUT -p tcp --dport 22 -j ACCEPT
  when: iptables_rule.rc == 1
  register: iptables_add
  changed_when: iptables_add.rc == 0

- name: "Сохранение правил iptables"
  ansible.builtin.command: iptables-save > /etc/iptables/rules.v4
  when: iptables_add.changed
```

### Настройка параметров ядра через sysctl

Проверка и применение параметров ядра без замены всего файла.

```yaml
- name: "Проверка текущего значения параметра ядра"
  ansible.builtin.command: sysctl -n net.ipv4.ip_forward
  register: ip_forward_current
  changed_when: false

- name: "Применение параметра sysctl если отличается"
  ansible.builtin.command: sysctl -w net.ipv4.ip_forward=1
  when: ip_forward_current.stdout | trim != '1'
  register: sysctl_result
  changed_when: "'net.ipv4.ip_forward = 1' in sysctl_result.stdout"

- name: "Постоянное сохранение параметра"
  ansible.builtin.lineinfile:
    path: /etc/sysctl.conf
    regexp: '^net.ipv4.ip_forward'
    line: 'net.ipv4.ip_forward=1'
    state: present
  when: sysctl_result.changed
```

### Управление cron-задачами

Безопасное добавление и удаление записей в cron.

```yaml
- name: "Проверка существования задачи в cron"
  ansible.builtin.command: crontab -l | grep -F "cleanup_cache.sh"
  register: cron_check
  changed_when: false
  failed_when: false

- name: "Добавление задачи очистки кеша"
  ansible.builtin.cron:
    name: "Очистка кеша приложения"
    minute: "0"
    hour: "2"
    job: "/usr/local/bin/cleanup_cache.sh >> /var/log/cleanup.log 2>&1"
  when: cron_check.rc != 0
```

### Анализ логов и диагностика

Поиск ошибок в логах и сбор диагностической информации.

```yaml
- name: "Поиск ошибок в логах Nginx"
  ansible.builtin.shell: grep -c "error" /var/log/nginx/error.log
  register: error_count
  changed_when: false
  failed_when: false

- name: "Вывод количества ошибок"
  ansible.builtin.debug:
    msg: "Найдено ошибок в логах Nginx: {{ error_count.stdout }}"
  when: error_count.stdout | int > 0

- name: "Сбор диагностической информации о системе"
  ansible.builtin.command: dmesg | tail -50
  register: dmesg_output
  changed_when: false

- name: "Сохранение диагностики в файл"
  ansible.builtin.copy:
    content: "{{ dmesg_output.stdout }}"
    dest: "/var/log/ansible/diag_{{ ansible_date_time.date }}_{{ inventory_hostname }}.log"
    mode: '0640'
  when: dmesg_output.stdout | length > 0
```

### Пакетное выполнение команд с throttle

Ограничение параллелизма при массовом выполнении задач.

```yaml
- name: "Пакетный запуск задач с ограничением параллелизма"
  ansible.builtin.command: /opt/app/process.sh {{ item }}
  loop: "{{ large_list_of_items }}"
  async: 600
  poll: 0
  throttle: 10  # Максимум 10 параллельных задач
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

### Цепочка задач с зависимостями

Полный цикл деплоя приложения с откатом при ошибке.

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

Использование Vault для защиты чувствительных данных в командах.

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

Использование `setup` для сбора фактов и последующего выполнения команд на основе типа ОС.

```yaml
- name: "Сбор фактов о системе"
  ansible.builtin.setup:
    register: setup_facts

- name: "Настройка на основе типа ОС"
  ansible.builtin.command: "{{ 'systemctl' if setup_facts.ansible_os_family == 'Debian' else 'service' }} nginx restart"
  become: yes
  when: setup_facts.ansible_distribution in ['Ubuntu', 'Debian']
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

## Операции и команды

### Работа с документацией модулей (`ansible-doc`)

Утилита `ansible-doc` позволяет получать справку без доступа к интернету.

```bash
# Просмотр документации модуля command
ansible-doc ansible.builtin.command

# Просмотр в формате man-page
ansible-doc --man ansible.builtin.shell

# Список всех модулей выполнения
ansible-doc --list | grep -E "command|shell|raw|script|expect"

# Вывод краткого шаблона (snippet) для вставки в плейбук
ansible-doc -s ansible.builtin.command
```

### Управление коллекциями (`ansible-galaxy`)

Некоторые модули (например, `ansible.windows.win_command`) требуют установки дополнительных коллекций:

```bash
# Установка коллекции Windows
ansible-galaxy collection install ansible.windows

# Установка community.general для дополнительных модулей
ansible-galaxy collection install community.general

# Обновление всех коллекций
ansible-galaxy collection install --upgrade

# Просмотр установленных коллекций
ansible-galaxy collection list
```

### Ad-hoc команды

Выполнение команд напрямую без плейбука:

```bash
# Выполнение команды на всех хостах
ansible all -m ansible.builtin.command -a "uptime"

# Выполнение с привилегиями
ansible all -m ansible.builtin.shell -a "systemctl status nginx" --become

# Выполнение с передачей переменной окружения
ansible all -m ansible.builtin.command -a "env" -e "MY_VAR=value"

# Выполнение команды на конкретном хосте с ограничением по фактам
ansible db_servers -m ansible.builtin.command -a "systemctl is-active postgresql"

# Проверка доступности Python на хостах
ansible all -m ansible.builtin.command -a "python3 --version"
```

### Диагностика выполнения

```bash
# Запуск с максимальной детализацией для отладки
ansible-playbook playbook.yml -vvvv

# Проверка доступности модуля на целевом хосте
ansible all -m ansible.builtin.command -a "python3 --version"

# Проверка синтаксиса модуля без выполнения
ansible-doc ansible.builtin.command

# Проверка подключения к хосту
ansible all -m ansible.builtin.ping
```

## Устранение неполадок

### Типичные ошибки и их решение

| Ошибка | Причина | Решение |
|--------|---------|---------|
| `Permission denied` | Недостаточно прав на управляемом узле | Используйте `become: yes` или проверьте права |
| `No such file or directory` | Несуществующий путь | Проверьте путь или используйте `creates` для идемпотентности |
| `Module failed` | Невалидная команда | Проверьте синтаксис команды |
| `Timeout` | Команда выполняется слишком долго | Увеличьте `async` таймаут |
| `Connection closed` | Разрыв соединения | Проверьте стабильность сети |
| `python3: command not found` | На хосте нет Python | Используйте `ansible.builtin.raw` для bootstrap |
| `pexpect not found` | Нет библиотеки для `expect` | Установите `python3-pexpect` на целевой хост |
| `Checksum mismatch` | Изменение файла после рендеринга | Проверьте конфликты параллельного доступа или внешние изменения |
| `Module failed with unrecognized argument` | Неверный параметр модуля | Проверьте YAML-синтаксис и типы данных параметров |
| `FIPS-403: md5 unavailable` | MD5 запрещен на FIPS-системе | Используйте `checksum_algorithm: sha256` или выше |

### Диагностические команды

```bash
# Проверка фактов о хосте
ansible <host> -m ansible.builtin.setup

# Проверка доступности Python
ansible <host> -m ansible.builtin.command -a "which python3"

# Проверка доступности оболочки
ansible <host> -m ansible.builtin.command -a "echo $SHELL"

# Тест подключения
ansible <host> -m ansible.builtin.ping

# Проверка установленных пакетов
ansible <host> -m ansible.builtin.command -a "dpkg -l | grep -i nginx"
```

### Режим отладки

```bash
# Проверка плейбука без выполнения
ansible-playbook playbook.yml --check

# Проверка с отображением изменений
ansible-playbook playbook.yml --diff

# Детальная отладка (5 уровней)
ansible-playbook playbook.yml -vvvv

# Сохранение временных файлов для анализа
export ANSIBLE_KEEP_REMOTE_FILES=1
ansible-playbook playbook.yml -vvv
```

### Паттерны обработки ошибок

```yaml
- name: "Выполнение с повторными попытками"
  ansible.builtin.command: /opt/app/retry_operation.sh
  register: retry_result
  until: retry_result.rc == 0
  retries: 3
  delay: 10
  changed_when: retry_result.rc == 0

- name: "Выполнение с обработкой ошибок"
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

## Рекомендации

### Выбор правильного модуля

При выборе модуля следуйте принципу «декларативность вместо императивности»:
- Для управления состоянием файла → `ansible.builtin.file`
- Для сложных шаблонов → `ansible.builtin.template`
- Для простых замен строк → `ansible.builtin.lineinfile`
- Для массового поиска/замены по regex → `ansible.builtin.replace` или `ansible.builtin.lineinfile`
- Для синхронизации больших объемов → `ansible.posix.synchronize` (rsync)
- Для распаковки архивов → `ansible.builtin.unarchive`
- Для управления пакетами → `ansible.builtin.apt`, `ansible.builtin.dnf`, `ansible.builtin.yum`
- Для управления службами → `ansible.builtin.service`, `ansible.builtin.systemd`
- **Избегайте**: `command`/`shell` для файловых операций (нарушают идемпотентность)

### Валидация и безопасность

- Всегда используйте фильтр `quote` для переменных в `ansible.builtin.shell`
- Применяйте `no_log: true` для команд, содержащих секреты
- Валидируйте переменные перед использованием в командах
- Избегайте конкатенации строк для построения команд
- Используйте FQCN для всех модулей
- Для критических операций используйте `block`/`rescue`/`always` вместо `ignore_errors: true`

### Идемпотентность

- Используйте `creates` и `removes` для предотвращения повторного выполнения
- Явно указывайте `changed_when: false` для команд только для чтения
- Регистрируйте результаты и анализируйте `stdout`/`stderr` для определения изменений
- Избегайте `ignore_errors: true` для скрытия реальных проблем
- Тестируйте идемпотентность через `ansible-playbook --check` и Molecule (сценарий `idempotence`)

### Производительность

- Для длительных операций используйте `async` и `poll: 0` для параллельного выполнения
- Используйте `retries` и `delay` для операций, требующих ожидания
- Избегайте выполнения команд в цикле без необходимости — используйте `loop` с `strategy: free` для параллелизма
- Используйте `throttle` для ограничения параллелизма при массовых операциях
- Для пакетных операций передавайте списки в специализированные модули вместо циклов с `command`

**Параллельное выполнение:**
```yaml
- name: "Параллельный запуск на нескольких хостах"
  ansible.builtin.command: /opt/app/process.sh {{ item }}
  loop: "{{ large_list_of_items }}"
  async: 600
  poll: 0
  throttle: 10
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

**Кэширование результатов:**
```yaml
- name: "Проверка с кэшированием"
  ansible.builtin.command: expensive_operation
  register: cached_result
  cacheable: yes
  changed_when: false
```

## Дополнительная информация

- **[Антипаттерны Ansible](../ansible_bad_practices.md)** — глубокий разбор причин, по которым стоит избегать модулей команд.
- **[Обзор модулей Ansible](ansible_modules_overview.md)** — выбор правильного инструмента для задачи.
- **[Основные концепции Ansible](../ansible_core_concepts.md)** — архитектура и идемпотентность.
- **[Action-плагины](../ansible-action-plugins.md)** — как работают `template`, `copy`, `fetch` на уровне плагинов.
