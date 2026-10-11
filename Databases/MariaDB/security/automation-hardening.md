# Автоматизация hardening MariaDB (Ansible)

**Актуально для:** MariaDB 10.6 / 10.11 / 11.x; ansible-core 2.16+ / коллекция `ansible.mariadb` 6.x

## Определения

**Compliance-as-code** — подход, при котором требования безопасности (CIS, PCI DSS) выражаются в виде кода (Ansible-плейбуки, роли), а не документов. Состояние проверяется автоматически, отклонения обнаруживаются сразу.

**Configuration drift** — расхождение фактической конфигурации от эталонной (например, после ручного `SET GLOBAL` или патча). Детектируется сравнением текущего состояния с желаемым.

**Idempotency** — свойство плейбука: многократный запуск приводит к одному и тому же состоянию без побочных эффектов.

**Check mode (проверочный режим)** — режим Ansible (`--check`), в котором модули предсказывают изменения, не применяя их. Модуль `ansible.mariadb.mariadb_query` **не поддерживает** check mode: SQL выполняется даже при `--check` (см. Устранение неполадок).

**Ansible role** — переиспользуемая структура (tasks, handlers, templates, defaults) для настройки компонента.

**Vault** — механизм шифрования секретов Ansible (`ansible-vault`); хранит пароли и ключи вне plaintext.

**`mariadb_secure_installation`** — интерактивный скрипт закалки; в автоматизации заменяется явными SQL-задачами и модулями коллекции `ansible.mariadb` (см. ниже).

## Основные концепции

### Что автоматизировать

| Область | Что задаётся в коде | Проверка |
| :--- | :--- | :--- |
| Конфигурация | `my.cnf` (template) | `template` + `notify: restart mariadb` |
| Учётные записи | удаление анонимных, `test` | `ansible.mariadb.mariadb_user` / `mariadb_db` |
| Привилегии | роли, `GRANT` | `ansible.mariadb.mariadb_role`, SQL-задачи |
| Политика паролей | `validate_password` / `simple_password_check` | template + `mariadb_password_policy` |
| TLS | сертификаты, `require_secure_transport` | template + задачи |
| Аудит | `server_audit`, блокировка плагина | template |
| Файловые права | datadir, `my.cnf` | `file` module |

### Почему не `mariadb-secure-installation`

Скрипт интерактивен и не идемпотентен. В автоматизации его заменяют явными задачами: удаление анонимных пользователей и `test`-БД — модулями `ansible.mariadb.mariadb_user` и `ansible.mariadb.mariadb_db` (идемпотентны, поддерживают check mode); удаление сетевого root — через `ansible.mariadb.mariadb_query` или `ansible.builtin.command` как fallback.

### Модули коллекции `ansible.mariadb`

MariaDB-специфичные модули живут в коллекции `ansible.mariadb` (не `community.mysql`):

| Модуль | Назначение | Check mode |
| :--- | :--- | :--- |
| `ansible.mariadb.mariadb_query` | Произвольные SQL-запросы | **Нет** — выполняет SQL даже при `--check` |
| `ansible.mariadb.mariadb_user` | Создание/удаление пользователей, привилегии, `tls_requires`, `resource_limits` | Полный |
| `ansible.mariadb.mariadb_db` | Создание/удаление баз данных | Полный |
| `ansible.mariadb.mariadb_role` | Управление ролями | Полный |
| `ansible.mariadb.mariadb_password_policy` | Политика паролей (на MariaDB — только `simple_password_check`) | Полный |
| `ansible.mariadb.mariadb_variables` | Глобальные переменные (`SET GLOBAL`, неперсистентно) | Полный |
| `ansible.mariadb.mariadb_info` | Сбор информации о сервере | Полный |

> **Переименование коллекций.** Коллекция `community.mysql` переименована в `ansible.mysql` (в Ansible 14 — редиректы, в Ansible 17 — удалена). MariaDB-поддержка в `ansible.mysql.mysql_query` будет удалена в версии 6.0 коллекции — для MariaDB используйте `ansible.mariadb.*`. FQCN `community.mysql.mariadb_query` не существовал: универсальный модуль назывался `community.mysql.mysql_query`.

