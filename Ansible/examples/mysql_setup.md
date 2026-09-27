# Ansible: автоматизация установки и настройки MySQL/MariaDB

## Определения

**Автоматизация установки MySQL/MariaDB** — декларативное описание и воспроизводимое развертывание серверов баз данных на различных ОС (Debian, Ubuntu, RHEL, Rocky) с использованием модулей Ansible, что исключает ошибки ручного ввода и обеспечивает идемпотентность.

**FQCN (Fully Qualified Collection Name)** — полное имя коллекции и модуля (например, `ansible.mysql.mysql_user`), являющееся стандартом Ansible 2.10+. Гарантирует вызов нужного модуля и предотвращает конфликты имен.

**Идемпотентность** — свойство задач Ansible сохранять целевое состояние системы при многократных запусках. Если база данных уже создана, повторный запуск модуля `mysql_db` не приведет к изменениям или ошибкам.

**.my.cnf** — файл конфигурации клиента (обычно в `/root/`), хранящий учетные данные (`user`, `password`). Используется модулями Ansible для локального подключения без передачи пароля в открытом виде через аргументы командной строки.

**PyMySQL** — Python-драйвер для взаимодействия модулей `ansible.mysql` с MySQL/MariaDB на целевом хосте. Предпочтительный коннектор; `mysqlclient` устарел и будет удален в коллекции версии 6.0.

**caching_sha2_password** — плагин аутентификации MySQL 8.0+, использующий SHA-256 кэширование. Стандарт для MySQL 8.4 LTS и 9.0. В MariaDB 12.3 LTS поддерживается для совместимости.

**auth_socket** — плагин аутентификации, позволяющий пользователям ОС подключаться к MariaDB/MySQL без пароля при совпадении системного UID с именем пользователя БД (актуально для `root` на Debian/Ubuntu).

## Базовые концепции

### Архитектура модулей ansible.mysql

Коллекция `ansible.mysql` (5.x, released 2026-05-05) является преемником deprecated `community.mysql` и предоставляет модули для управления жизненным циклом СУБД:

| Модуль | Назначение |
|---|---|
| `mysql_db` | Создание, удаление баз данных |
| `mysql_user` | Управление пользователями и привилегиями |
| `mysql_replication` | Управление репликацией (primary/replica) |
| `mysql_variables` | Управление глобальными переменными |
| `mysql_info` | Сбор информации о сервере |
| `mysql_query` | Выполнение произвольных SQL-запросов |
| `mysql_perf_schema` | Управление Performance Schema |
| `mysql_slow_log` | Управление медленным логом |
| `mysql_clone` | Клонирование инстанса |

Все модули работают через Python-интерпретатор на целевом хосте, используя PyMySQL-коннектор. Модули не хранят состояние соединения между задачами — каждому вызову требуются параметры аутентификации или `.my.cnf`.

### Зависимости и коллекции

| Компонент | Где требуется | Назначение |
|---|---|---|
| `ansible.mysql` | Управляющий узел | Коллекция модулей для управления БД, пользователями и репликацией. |
| `PyMySQL` | Целевой хост | Основной Python-драйвер для взаимодействия модулей с MySQL/MariaDB. |
| `cryptography` | Целевой хост | Библиотека для поддержки плагина `caching_sha2_password` (MySQL 8.0+). |

Установка коллекции на управляющем узле:
```bash
ansible-galaxy collection install ansible.mysql
# → Installing 'ansible.mysql' to ...
```

Обновление до последней версии:
```bash
ansible-galaxy collection install ansible.mysql --upgrade
```

### Требования к среде

Перед запуском плейбуков необходимо убедиться в выполнении следующих условий на **управляющем узле** и **целевых хостах**:

**Управляющий узел (Control Node):**

| Компонент | Минимальная версия | Рекомендуется | Проверка |
|---|---|---|---|
| Ansible Core | 2.16.0+ | 2.21+ (GA: май 2026) | `ansible --version` |
| Python | 3.10+ | 3.12+ | `python3 --version` |
| `ansible.mysql` | 5.0+ | Последняя | `ansible-galaxy collection list ansible.mysql` |

**Целевые хосты (Managed Nodes):**

