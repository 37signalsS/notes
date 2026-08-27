# Ansible: автоматизация установки и настройки MySQL/MariaDB

## Определения

**Автоматизация установки MySQL/MariaDB** — декларативное описание и воспроизводимое развертывание серверов баз данных на различных ОС (Debian, Ubuntu, RHEL, Rocky) с использованием модулей Ansible, что исключает ошибки ручного ввода.

**FQCN (Fully Qualified Collection Name)** — полное имя коллекции и модуля (например, `ansible.mysql.mysql_user`), являющееся стандартом Ansible 2.10+. Гарантирует вызов нужного модуля и предотвращает конфликты имен.

**Идемпотентность** — свойство задач Ansible сохранять целевое состояние системы при многократных запусках. Если база данных уже создана, повторный запуск модуля `mysql_db` не приведет к изменениям или ошибкам.

**.my.cnf** — файл конфигурации клиента (обычно в `/root/`), хранящий учетные данные (`user`, `password`). Используется модулями Ansible для локального подключения без передачи пароля в открытом виде через аргументы командной строки.

## Базовые концепции

### Зависимости и коллекции

С версии Ansible 2.10 модули для работы с базами данных вынесены в коллекцию `ansible.mysql` (ранее `community.mysql`). Для работы модулей требуется наличие специфических Python-библиотек на целевом хосте.

| Компонент | Где требуется | Назначение |
|---|---|---|
| `ansible.mysql` | Управляющий узел | Коллекция модулей для управления БД, пользователями и репликацией. |
| `PyMySQL` | Целевой хост | Основной Python-драйвер для взаимодействия модулей с MySQL/MariaDB. |
| `cryptography` | Целевой хост | Библиотека для поддержки плагина `caching_sha2_password` (MySQL 8.0+). |

Установка коллекции:
```bash
ansible-galaxy collection install ansible.mysql
```

### Предварительные требования (Prerequisites)

Перед запуском плейбуков необходимо убедиться в выполнении следующих условий на **управляющем узле** и **целевых хостах**:

**Управляющий узел (Control Node):**

| Компонент | Минимальная версия | Проверка |
|---|---|---|
| Ansible | 2.15+ (рекомендуется ≥ 10.x для поддержки `ansible.mysql`) | `ansible --version` |
| Python | 3.10+ | `python3 --version` |
| `ansible.mysql` | Последняя версия | `ansible-galaxy collection list ansible.mysql` |

**Целевые хосты (Managed Nodes):**

| Компонент | Требование | Назначение |
|---|---|---|
| Python 3 | 3.8+ | Модули Ansible работают через Python на целевом хосте |
| `python3-pymysql` | Установлен | Python-драйвер для MySQL/MariaDB (обязателен для модулей `mysql_user`, `mysql_db`) |
| `python3-cryptography` | Установлен | Поддержка плагина `caching_sha2_password` (MySQL 8.0+) |
| Права `sudo` | Настроен `NOPASSWD` (рекомендуется) | Выполнение задач с `become: true` |
| SSH-доступ | Настроен и протестирован | Удаленное управление через Ansible |

**Проверка зависимостей на целевом хосте (однострочник):**
```bash
# Debian/Ubuntu
sudo apt install -y python3-pymysql python3-cryptography && python3 -c "import pymysql; import cryptography; print('Dependencies OK')"

# RHEL/Rocky
sudo dnf install -y python3-pymysql python3-cryptography && python3 -c "import pymysql; import cryptography; print('Dependencies OK')"
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

---

## Практические сценарии

### Сценарий 1: Полный цикл развертывания и закалки БД

Сценарий охватывает установку сервера, настройку безопасности и создание прикладной базы данных.

```yaml
---
- name: Развертывание и настройка MySQL/MariaDB
  hosts: db_servers
  become: true
  vars:
    # Используйте Ansible Vault для шифрования!
    mysql_root_password: "{{ vaulted_mysql_root_password }}"
    app_db_name: "production_app"
    app_db_user: "app_worker"
    app_db_password: "{{ vaulted_app_db_password }}"

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
        collation: utf8mb4_unicode_ci
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

### Сценарий 2: Настройка SSL/TLS и ограничение доступа

В современных инфраструктурах (2026+) шифрование трафика является обязательным.

```yaml
- name: Настройка обязательного SSL для подключений
  ansible.builtin.blockinfile:
    path: /etc/mysql/mariadb.conf.d/50-server.cnf # Путь зависит от дистрибутива
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

> **Примечание:** Если сценарий 2 используется отдельно, handlers должны быть определены в том же плейбуке или включены через `import_tasks` / `include_role`. Без определенного handler задача с `notify` завершится ошибкой `ERROR! The requested handler 'Restart Database Service' was not found`.

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

### Сценарий 3: Управление сетевым доступом (Firewall)

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

---

## Запуск и структура проекта

### Пример инвентаря (inventory)

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
└── templates/
    └── my.cnf.j2           # Шаблоны конфигураций
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

### Команды запуска

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

### Чек-лист валидации после развертывания

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

---

## Дополнительная информация

### Использование Module Defaults

Для сокращения кода при большом количестве задач можно использовать `module_defaults`, чтобы не указывать параметры подключения (`login_user`, `login_password`, `login_unix_socket`) в каждой задаче:

```yaml
- name: Работа с БД
  hosts: all
  module_defaults:
    ansible.mysql.mysql_user:
      login_unix_socket: /var/run/mysqld/mysqld.sock
    ansible.mysql.mysql_db:
      login_unix_socket: /var/run/mysqld/mysqld.sock
  tasks:
    # Задачи выполняются с использованием сокета без явного указания
    - name: Создание базы данных
      ansible.mysql.mysql_db:
        name: staging_db
        state: present
```

### Типичные ошибки

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

### Краевые случаи (Edge Cases)

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
2. Ограничивайте права пользователей (`priv`) только необходимыми таблицами и действиями.
3. Всегда используйте `FQCN` для надежности плейбуков.
4. Добавляйте `no_log: true` ко всем задачам, передающим пароли или конфиденциальные данные — это предотвращает утечку секретов в логах Ansible.
5. Для production-сред используйте `--ask-vault-pass` интерактивно или `--vault-password-file` с зашифрованным файлом пароля.
6. Регулярно проверяйте идемпотентность плейбуков — повторный запуск не должен показывать `changed` без реальных изменений.

## Смотрите также

- **[Ansible Vault: работа с секретами](../Vault/basics.md)**
- **[Развертывание LEMP-стека через Ansible](tutorial_lemp_stack.md)**
- **[MySQL: установка и базовая настройка (SSoT)](../../Databases/MySQL/installation.md)**
- **[MariaDB: установка и настройка (SSoT)](../../Databases/MariaDB/installation_and_setup.md)**
- **[Безопасная установка и закалка СУБД](../../Databases/installation_security.md)**