### Связь с существующими ролями

- OS-hardening (пакеты, файрвол, SELinux) — см. [Ansible OS hardening](../../../Ansible/ansible-os-hardening.md) (фреймворк devsec).
- Детектирование дрейфа конфигурации — см. [Configuration drift](../../../Ansible/examples/ansible_configuration_drift.md).
- Установка и первичная настройка — см. [Ansible: установка MySQL/MariaDB](../../../Ansible/examples/mysql_setup.md).
- Данный файл фокусируется на MariaDB-специфичных задачах hardening.

## Предварительные требования

| Компонент | Где | Минимальная версия | Проверка |
| :--- | :--- | :--- | :--- |
| ansible-core | Управляющий узел | 2.16.0+ | `ansible --version` |
| `ansible.mariadb` | Управляющий узел | 6.x | `ansible-galaxy collection list ansible.mariadb` |
| PyMySQL | Целевой хост | 0.9.3+ (см. ограничение по `IF EXISTS`) | `python3 -c "import pymysql; print(pymysql.__version__)"` |
| Python | Целевой хост | 3.x | `python3 --version` |

Установка коллекции:

```bash
ansible-galaxy collection install ansible.mariadb
```

PyMySQL на целевых хостах (пакет зависит от дистрибутива):

```bash
# Debian / Ubuntu
sudo apt-get install python3-pymysql

# RHEL / Rocky / Alma
sudo dnf install python3-PyMySQL
```

Дополнительно: доступ к хостам MariaDB (SSH, sudo), Vault для секретов (`ansible-vault`), репозиторий для хранения плейбуков и снимков конфигурации.

## Практические сценарии

### Сценарий 1: Роль `mariadb_hardening` — структура

```
roles/mariadb_hardening/
├── defaults/main.yml
├── tasks/main.yml
├── tasks/check.yml
├── templates/my.cnf.j2
└── handlers/main.yml
```

### Сценарий 2: Шаблон `my.cnf`

```ini
# templates/my.cnf.j2
[mariadb]
bind-address        = {{ mariadb_bind_address }}
skip-name-resolve   = 1
require_secure_transport = {{ mariadb_require_tls | ternary('ON', 'OFF') }}
tls_version         = TLSv1.2,TLSv1.3

max_user_connections = {{ mariadb_max_user_connections }}
wait_timeout         = {{ mariadb_wait_timeout }}

local-infile      = 0
skip-show-database = 1
symbolic-links    = 0

# Аудит: автозагрузка + блокировка выгрузки (защита от SUPER-пользователя)
plugin_load_add     = server_audit
server_audit        = FORCE_PLUS_PERMANENT
server_audit_events = CONNECT,TABLE
server_audit_logging = ON
server_audit_syslog  = ON
server_audit_file_rotate_size = 1G
server_audit_file_rotations = 30

# Политика паролей (альтернатива — validate_password, см. authentication.md)
plugin_load_add = simple_password_check
simple_password_check_minimal_length = 14

ssl_cert = /etc/mysql/ssl/server-cert.pem
ssl_key  = /etc/mysql/ssl/server-key.pem
```

> **Примечание:** `require_secure_transport` разрешает подключения через unix-сокет (unix-сокет считается secure transport) — приложения на localhost без TLS продолжат работать; TCP-клиенты обязаны использовать TLS.

### Сценарий 3: Задачи hardening