| Компонент | Требование | Назначение |
|---|---|---|
| Python 3 | 3.9+ | Модули Ansible работают через Python на целевом хосте |
| `python3-pymysql` | Установлен | Python-драйвер для MySQL/MariaDB (обязателен для модулей `mysql_user`, `mysql_db`) |
| `python3-cryptography` | Установлен | Поддержка плагина `caching_sha2_password` (MySQL 8.0+) |
| Права `sudo` | Настроен `NOPASSWD` (рекомендуется) | Выполнение задач с `become: true` |
| SSH-доступ | Настроен и протестирован | Удаленное управление через Ansible |

**Проверка зависимостей на целевом хосте (однострочник):**
```bash
# Debian/Ubuntu
sudo apt install -y python3-pymysql python3-cryptography && python3 -c "import pymysql; import cryptography; print('Dependencies OK')"
# → Dependencies OK

# RHEL/Rocky
sudo dnf install -y python3-pymysql python3-cryptography && python3 -c "import pymysql; import cryptography; print('Dependencies OK')"
# → Dependencies OK
```

> **Важно:** Если на целевом хосте отсутствует хотя бы одна зависимость, модули `ansible.mysql` завершатся ошибкой `ModuleNotFoundError`. В Ansible 2.10+ можно автоматизировать установку зависимостей через `ansible.builtin.raw` или `ansible.builtin.script` до вызова модулей БД.

### Аутентификация и современная безопасность

**Актуальность на 2026 год (Freshness Triggers):**
- **MySQL 8.4 LTS / 9.0:** Плагин `mysql_native_password` полностью удален в версии 9.0. Стандартом является `caching_sha2_password`.
- **MariaDB 12.3 LTS:** Поддерживает `caching_sha2_password` для совместимости. SSL/TLS рекомендуется включать по умолчанию для всех внешних соединений.
- **Debian/Ubuntu:** Для пользователя `root` по умолчанию применяется `auth_socket` (вход через sudo без пароля).

**Важные параметры модулей:**
- `login_unix_socket`: Обязателен для первичной настройки на Debian-системах, где root использует сокет.
- `check_implicit_admin`: Позволяет модулю войти без пароля, если обычный вход не удался (полезно при первом запуске после установки).
- `update_password: on_create`: Критически важно для плагина `caching_sha2_password`. Поскольку плагин генерирует разные хеши для одного пароля, этот параметр предотвращает ложные срабатывания `changed: true` при каждом запуске.

### Кроссплатформенные различия

| Параметр | Debian/Ubuntu | RHEL/Rocky |
|---|---|---|
| Пакет сервера | `mysql-server` или `mariadb-server` | `mariadb-server` (MySQL — через Oracle-репозиторий) |
| Имя службы | `mysql` | `mariadb` |
| Путь к сокету | `/var/run/mysqld/mysqld.sock` | `/var/lib/mysql/mysql.sock` |
| Конфиг my.cnf | `/etc/mysql/mysql.conf.d/mysqld.cnf` | `/etc/my.cnf.d/mysql.cnf` |
| Python-пакет | `python3-pymysql` | `python3-PyMySQL` (CamelCase в EPEL) |
| Firewall | `ufw` | `firewalld` |
| SELinux | Отсутствует | Включен по умолчанию (targeted) |

## Практические сценарии

### Сценарий 1: Полный цикл развертывания базы данных

Сценарий охватывает установку сервера, настройку безопасности и создание прикладной базы данных.