```yaml
# tasks/main.yml
- name: Установить PyMySQL на целевых хостах
  ansible.builtin.package:
    name: "{{ 'python3-pymysql' if ansible_os_family == 'Debian' else 'python3-PyMySQL' }}"
    state: present
  tags: [hardening]

- name: Развернуть конфигурацию
  ansible.builtin.template:
    src: my.cnf.j2
    dest: /etc/mysql/conf.d/hardening.cnf
    owner: root
    group: root
    mode: '0644'
  notify: restart mariadb
  tags: [hardening]

- name: Удалить анонимных пользователей
  ansible.mariadb.mariadb_user:
    name: ''
    host_all: true
    state: absent
    login_user: root
    login_password: "{{ mariadb_root_password }}"
    config_file: ''
  tags: [hardening]

- name: Удалить тестовую БД
  ansible.mariadb.mariadb_db:
    name: test
    state: absent
    login_user: root
    login_password: "{{ mariadb_root_password }}"
    config_file: ''
  tags: [hardening]

- name: Удалить сетевой root
  ansible.mariadb.mariadb_query:
    login_user: root
    login_password: "{{ mariadb_root_password }}"
    config_file: ''
    query: "DELETE FROM mysql.user WHERE User = 'root' AND Host NOT IN ('localhost', '127.0.0.1', '::1');"
  tags: [hardening]

- name: Установить права на datadir
  ansible.builtin.file:
    path: /var/lib/mysql
    owner: mysql
    group: mysql
    mode: '0750'
    recurse: yes
  tags: [hardening]

- name: Установить права на конфиг
  ansible.builtin.file:
    path: /etc/my.cnf
    owner: root
    group: root
    mode: '0644'
  tags: [hardening]
```

**Почему именно так:**

- `mariadb_user` с `host_all: true` — идиоматичный способ удалить анонимных пользователей (аналог `DELETE FROM mysql.user WHERE User = ''`), но идемпотентен и работает в check mode. Нельзя использовать `host_all: true` при создании пользователей.
- `mariadb_db` вместо `DROP DATABASE IF EXISTS test`: DDL через `mariadb_query` с PyMySQL 0.10+ сообщает `changed` даже когда ничего не удалено (см. Устранение неполадок).
- `config_file: ''` — запрет чтения `~/.my.cnf`, иначе существующий `[client]`-секция на хосте может повлиять на подключение.
- Сетевой root удаляется SQL-задачей: `host_all: true` для `root` удалил бы и локальный root — недопустимо.
- `DELETE` (DML) идемпотентен: `changed` сообщается только при `rowcount > 0`.

### Сценарий 4: Политика паролей

```yaml
# Вариант 1: validate_password через template (персистентно) — см. authentication.md
# в my.cnf.j2:
#   plugin_load_add = validate_password
#   validate_password_length = 14
#   validate_password_policy = MEDIUM

# Вариант 2: simple_password_check через модуль (MariaDB-only, SET GLOBAL)
- name: Настроить simple_password_check
  ansible.mariadb.mariadb_password_policy:
    login_user: root
    login_password: "{{ mariadb_root_password }}"
    config_file: ''
    login_unix_socket: "{{ mariadb_socket | default('/run/mysqld/mysqld.sock') }}"
    length: 14
    mixed_case_count: 2
    number_count: 2
    special_char_count: 2
  tags: [hardening]
```

> **Ограничение:** на MariaDB модуль `mariadb_password_policy` управляет только настройками `simple_password_check` и не устанавливает сам плагин — он должен быть загружен (`plugin_load_add = simple_password_check` в `my.cnf`). Для `validate_password` используйте template (Сценарий 2) — модуль его не покрывает.

### Сценарий 5: Handlers

```yaml
# handlers/main.yml
- name: restart mariadb
  ansible.builtin.systemd:
    name: "{{ mariadb_service_name | default('mariadb') }}"
    state: restarted
```

Имя сервиса — `mariadb` в стандартных пакетах; на legacy-установках может быть `mysqld` (задаётся в inventory).

### Сценарий 6: Проверка состояния (compliance check)

```yaml
# tasks/check.yml — проверка без изменения
- name: Проверить отсутствие анонимных пользователей
  ansible.mariadb.mariadb_query:
    login_user: root
    login_password: "{{ mariadb_root_password }}"
    config_file: ''
    query: "SELECT User, Host FROM mysql.user WHERE User = '';"
  register: anon_users
  changed_when: false
  tags: [check]

- name: Анонимные пользователи отсутствуют
  ansible.builtin.assert:
    that:
      - anon_users.query_result[0] | length == 0
    fail_msg: "Обнаружены анонимные пользователи: {{ anon_users.query_result[0] }}"
  tags: [check]

- name: Проверить require_secure_transport
  ansible.mariadb.mariadb_query:
    login_user: root
    login_password: "{{ mariadb_root_password }}"
    config_file: ''
    query: "SHOW VARIABLES LIKE 'require_secure_transport';"
  register: rst
  changed_when: false
  tags: [check]

- name: TLS обязателен
  ansible.builtin.assert:
    that:
      - rst.query_result[0][0].Value == 'ON'
    fail_msg: "require_secure_transport = {{ rst.query_result[0][0].Value }}"
  tags: [check]

- name: Проверить, что аудит активен
  ansible.mariadb.mariadb_query:
    login_user: root
    login_password: "{{ mariadb_root_password }}"
    config_file: ''
    query: "SHOW PLUGINS LIKE 'server_audit';"
  register: audit_plugin
  changed_when: false
  tags: [check]

- name: Плагин server_audit активен
  ansible.builtin.assert:
    that:
      - audit_plugin.query_result[0][0].Status == 'ACTIVE'
    fail_msg: "server_audit не активен: {{ audit_plugin.query_result[0][0] | default('не найден') }}"
  tags: [check]
```

> **Структура возвращаемых значений `mariadb_query`:** `query_result` — список списков (подсписок на каждый запрос) словарей `column: value`; `rowcount` — список с числом затронутых строк на запрос. Поэтому доступ — `query_result[0][0].Value`, а не `row[0].Value`.

### Сценарий 7: Детектирование дрейфа

```yaml
# Снимок привилегий в git (ежедневно через cron/CI)
# Требуется gather_facts: true (используется ansible_date_time)
- name: Сохранить снимок привилегий
  ansible.mariadb.mariadb_query:
    login_user: root
    login_password: "{{ mariadb_root_password }}"
    config_file: ''
    query: "SELECT User, Host, Plugin FROM mysql.user ORDER BY User, Host;"
  register: users_snapshot
  changed_when: false

- name: Записать снимок на узел
  ansible.builtin.copy:
    content: "{{ users_snapshot.query_result | to_nice_json }}"
    dest: "/var/backups/mysql-users-{{ ansible_date_time.date }}.json"

- name: Собрать снимок на управляющий узел
  ansible.builtin.fetch:
    src: "/var/backups/mysql-users-{{ ansible_date_time.date }}.json"
    dest: "backups/{{ inventory_hostname }}/"
    flat: yes
```

Подробнее о детектировании дрейфа: [Configuration drift](../../../Ansible/examples/ansible_configuration_drift.md).

### Сценарий 8: Откат hardening (rollback)

```yaml
# rollback.yml — возврат к эталону перед hardening
- name: Восстановить конфигурацию из бэкапа
  ansible.builtin.copy:
    src: "backups/{{ inventory_hostname }}/my.cnf.before-hardening"
    dest: /etc/mysql/conf.d/hardening.cnf
    owner: root
    group: root
    mode: '0644'
  notify: restart mariadb

- name: Восстановить системную базу mysql
  ansible.builtin.command: >-
    mariadb < /backups/{{ inventory_hostname }}/mysql-before-hardening.sql
  args:
    creates: "/backups/{{ inventory_hostname }}/mysql-before-hardening.sql"
```

Бэкап перед hardening делается один раз:

```bash
# Конфигурация
cp -a /etc/my.cnf /etc/mysql/conf.d/ /backups/$(hostname)/

# Системная база (учётные записи и привилегии)
mariadb-dump mysql > /backups/$(hostname)/mysql-before-hardening.sql
```

## Конфигурации и команды

### Запуск плейбука