```yaml
---
- name: Развертывание и настройка MySQL/MariaDB
  hosts: db_servers
  become: true
  vars:
    mysql_root_password: "{{ vaulted_mysql_root_password }}"
    app_db_name: "production_app"
    app_db_user: "app_worker"
    app_db_password: "{{ vaulted_app_db_password }}"
    mysql_config_path: "{{ '/etc/mysql/mysql.conf.d/mysqld.cnf' if ansible_facts['os_family'] == 'Debian' else '/etc/my.cnf.d/mysql.cnf' }}"

  tasks:
    - name: Установка системных пакетов и зависимостей Python
      ansible.builtin.package:
        name:
          - "{{ 'mysql-server' if ansible_facts['os_family'] == 'Debian' else 'mariadb-server' }}"
          - python3-pymysql
          - python3-cryptography
        state: present
        update_cache: yes

    - name: Запуск и включение службы БД
      ansible.builtin.service:
        name: "{{ 'mysql' if ansible_facts['os_family'] == 'Debian' else 'mariadb' }}"
        state: started
        enabled: yes

    - name: Первичная настройка пароля root
      ansible.mysql.mysql_user:
        name: root
        password: "{{ mysql_root_password }}"
        login_unix_socket: "{{ '/var/run/mysqld/mysqld.sock' if ansible_facts['os_family'] == 'Debian' else omit }}"
        check_implicit_admin: yes
        state: present
        update_password: on_create
      no_log: true

    - name: Создание .my.cnf для идемпотентности root
      ansible.builtin.copy:
        content: |
          [client]
          user=root
          password="{{ mysql_root_password }}"
        dest: /root/.my.cnf
        owner: root
        group: root
        mode: '0400'
      no_log: true

    - name: Удаление небезопасных настроек по умолчанию
      ansible.mysql.mysql_user:
        name: ""
        host_all: yes
        state: absent
      loop: ["localhost", "{{ ansible_facts['hostname'] }}", "127.0.0.1", "::1"]

    - name: Создание прикладной базы данных
      ansible.mysql.mysql_db:
        name: "{{ app_db_name }}"
        encoding: utf8mb4
        collation: utf8mb4_0900_ai_ci
        state: present

    - name: Создание пользователя приложения с правами доступа
      ansible.mysql.mysql_user:
        name: "{{ app_db_user }}"
        password: "{{ app_db_password }}"
        priv: "{{ app_db_name }}.*:ALL"
        state: present
        update_password: on_create
      no_log: true
```

**Валидация (ожидаемый результат):**

После выполнения плейбука проверьте корректность развертывания:

```bash
# Проверка доступа root через .my.cnf
mysql -e "SELECT VERSION();"
# → Версия MySQL/MariaDB

# Проверка наличия БД и пользователя
mysql -e "SHOW DATABASES LIKE '{{ app_db_name }}';"
# → production_app

mysql -e "SELECT User, Host FROM mysql.user WHERE User='{{ app_db_user }}';"
# → app_worker    %

# Проверка прав пользователя
mysql -e "SHOW GRANTS FOR '{{ app_db_user }}'@'%';"
# → GRANT ALL PRIVILEGES ON `production_app`.* TO `app_worker`@`%`

# Идемпотентность: повторный запуск не должен показать changes
ansible-playbook playbook.yml --diff
# → В идеале: 0 changed
```

### Сценарий 2: Настройка первичной репликации (Primary-Replica)

Настройка асинхронной репликации для отказоустойчивости и распределения чтения.

```yaml
---
- name: Настройка репликации MySQL/MariaDB
  hosts: db_servers
  become: true
  vars:
    mysql_root_password: "{{ vaulted_mysql_root_password }}"
    repl_user: "repl_user"
    repl_password: "{{ vaulted_repl_password }}"
    primary_host: "{{ hostvars['db-primary']['ansible_host'] }}"
    replica_hosts: "{{ groups['db-replica'] | map('extract', hostvars, 'ansible_host') | list }}"

  tasks:
    - name: Создание пользователя репликации на primary
      ansible.mysql.mysql_user:
        name: "{{ repl_user }}"
        password: "{{ repl_password }}"
        priv: "REPLICATION SLAVE ON *.*:REPLICATION CLIENT ON *.*"
        state: present
      delegate_to: "{{ primary_host }}"
      no_log: true

    - name: Получение позиции бинарного лога primary
      ansible.mysql.mysql_replication:
        mode: getprimary
      delegate_to: "{{ primary_host }}"
      register: primary_status

    - name: Конфигурация replica (MySQL 8.0.23+ / MariaDB)
      ansible.mysql.mysql_replication:
        mode: changereplication
        primary_host: "{{ primary_host }}"
        primary_user: "{{ repl_user }}"
        primary_password: "{{ repl_password }}"
        primary_log_file: "{{ primary_status.File }}"
        primary_log_pos: "{{ primary_status.Position }}"
        gtid_mode: yes
        state: present
      when: ansible_facts['os_family'] == 'Debian' or (ansible_facts['os_family'] == 'RedHat' and ansible_facts['distribution_major_version'] | int >= 9)
      no_log: true

    - name: Запуск репликации
      ansible.mysql.mysql_replication:
        mode: startreplica
      delegate_to: "{{ replica_hosts }}"
```

**Валидация репликации:**
```bash
# Проверка статуса primary
mysql -e "SHOW MASTER STATUS;"
# → File: mysql-bin.000003, Position: 1234

# Проверка статуса replica
mysql -e "SHOW REPLICA STATUS\G"
# → Replica_IO_Running: Yes
# → Replica_SQL_Running: Yes
# → Seconds_Behind_Master: 0

# Проверка через Ansible
ansible db-replica -m ansible.mysql.mysql_replication -a "mode=getreplica" --ask-vault-pass
```

### Сценарий 3: Настройка SSL/TLS и ограничение доступа

В современных инфраструктурах шифрование трафика является обязательным.

```yaml
- name: Настройка обязательного SSL для подключений
  ansible.builtin.blockinfile:
    path: "{{ mysql_config_path }}"
    block: |
      [mysqld]
      ssl-ca=/etc/mysql/ssl/ca-cert.pem
      ssl-cert=/etc/mysql/ssl/server-cert.pem
      ssl-key=/etc/mysql/ssl/server-key.pem
      require_secure_transport=ON
  notify: Restart Database Service

- name: Требование SSL для пользователя приложения
  ansible.mysql.mysql_user:
    name: "{{ app_db_user }}"
    requires_ssl: yes
    state: present
```

**Обработчики (handlers) для данного сценария:**
```yaml
  handlers:
    - name: Restart Database Service
      ansible.builtin.service:
        name: "{{ 'mysql' if ansible_facts['os_family'] == 'Debian' else 'mariadb' }}"
        state: restarted
```

> **Примечание:** Путь к конфигурационному файлу зависит от дистрибутива и СУБД. Используйте переменную `mysql_config_path` для универсальности. Если сценарий 3 используется отдельно, handlers должны быть определены в том же плейбуке или включены через `import_tasks` / `include_role`. Без определенного handler задача с `notify` завершится ошибкой `ERROR! The requested handler 'Restart Database Service' was not found`.

**Валидация SSL-конфигурации:**
```bash
# Проверка включения SSL на сервере
mysql -e "SHOW VARIABLES LIKE '%ssl%';"
# → have_ssl = YES

# Проверка требований SSL для пользователя
mysql -e "SELECT user, ssl_type FROM mysql.user WHERE user='{{ app_db_user }}';"
# → app_worker    ANY

# Тест подключения с SSL
mysql --ssl-mode=REQUIRED -u {{ app_db_user }} -p -h 127.0.0.1
```

### Сценарий 4: Управление сетевым доступом (Firewall)

```yaml
- name: Открытие порта 3306 через UFW (Ubuntu/Debian)
  community.general.ufw:
    rule: allow
    port: 3306
    proto: tcp
    from_ip: "{{ trusted_network_range }}"
  when: ansible_facts['os_family'] == 'Debian'

- name: Открытие порта 3306 через Firewalld (RHEL/Rocky)
  ansible.posix.firewalld:
    port: 3306/tcp
    permanent: yes
    state: enabled
    immediate: yes
  when: ansible_facts['os_family'] == 'RedHat'
```

**Валидация сетевых правил:**
```bash
# Проверка UFW (Debian/Ubuntu)
sudo ufw status | grep 3306
# → 3306/tcp    ALLOW    10.0.0.0/24

# Проверка Firewalld (RHEL/Rocky)
sudo firewall-cmd --list-ports
# → 3306/tcp

# Тест подключения с удаленного хоста
mysql -h {{ target_host_ip }} -u {{ app_db_user }} -p -e "SELECT 1;"
```

### Сценарий 5: Автоматизация резервного копирования

Регулярное резервное копирование — ключевая задача SRE. Используйте `mysql_dump` или `mysql_query` для создания дампов.