```bash
# Применение hardening
ansible-playbook -i inventory mariadb_hardening.yml \
  --ask-vault-pass

# Проверка синтаксиса
ansible-playbook -i inventory mariadb_hardening.yml --syntax-check

# Только compliance-проверки (без изменений)
ansible-playbook -i inventory mariadb_hardening.yml -t check

# Dry-run ТОЛЬКО для не-SQL задач (template, file, systemd)
# ВНИМАНИЕ: mariadb_query выполняет SQL даже в --check — см. Устранение неполадок
ansible-playbook -i inventory mariadb_hardening.yml --check --diff \
  --skip-tags hardening -t check
```

### Vault-файл с секретами

```yaml
# group_vars/mariadb/vault.yml
mariadb_root_password: !vault |
          $ANSIBLE_VAULT;1.1;AES256
          6638643965323633646239613031...
```

```bash
ansible-vault encrypt group_vars/mariadb/vault.yml
# → Encryption successful
```

### Структура inventory

```ini
# inventory
[mariadb]
db01.example.com
db02.example.com
db03.example.com

[mariadb:vars]
mariadb_bind_address = 10.0.5.20
mariadb_require_tls = true
mariadb_max_user_connections = 50
mariadb_wait_timeout = 600
# mariadb_service_name = mariadb   # mysqld на legacy-установках
# mariadb_socket = /run/mysqld/mysqld.sock   # Debian/Ubuntu; /var/lib/mysql/mysql.sock на RHEL/Rocky
```

## Проверка и валидация

### Критерии успешного применения

```bash
# Повторный запуск — идемпотентность
ansible-playbook -i inventory mariadb_hardening.yml --ask-vault-pass
# → ok=NN  changed=0  (второй запуск без изменений)

# Проверка на хосте
mariadb -e "SELECT User, Host FROM mysql.user WHERE User = '';"
# → (пустой результат)
mariadb -e "SHOW VARIABLES LIKE 'require_secure_transport';"
# → ON
mariadb -e "SHOW PLUGINS LIKE 'server_audit';"
# → server_audit | ... | ACTIVE
```

### Проверка окружения

```bash
ansible-galaxy collection list ansible.mariadb
# → ansible.mariadb 6.x
python3 -c "import pymysql; print(pymysql.__version__)"   # на целевом хосте
# → 0.10.x
```

## Устранение неполадок

### SQL-задачи выполняются в проверочном режиме

**Причина:** у `ansible.mariadb.mariadb_query` атрибут `check_mode: support: none` — модуль не умеет предсказывать изменения и выполняет запрос даже при `--check`. `DELETE`/`DROP` в «dry-run» приведут к реальным изменениям.

**Решение:** для dry-run используйте отдельный тег (`-t check` с `tasks/check.yml`, где все запросы SELECT) или защиту `when: not ansible_check_mode` на задачах с DML/DDL. Никогда не полагайтесь на `--check` для destructive SQL.

### Плейбук не идемпотентен (DDL с `IF EXISTS`)

**Причина:** `mariadb_query` определяет «уже существует» по предупреждению MySQL «already exists». PyMySQL 0.10.0+ (и mysqlclient) больше не выбрасывают это предупреждение, поэтому `DROP DATABASE IF EXISTS test` или `CREATE ... IF NOT EXISTS` сообщают `changed` даже когда ничего не произошло.

**Решение:** для БД и пользователей используйте модули `mariadb_db` / `mariadb_user` (полная идемпотентность); для остальных DDL — проверяйте состояние SELECT-запросом и применяйте условие (`when`).

### `mariadb_query` не подключается

**Причина:** неверный `login_user`/`login_password`, отсутствует `login_unix_socket`, или на хосте есть `~/.my.cnf` с `[client]`-секцией без корректных учётных данных.

**Решение:** проверьте учётные данные; для локального root используйте `login_unix_socket` вместо `login_host: localhost` (иначе — ошибка «Please explicitly state intended protocol» или «Host '127.0.0.1' is not allowed»); путь сокета различается: `/run/mysqld/mysqld.sock` (Debian/Ubuntu), `/var/lib/mysql/mysql.sock` (RHEL/Rocky). Для детерминизма указывайте `config_file: ''`.

### Рестарт mariadb ломает репликацию

**Причина:** handler `restart mariadb` срабатывает на каждом узле одновременно.