```yaml
---
- name: Резервное копирование баз данных
  hosts: db_servers
  become: true
  vars:
    backup_dir: "/var/backups/mysql"
    retention_days: 7
    databases:
      - "{{ app_db_name }}"
      - mysql

  tasks:
    - name: Создание директории для бэкапов
      ansible.builtin.file:
        path: "{{ backup_dir }}"
        state: directory
        owner: root
        group: root
        mode: '0700'

    - name: Создание резервной копии баз данных
      ansible.builtin.shell: >
        mysqldump --defaults-file=/root/.my.cnf
        --single-transaction
        --routines
        --triggers
        --databases {{ item | join(' ') }}
        > {{ backup_dir }}/backup_{{ ansible_date_time.date }}_{{ item | join('_') }}.sql
      loop: "{{ databases }}"
      register: backup_result
      changed_when: "'mysqldump: Got' in backup_result.stdout or backup_result.rc == 0"

    - name: Сжатие резервных копий
      ansible.builtin.command: >
        gzip {{ backup_dir }}/backup_{{ ansible_date_time.date }}_*.sql
      when: backup_result.changed

    - name: Удаление устаревших резервных копий
      ansible.builtin.command: >
        find {{ backup_dir }} -type f -name "*.sql.gz" -mtime +{{ retention_days }} -delete
```

**Валидация бэкапов:**
```bash
# Проверка наличия файлов бэкапа
ls -la /var/backups/mysql/
# → backup_2026-09-22_production_app.sql.gz

# Проверка целостности дампа
gunzip -c /var/backups/mysql/backup_2026-09-22_production_app.sql.gz | head -20
# → -- MySQL dump 10.13 ...

# Проверка размера бэкапа
du -sh /var/backups/mysql/
# → 2.5G    /var/backups/mysql/
```

### Запуск и структура проекта

**Пример инвентаря (inventory):**

**Файл `inventory.ini`:**
```ini
[db_servers]
db-primary ansible_host=10.0.5.20 ansible_user=deploy
db-replica  ansible_host=10.0.5.21 ansible_user=deploy

[db_servers:vars]
ansible_become=true
ansible_become_method=sudo
```

**Структура файлов проекта:**
```
mysql-automation/
├── inventory.ini
├── playbook.yml
├── vars/
│   ├── vault.yml          # Зашифрованные пароли
│   └── default.yml        # Обычные переменные
├── handlers/
│   └── main.yml           # Handlers (Restart DB и т.д.)
├── templates/
│   └── my.cnf.j2           # Шаблоны конфигураций
└── files/
    └── ssl/                # SSL-сертификаты (если используются)
```

**Создание зашифрованных переменных:**
```bash
# Создание файла Vault
ansible-vault create vars/vault.yml
# → Содержимое:
#   vaulted_mysql_root_password: "StrongRoot2026!"
#   vaulted_app_db_password: "SecureApp2026!"

# Шифрование отдельной строки (для вставки в YAML)
ansible-vault encrypt_string 'StrongRoot2026!' --name 'vaulted_mysql_root_password'
```

**Команды запуска:**
```bash
# Полный запуск (с запросом пароля Vault)
ansible-playbook -i inventory.ini playbook.yml --ask-vault-pass

# Запуск с конкретными переменными
ansible-playbook -i inventory.ini playbook.yml \
  -e @vars/default.yml \
  --ask-vault-pass

# Проверка без выполнения (dry-run)
ansible-playbook -i inventory.ini playbook.yml --check --diff --ask-vault-pass

# Запуск только тегов
ansible-playbook -i inventory.ini playbook.yml --tags "install,security" --ask-vault-pass

# Ограничение по хостам
ansible-playbook -i inventory.ini playbook.yml --limit "db-primary" --ask-vault-pass
```

**Чек-лист валидации после развертывания:**

| Проверка | Команда | Ожидаемый результат |
|---|---|---|
| Служба запущена | `systemctl status mysql` | `active (running)` |
| Порт слушается | `ss -tlnp \| grep 3306` | Процесс `mysqld`/`mariadbd` на `0.0.0.0:3306` или `127.0.0.1:3306` |
| Root доступен | `mysql -e "SELECT 1;"` | `1` |
| Прикладная БД создана | `mysql -e "SHOW DATABASES;"` | Отображается `production_app` |
| Пользователь приложения создан | `mysql -e "SELECT User FROM mysql.user;"` | Отображается `app_worker` |
| .my.cnf корректен | `cat /root/.my.cnf \| wc -l` | ≥3 строки (секрет в зашифрованном виде) |
| Права .my.cnf | `stat -c %a /root/.my.cnf` | `400` |
| SSL включен (если настроен) | `mysql -e "SHOW VARIABLES LIKE 'have_ssl';"` | `YES` |
| Firewall активен | `ufw status` или `firewall-cmd --state` | `active` / `running` |

## Операции и команды

### Основные параметры модулей `ansible.mysql`

| Модуль | Параметр | Назначение | Пример |
|---|---|---|---|
| `mysql_user` | `name` | Имя пользователя БД | `app_worker` |
| `mysql_user` | `password` | Пароль пользователя | `"{{ vaulted_password }}"` |
| `mysql_user` | `priv` | Привилегии в формате `db.table:priv` | `"production_app.*:ALL"` |
| `mysql_user` | `login_unix_socket` | Путь к Unix-сокету для аутентификации | `/var/run/mysqld/mysqld.sock` |
| `mysql_user` | `check_implicit_admin` | Автоматический вход при первичной настройке | `yes` |
| `mysql_user` | `update_password` | Стратегия обновления пароля | `on_create` |
| `mysql_user` | `requires_ssl` | Требование SSL для пользователя | `yes` |
| `mysql_db` | `name` | Имя базы данных | `production_app` |
| `mysql_db` | `encoding` | Кодировка символов | `utf8mb4` |
| `mysql_db` | `collation` | Сравнение и сортировка | `utf8mb4_0900_ai_ci` |
| `mysql_db` | `state` | Желаемое состояние | `present` / `absent` |
| `mysql_replication` | `mode` | Режим работы | `getprimary` / `getreplica` / `startreplica` / `stopreplica` / `changereplication` |
| `mysql_variables` | `name` | Имя переменной | `innodb_buffer_pool_size` |
| `mysql_variables` | `value` | Значение переменной | `2G` |

### Общие команды управления

```bash
# Проверка подключения и версии
mysql -e "SELECT VERSION();"
# → Версия MySQL/MariaDB

# Список баз данных
mysql -e "SHOW DATABASES;"

# Создание базы данных (ручной метод)
mysql -e "CREATE DATABASE mydb CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;"

# Создание пользователя (ручной метод)
mysql -e "CREATE USER 'user'@'%' IDENTIFIED BY 'password';"
mysql -e "GRANT ALL PRIVILEGES ON mydb.* TO 'user'@'%';"
mysql -e "FLUSH PRIVILEGES;"

# Проверка статуса репликации
mysql -e "SHOW REPLICA STATUS\G"
# → Replica_IO_Running: Yes
# → Replica_SQL_Running: Yes

# Проверка глобальных переменных
mysql -e "SHOW VARIABLES LIKE 'innodb_buffer_pool_size';"
# → innodb_buffer_pool_size | 1342177280
```

## Устранение неисправностей

| Ошибка | Причина | Решение |
|---|---|---|
| `Authentication plugin 'caching_sha2_password' is not supported` | Отсутствует `python3-cryptography` на целевом хосте. | Установите пакет `python3-cryptography`. |
| `Access denied for user 'root'@'localhost'` | Пароль уже изменен, а файл `.my.cnf` отсутствует или содержит неверные данные. | Проверьте наличие `/root/.my.cnf` или передайте `login_password` явно. |
| `ansible.mysql.mysql_user not found` | Коллекция не установлена на управляющем узле. | Выполните `ansible-galaxy collection install ansible.mysql`. |
| `Changed: true` на каждом прогоне | Использование `caching_sha2_password` без `update_password: on_create`. | Добавьте параметр `update_password: on_create` в модуль `mysql_user`. |
| `ModuleNotFoundError: No module named 'pymysql'` | На целевом хосте не установлена библиотека Python. | Установите `python3-pymysql` через `ansible.builtin.raw` или `ansible.builtin.package`. |
| `ERROR! The requested handler 'Restart Database Service' was not found` | Handler не определен в плейбуке или в `handlers/main.yml`. | Добавьте секцию `handlers:` в плейбук или подключите файл handlers. |
| `TimeoutExpiredError: Timeout expired` | Сервер БД не отвечает (ohlades, большой load, сбой сети). | Проверьте `systemctl status mysql`, логи ошибок, нагрузку на сервере. |
| `ERROR! `login_unix_socket` is not a valid parameter` | Используется старая версия коллекции без поддержки параметра. | Обновите коллекцию: `ansible-galaxy collection install ansible.mysql --upgrade`. |
| `Unreachable: Failed to connect to the host via ssh` | SSH-доступ не настроен или заблокирован Firewall. | Проверьте SSH-подключение вручную: `ssh user@host`. |
| `Permission denied: 'become' requires the 'sudo' package` | На целевом хосте не установлен `sudo`. | Установите `sudo` на целевом хосте или используйте другой метод привилегирования. |
| `The field 'encoding' is not valid for mysql_db` | Неверное имя параметра или устаревшая версия модуля. | Проверьте FQCN (`ansible.mysql.mysql_db`) и версию коллекции. |
| `Found multiple matches for 'host'` | Пользователь уже существует с разными хостами. | Укажите `host` явно или используйте `host_all: yes` для удаления всех записей. |
| `Replica_IO_Running: No` | Реплика не может подключиться к primary или сетевой доступ запрещен. | Проверьте `primary_host`, `primary_user`, порт 3306, Firewall, SSL-настройки. |
| `InnoDB: Upgrade after a crash is not supported` | Попытка обновиться на "грязных" данных после сбоя. | Вернитесь на старую версию, выполните чистую остановку (`SET GLOBAL innodb_fast_shutdown = 0`), затем обновляйтесь. |