**Решение:** используйте `serial: 1` в плейбуке для поочерёдного применения.

### `skip-show-database` или `local-infile = 0` ломают приложение

**Причина:** приложение перечисляет базы (`SHOW DATABASES`) без привилегии или использует `LOAD DATA INFILE`.

**Решение:** выдайте прикладному пользователю `SHOW DATABASES` на конкретных базах; для импорта файлов используйте `mariadb` CLI на клиенте, а не `LOAD DATA INFILE` через SQL.

## Лучшие практики

1. **Секреты в Vault.** Пароли и ключи — только через `ansible-vault`, не в plaintext.
2. **Модули вместо raw SQL.** Где есть `mariadb_user` / `mariadb_db` / `mariadb_role` — используйте их: они идемпотентны и поддерживают check mode.
3. **Compliance-теги.** Разделяйте применение (`--tags hardening`) и проверку (`--tags check`).
4. **Снимки в git.** Ежедневные снимки привилегий — дешёвый детектор эскалации.
5. **`serial: 1` для кластеров.** Рестарт узлов по очереди, не одновременно.
6. **Бэкап перед hardening.** `mariadb-dump mysql` и копия `my.cnf` — иначе откат невозможен (Сценарий 8).
7. **Тестируйте на staging.** Плейбук hardening — сначала на копии production.
8. **`config_file: ''`.** Явно отключайте чтение `~/.my.cnf` в автоматизации — иначе поведение зависит от состояния хоста.

## Дополнительная информация

### Ограничения

- Модуль `ansible.mariadb.mariadb_query` требует установленного PyMySQL на целевом хосте и не поддерживает check mode.
- Динамические переменные (`SET GLOBAL`, в т.ч. через `mariadb_variables` и `mariadb_password_policy`) не персистентны; закрепляйте их в `my.cnf`.
- `mariadb_password_policy` на MariaDB покрывает только `simple_password_check`; `validate_password` настраивается через template.
- Коллекция `community.mysql` удалена в Ansible 17 — старые плейбуки с `community.mysql.*` перестанут работать; мигрируйте на `ansible.mysql.*` (MySQL) и `ansible.mariadb.*` (MariaDB).

### Граничные случаи

- **Galera / multi-master.** DDL (`DROP DATABASE`, `DELETE FROM mysql.user`) реплицируется на все узлы; применяйте плейбук с `serial: 1` и учитывайте `wsrep_OSU` (TOI блокирует таблицы на всех узлах).
- **Большой datadir.** `recurse: yes` на `/var/lib/mysql` с миллионами файлов работает долго; достаточно установить права на саму директорию — mysqld создаёт файлы с корректными правами.
- **`require_secure_transport = ON`** не блокирует unix-сокеты — локальные клиенты без TLS работают, TCP-клиенты обязаны использовать TLS.
- **`max_user_connections`** ограничивает конкурентные подключения одного пользователя — может ломать пулы соединений приложений.
- **Разные окружения:** путь сокета (`/run/mysqld/mysqld.sock` vs `/var/lib/mysql/mysql.sock`), имя сервиса (`mariadb` vs `mysqld`), пакет PyMySQL (`python3-pymysql` vs `python3-PyMySQL`) — выносите в inventory.

### Смежные темы

- **[Ansible OS hardening](../../../Ansible/ansible-os-hardening.md)** — OS-уровень (devsec).
- **[Configuration drift](../../../Ansible/examples/ansible_configuration_drift.md)** — детектирование дрейфа.
- **[Ansible: установка MySQL/MariaDB](../../../Ansible/examples/mysql_setup.md)** — установка и модули `ansible.mysql`.
- **[CIS Benchmark](cis-benchmark.md)** — контролы для автоматизации.
- **[Начальная закалка](hardening.md)** — что автоматизировать.
- **[Аутентификация](authentication.md)** — `validate_password`, PAM, `unix_socket`.
- **[Аудит](audit.md)** — параметры `server_audit`, ротация, SIEM.
- **[Мониторинг безопасности](security-monitoring.md)** — алерты на дрейф.