## Рекомендации

### Безопасность

Никогда не храните пароли в открытом виде. Используйте **[Ansible Vault](../Vault/basics.md)** для шифрования переменных:

```bash
# Шифрование строки с привязкой к имени переменной
ansible-vault encrypt_string 'StrongPassword2026!' --name 'mysql_root_password'

# Вставка зашифрованного значения в YAML
vaulted_mysql_root_password: !vault |
  $ANSIBLE_VAULT;1.1;AES256
  61626364656667686970...
```

**Рекомендации:**
1. Не используйте `bind-address = 0.0.0.0` без настроенного Firewall.
2. Ограничивайте права пользователей (`priv`) только необходимыми таблицами и действиями. Вместо `ALL` используйте конкретные привилегии: `SELECT,INSERT,UPDATE,DELETE` для приложений, `SELECT` для reporting-пользователей.
3. Всегда используйте `FQCN` для надежности плейбуков.
4. Добавляйте `no_log: true` ко всем задачам, передающим пароли или конфиденциальные данные — это предотвращает утечку секретов в логах Ansible.
5. Для production-сред используйте `--ask-vault-pass` интерактивно или `--vault-password-file` с зашифрованным файлом пароля.
6. Регулярно проверяйте идемпотентность плейбуков — повторный запуск не должен показывать `changed` без реальных изменений.
7. На RHEL/Rocky настройте контексты SELinux для директории `/var/lib/mysql`:
   ```bash
   sudo semanage fcontext -a -t mysqld_db_t "/var/lib/mysql(/.*)?"
   sudo restorecon -Rv /var/lib/mysql
   ```

### Краевые случаи

**1. Первый запуск после установки СУБД:**
На Debian/Ubuntu после `apt install mysql-server` root-пользователь аутентифицируется через `auth_socket`. Модуль `mysql_user` с `check_implicit_admin: yes` автоматически определяет это и выполняет настройку без явного пароля. Если `check_implicit_admin` не указан, задача завершится ошибкой `Access denied`.

**2. Кросс-платформенные различия (MySQL vs MariaDB):**
- Название пакета: `mysql-server` (Debian) vs `mariadb-server` (RHEL). В playbook используется условный оператор `if ansible_facts['os_family']`.
- Путь к сокету: `/var/run/mysqld/mysqld.sock` (MySQL) vs `/var/run/mysqld/mysqld.sock` (MariaDB на Debian) или `/var/lib/mysql/mysql.sock` (RHEL).
- Имя службы: `mysql` (Debian) vs `mariadb` (RHEL). Проверьте через `systemctl list-unit-files | grep -E 'mysql|mariadb'`.

**3. Пароль содержит спецсимволы:**
Если пароль содержит `$`, `!`, `#` или пробелы, используйте Ansible Vault для шифрования переменных. Передача таких паролей через `-e` на командной строке может привести к ошибкам парсинга shell.

**4. Идемпотентность и `update_password: on_create`:**
Плагин `caching_sha2_password` (MySQL 8.0+) генерирует разные хеши для одного и того же пароля при каждом вызове `PASSWORD()`. Без `update_password: on_create` модуль будет считать, что пароль изменился, и возвращать `changed: true` при каждом запуске. Параметр `on_create` гарантирует, что пароль устанавливается только при создании пользователя.

**5. Работа с существующей СУБД (не с нуля):**
Если MySQL/MariaDB уже установлен и настроен, задача «Первичная настройка пароля root» может завершиться ошибкой `Access denied`. Решение: используйте `login_unix_socket` (для Debian-систем) или `check_implicit_admin: yes` для первичного доступа.

**6. Ограничение привилегий (Principle of Least Privilege):**
Вместо `ALL` используйте конкретные привилегии: `SELECT,INSERT,UPDATE,DELETE` для приложений, `SELECT` для reporting-пользователей. Это минимизирует последствия компрометации учетной записи.

**7. Масштабирование на несколько хостов:**
Для кластерных развертываний (Galera, Group Replication) добавьте `serial: 1` в плейбук для последовательного выполнения на каждом хосте. Параллельный запуск может привести к конфликтам при создании пользователей и БД.

**8. Обновление версии СУБД:**
При переходе между минорными версиями (например, 8.4.1 → 8.4.2) выполните полный бэкап перед обновлением. MySQL 8.0.16+ выполняет `mysql_upgrade` автоматически при старте. Для мажорных обновлений проверьте `my.cnf` на наличие удаленных параметров.

### Обслуживание

**Регулярные проверки:**
```bash
# Проверка целостности таблиц
mysql -e "CHECK TABLE production_app.*;"

# Оптимизация таблиц (при фрагментации)
mysql -e "OPTIMIZE TABLE production_app.large_table;"

# Проверка статуса InnoDB
mysql -e "SHOW ENGINE INNODB STATUS\G"
```

**Мониторинг через Ansible:**
```yaml
- name: Проверка статуса сервера БД
  ansible.mysql.mysql_info:
    login_user: root
    login_password: "{{ vaulted_mysql_root_password }}"
  register: db_info

- name: Отчет о версии и статусе
  ansible.builtin.debug:
    msg: "Версия: {{ db_info.version }}, Uptime: {{ db_info.uptime }}"
```

## Дополнительная информация

### Использование Module Defaults

Для сокращения кода при большом количестве задач можно использовать `module_defaults`, чтобы не указывать параметры подключения (`login_user`, `login_password`, `login_unix_socket`) в каждой задаче:

```yaml
- name: Работа с БД
  hosts: all
  module_defaults:
    group/ansible.mysql:
      login_unix_socket: /var/run/mysqld/mysqld.sock
      login_user: root
      login_password: "{{ vault_mysql_root_pass }}"
  tasks:
    # Задачи выполняются с использованием сокета без явного указания
    - name: Создание базы данных
      ansible.mysql.mysql_db:
        name: staging_db
        state: present

    - name: Создание пользователя
      ansible.mysql.mysql_user:
        name: staging_user
        password: "{{ vault_staging_pass }}"
        priv: "staging_db.*:ALL"
        state: present
```

> **Важно:** Групповой синтаксис `group/ansible.mysql` применяет дефолты ко всем модулям коллекции. Убедитесь, что это не конфликтует с другими модулями в плейбуке.

### Замечания по кроссплатформенности

- Название пакета на RHEL/Rocky по умолчанию — `mariadb-server`. Для установки MySQL Community Server используйте официальные репозитории Oracle (см. [Установка MySQL](../../Databases/MySQL/installation.md)).
- Путь к конфигурационному файлу (`my.cnf`) различается между дистрибутивами и СУБД. Используйте переменные для универсальности.
- На RHEL/Rocky пакет Python-библиотеки может называться `python3-PyMySQL` (CamelCase) в зависимости от репозитория.
- На RHEL/Rocky настройте контексты SELinux для `/var/lib/mysql` и `/var/run/mysqld/`.

## Смотрите также

- **[Ansible Vault: работа с секретами](../Vault/basics.md)**
- **[MySQL: установка и базовая настройка](../../Databases/MySQL/installation.md)**
- **[MariaDB: установка и настройка](../../Databases/MariaDB/installation_and_setup.md)**
