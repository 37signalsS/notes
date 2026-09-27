# Ansible: Модули управления инфраструктурой и сервисами

## Определения

**Модули управления инфраструктурой** — группа специализированных декларативных инструментов Ansible из сторонних коллекций (`community.*`, `prometheus.*`, `datadog.*` и др.), предназначенных для автоматизации развертывания и конфигурации инфраструктурных сервисов: баз данных, веб-серверов, балансировщиков нагрузки, систем мониторинга, агентов observability и инструментов бэкапа.

**Collection-first подход** — современный стандарт Ansible, при котором функциональность переносится из отдельных модулей в коллекции. Перед использованием модуля необходимо установить соответствующую коллекцию через `ansible-galaxy collection install <namespace>.<collection>`.

**FQCN (Fully Qualified Collection Name)** — полное имя модуля в формате `namespace.collection.module` (например, `community.postgresql.postgresql_db`). Использование FQCN является обязательным стандартом для предотвращения конфликтов имен и обеспечения предсказуемости выполнения.

## Версионирование и требования

| Компонент | Минимальная версия | Рекомендуемая версия | Примечание |
| :--- | :--- | :--- | :--- |
| **ansible-core** | 2.15+ | 2.21.4+ | 2.22 GA Nov 2026 |
| **community.postgresql** | 4.0+ | 4.2.0+ | 4.x текущая |
| **ansible.mysql** | 3.0+ | 3.0+ | |
| **community.mongodb** | 3.0+ | 3.0+ | |
| **community.general** | 6.0+ | Актуальная | `nginx`, `haproxy`, `borg`, `restic`, `rsync` |
| **prometheus.prometheus** | 0.30.2+ | 0.30.2+ | Prometheus, exporters |
| **community.grafana** | 2.0.0+ | 2.3.0+ | Дашборды, data sources |
| **community.zabbix** | 2.0+ | Актуальная | Zabbix-специфичные модули |
| **datadog.dd** | 2.0+ | 5.6.0+ | Datadog мониторинг |
| **netways.icinga** | 0.4.0+ | 0.4.7+ | Icinga 2 |
| **community.kafka** | 1.0+ | Актуальная | Kafka топики, пользователи |
| **community.rabbitmq** | 1.0+ | Актуальная | RabbitMQ |
| **Python** (target) | 3.9+ | 3.12+ | |
| **sudo** (target) | 1.8+ | Актуальная LTS | |

**Установка коллекций:**
```bash
ansible-galaxy collection install community.postgresql:>=4.0
ansible-galaxy collection install ansible.mysql:>=3.0
ansible-galaxy collection install community.mongodb:>=3.0
ansible-galaxy collection install prometheus.prometheus:>=0.30.2
ansible-galaxy collection install community.grafana:>=2.0.0
ansible-galaxy collection install community.zabbix
ansible-galaxy collection install datadog.dd
ansible-galaxy collection install netways.icinga
ansible-galaxy collection install community.kafka
ansible-galaxy collection install community.rabbitmq
ansible-galaxy collection install community.general
```

**Проверка окружения:**
```bash
ansible --version | head -1
# → ansible [core 2.21.4]

ansible-doc -l community.postgresql | head -10
# → community.postgresql.postgresql_db
# → community.postgresql.postgresql_user

ansible-doc -l prometheus.prometheus | head -10
# → prometheus.prometheus.prometheus
# → prometheus.prometheus.node_exporter

ansible-doc -l community.general | grep -E "nginx|haproxy|borg|restic"
# → community.general.nginx
# → community.general.haproxy

# Проверка установленных коллекций
ansible-galaxy collection list | grep -E "community.postgresql|prometheus|grafana"
# → community.postgresql 4.2.0
# → prometheus.prometheus 0.30.2
```

## Архитектура и принципы работы

### Жизненный цикл инфраструктурного модуля

Каждый модуль управления инфраструктурой проходит через стандартный жизненный цикл Ansible:

1. **Инициализация:** проверка prerequisites, установка пакетов, создание пользователей/групп
2. **Конфигурация:** генерация конфигов через `template`, применение параметров через модули
3. **Валидация:** проверка конфигурации (`validate` параметр, `named-checkconf`, `nginx -t`)
4. **Применение:** запуск/перезапуск сервиса через `service`/`systemd`
5. **Проверка:** verification через `uri`, `command`, `service_facts`

### Модель идемпотентности

Инфраструктурные модули следуют принципу идемпотентности:
- Повторный запуск с одинаковыми параметрами не изменяет состояние
- `state: present` создаёт ресурс только если он отсутствует
- `state: absent` удаляет только существующий ресурс
- Конфигурационные изменения применяются только при diff в шаблоне

### Привилегированный доступ

Подавляющее большинство инфраструктурных модулей требует `become: yes` для:
- Установки пакетов (`apt`, `yum`, `dnf`)
- Создания системных пользователей и групп
- Изменения конфигураций в `/etc/`
- Управления сервисами (`systemctl start/enable`)

## Основные концепции

### Модули управления базами данных

Подробную информацию о модулях управления базами данных см. в файле **[Модули управления базами данных](./ansible_database_modules.md)**.

### Модули управления веб-серверами и балансировщиками

1.  **`community.general.nginx`**: Установка и настройка Nginx из репозиториев. Для управления конфигами используйте `template` + `lineinfile`.
2.  **`community.general.apache`**: Установка и настройка Apache HTTPD. Поддерживает `state`, `enabled`, `modules`, `mpm_module`.
3.  **`community.general.haproxy`**: Управление HAProxy. Настройка frontend, backend, балансировки. Поддерживает `state`, `enabled`, `config`.
4.  **`community.general.traefik`**: Управление Traefik. Настройка через статические и динамические конфиги.
5.  **`community.general.angie`**: Управление веб-сервером Angie (fork Nginx).

### Модули управления мониторингом и observability

Подробную информацию о модулях управления мониторингом см. в файле **[Модули управления мониторингом и observability](./ansible_monitoring_modules.md)**.

### Модули управления бэкапами и синхронизацией

1.  **`community.general.borg`**: Управление репозиториями BorgBackup. Создание snapshot, prune, check, mount.
2.  **`community.general.restic`**: Управление репозиториями Restic. Создание snapshot, prune, check, restore.
3.  **`community.general.rsync`**: Синхронизация файлов через rsync. Альтернатива `ansible.posix.synchronize` для точечных задач.
4.  **`community.general.rclone`**: Синхронизация данных между хранилищами. Поддерживает локальные пути, SFTP, WebDAV и другие протоколы. Копирование, sync, mount.

### Модули управления очередями сообщений

1.  **`community.kafka.kafka_topic`**: Управление топиками Kafka. Создание, удаление, настройка partitions, replication_factor, retention.
2.  **`community.kafka.kafka_user`**: Управление пользователями Kafka (SCRAM-SHA).
3.  **`community.rabbitmq.rabbitmq_user`**: Управление пользователями RabbitMQ.
4.  **`community.rabbitmq.rabbitmq_vhost`**: Управление виртуальными хостами RabbitMQ.
5.  **`community.rabbitmq.rabbitmq_queue`**: Управление очередями RabbitMQ.

### Привилегированный доступ (become)

Все модули управления инфраструктурой требуют root-доступа для установки пакетов, создания пользователей БД, изменения конфигураций.

```yaml
- name: "Установка PostgreSQL"
  community.postgresql.postgresql_db:
    name: production_db
    owner: app_user
  become: yes
  become_user: postgres
```

## Практические сценарии

### Сценарий 1: Полный цикл развертывания PostgreSQL с monitoring

Создание БД, пользователя, расширения и установка экспортера. Включает валидацию через `service_facts` и `uri` модули.

```yaml
- name: "Установка PostgreSQL"
  ansible.builtin.package:
    name:
      - postgresql16
      - postgresql16-server
    state: present
  become: yes

- name: "Инициализация БД"
  ansible.builtin.command: postgresql-16-setup initdb
  become: yes
  become_user: postgres

- name: "Создание БД production"
  community.postgresql.postgresql_db:
    name: production_db
    owner: app_user
    encoding: UTF-8
    lc_collate: en_US.UTF-8
  become: yes
  become_user: postgres

- name: "Создание пользователя app_user"
  community.postgresql.postgresql_user:
    name: app_user
    password: "{{ vault_db_password }}"
    role_attr_flags: LOGIN,CREATEDB
  become: yes
  become_user: postgres

- name: "Установка расширения pg_stat_statements"
  community.postgresql.postgresql_ext:
    name: pg_stat_statements
    db: production_db
  become: yes
  become_user: postgres

- name: "Создание пользователя мониторинга"
  community.postgresql.postgresql_user:
    name: prometheus_exporter
    password: "{{ vault_prometheus_password }}"
    role_attr_flags: LOGIN
    groups: pg_monitor
  become: yes
  become_user: postgres

- name: "Установка postgres_exporter"
  prometheus.prometheus.postgres_exporter:
    name: postgres_exporter
    config:
      data_source_name: "postgresql://prometheus_exporter:{{ vault_prometheus_password }}@localhost:5432/production_db?sslmode=disable"
    listen_address: "0.0.0.0:9187"
  become: yes
```

**Валидация:**
```bash
# Проверка статуса PostgreSQL
ansible db -i inventory.ini -m service_facts | grep postgresql
# → "postgresql": {"state": "running", "status": "enabled"}

# Проверка подключения
ansible db -i inventory.ini -m community.postgresql.postgresql_query -a "db=production_db query='SELECT 1'"
# → "rowcount": 1

# Проверка метрик экспортера
ansible db -i inventory.ini -m uri -a "url=http://localhost:9187/metrics"
# → "status": 200, body содержит pg_up, pg_exporter_
```

### Сценарий 2: Развертывание Nginx с HTTPS

Установка Nginx, настройка конфига, SSL и валидация.

```yaml
- name: "Установка Nginx"
  community.general.nginx:
    state: present
  become: yes

- name: "Настройка виртуального хоста"
  ansible.builtin.template:
    src: templates/nginx_vhost.conf.j2
    dest: /etc/nginx/conf.d/app.conf
    validate: 'nginx -t -c %s'
  become: yes
  notify: "Reload Nginx"

- name: "Разрешение HTTPS через firewalld"
  ansible.posix.firewalld:
    service: https
    permanent: yes
    immediate: yes
    state: enabled
  become: yes
  when: ansible_os_family == "RedHat"
```

**Валидация:**
```bash
# Проверка конфигурации
ansible web -i inventory.ini -m command -a "nginx -t"
# → nginx: the configuration file /etc/nginx/nginx.conf syntax is ok
# → nginx: configuration file /etc/nginx/nginx.conf test is successful

# Проверка статуса
ansible web -i inventory.ini -m service_facts | grep nginx
# → "nginx": {"state": "running", "status": "enabled"}

# Проверка HTTPS ответа
ansible web -i inventory.ini -m uri -a "url=https://localhost status_code=200"
# → "status": 200
```

### Сценарий 3: Настройка HAProxy с health check

Балансировка нагрузки между несколькими веб-серверами.

```yaml
- name: "Установка HAProxy"
  community.general.haproxy:
    state: started
    enabled: yes
  become: yes

- name: "Настройка backend"
  ansible.builtin.template:
    src: templates/haproxy.cfg.j2
    dest: /etc/haproxy/haproxy.cfg
    validate: 'haproxy -c -f %s'
  become: yes
  notify: "Reload HAProxy"
```

**Валидация:**
```bash
# Проверка конфигурации
ansible lb -i inventory.ini -m command -a "haproxy -c -f /etc/haproxy/haproxy.cfg"
# → Configuration file is valid

# Проверка stats
ansible lb -i inventory.ini -m uri -a "url=http://localhost:8404/stats"
# → "status": 200

# Проверка backend доступности
ansible lb -i inventory.ini -m command -a "echo 'show stat' | socat /var/run/haproxy.sock stdio | grep web01"
# → web01,RUNNING,0,0,0,0,...
```

### Сценарий 4: Установка Prometheus и node_exporter

Развертывание Prometheus server и сбора метрик с хостов.

```yaml
- name: "Установка Prometheus"
  prometheus.prometheus.prometheus:
    name: prometheus
    version: "3.0.0"
    config:
      global:
        scrape_interval: 15s
      scrape_configs:
        - job_name: node
          static_configs:
            - targets: ['{{ inventory_hostname }}:9100']
  become: yes

- name: "Установка node_exporter"
  prometheus.prometheus.node_exporter:
    name: node_exporter
    listen_address: "0.0.0.0:9100"
  become: yes
```

**Валидация:**
```bash
# Проверка targets в Prometheus
ansible monitoring -i inventory.ini -m uri -a "url=http://localhost:9090/api/v1/targets"
# → "activeTargets": [{"instance": "web01:9100", "health": "up"}]

# Проверка метрик
ansible web -i inventory.ini -m command -a "curl -s http://localhost:9100/metrics | head -5"
# → node_cpu_seconds_total{cpu="0",mode="idle"} 12345.67
# → node_memory_MemAvailable_bytes 1234567890

# Проверка алертов
ansible monitoring -i inventory.ini -m uri -a "url=http://localhost:9090/api/v1/alerts"
# → "alerts": [{"state": "inactive", ...}]
```

### Сценарий 5: Бэкап с Restic

Настройка репозитория и создание snapshot.

```yaml
- name: "Установка Restic"
  community.general.restic:
    state: present
  become: yes

- name: "Инициализация репозитория"
  community.general.restic:
    repo: "rest:http://backup-server:8000/repo"
    password: "{{ vault_restic_password }}"
    state: initialized

- name: "Создание snapshot"
  community.general.restic:
    repo: "rest:http://backup-server:8000/repo"
    password: "{{ vault_restic_password }}"
    paths:
      - /etc
      - /var/lib/data
    state: snapshotted
```

**Валидация:**
```bash
# Проверка snapshot'ов
ansible db -i inventory.ini -m command -a "restic -r rest:http://backup-server:8000/repo snapshots --password-file /etc/restic/password"
# → repository a1b2c3d4 opened successfully
# → ID        Date             Host        Tags  Paths
# → a1b2c3d4  2026-09-26 02:00 db01        []    /etc, /var/lib/data

# Проверка целостности
ansible db -i inventory.ini -m command -a "restic -r rest:http://backup-server:8000/repo check --password-file /etc/restic/password"
# → create exclusive lock for repository
# → check all packs
# → checking all blobs
# → no errors were found
```

## Операции и команды

### Базы данных

Подробные операционные таблицы см. в файле **[Модули управления базами данных](./ansible_database_modules.md)**.

### Веб-серверы

| Операция | Команда |
| :--- | :--- |
| Установка Nginx | `community.general.nginx` с `state: present` |
| Применение конфига | `ansible.builtin.template` с `validate: 'nginx -t -c %s'` |
| Установка Apache | `community.general.apache` с `state`, `enabled`, `modules` |
| Установка HAProxy | `community.general.haproxy` с `state: started`, `enabled: yes` |
| Настройка Traefik | `community.general.traefik` с `static_config`, `dynamic_config` |

### Мониторинг

Подробную информацию об операциях управления мониторингом см. в файле **[Модули управления мониторингом и observability](./ansible_monitoring_modules.md)**.

### Бэкапы

| Операция | Команда |
| :--- | :--- |
| Создание snapshot Borg | `community.general.borg` с `repo`, `path`, `state: snapshotted` |
| Создание snapshot Restic | `community.general.restic` с `repo`, `paths`, `state: snapshotted` |
| Prune старые snapshot | `community.general.borg` / `community.general.restic` с `state: pruned` |
| Синхронизация файлов | `community.general.rsync` с `src`, `dest`, `mode` |

### Очереди сообщений

| Операция | Команда |
| :--- | :--- |
| Создание топика Kafka | `community.kafka.kafka_topic` с `name`, `partitions`, `replication_factor` |
| Создание пользователя Kafka | `community.kafka.kafka_user` с `username`, `password` |
| Создание vhost RabbitMQ | `community.rabbitmq.rabbitmq_vhost` с `name`, `state` |
| Создание очереди RabbitMQ | `community.rabbitmq.rabbitmq_queue` с `name`, `vhost` |

## Устранение неполадок

### Типичные ошибки и их решение

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `FATAL: role "app_user" does not exist` | Пользователь не создан | Создайте пользователя перед выдачей прав; см. [Модули управления базами данных](./ansible_database_modules.md) |
| `psycopg2.errors.DuplicateDatabase` | БД уже существует | Используйте `state: present` (идемпотентно); см. [Модули управления базами данных](./ansible_database_modules.md) |
| `caching_sha2_password is not supported` | Отсутствует python3-cryptography | Установите пакет на целевой хост |
| `Access denied for user` | Неверные учетные данные | Проверьте пароль, хост, права пользователя |
| `Connection refused` | Служба не запущена | Запустите сервис: `systemctl start postgresql` |
| `Exporter timeout` | Экспортер не слушает порт | Проверьте `netstat -tlnp | grep 9187` |
| `Snapshot already exists` | Snapshot с таким именем существует | Удалите старый snapshot или используйте уникальное имя |
| `nginx: [emerg] unknown directive` | Ошибка в конфигурации | Проверьте синтаксис: `nginx -t -c /etc/nginx/nginx.conf` |
| `HAProxy configuration is invalid` | Ошибка в haproxy.cfg | Проверьте: `haproxy -c -f /etc/haproxy/haproxy.cfg` |

### Диагностические команды

```bash
# Проверка статуса PostgreSQL
systemctl status postgresql
# → ● postgresql.service - PostgreSQL database server
# →      Loaded: loaded (/usr/lib/systemd/system/postgresql.service; enabled)
# →      Active: active (running) since Mon 2026-09-26 02:00:00 UTC

# Проверка пользователей
sudo -u postgres psql -c "\du"
# → List of roles
# → Role name | Attributes | Member of
# → app_user  | Superuser  | {}

# Проверка репликации
sudo -u postgres psql -c "SHOW replica_status;"
# → Replica_IO_Running: Yes
# → Replica_SQL_Running: Yes

# Проверка node_exporter
curl http://localhost:9100/metrics | head -20
# → node_cpu_seconds_total{cpu="0",mode="idle"} 12345.67
# → node_memory_MemAvailable_bytes 1234567890

# Проверка Borg репозитория
borg list /backup/repo
# → backup-2026-09-24  Thu, 2026-09-24 02:00:00

# Проверка Nginx конфигурации
nginx -t -c /etc/nginx/nginx.conf
# → nginx: the configuration file /etc/nginx/nginx.conf syntax is ok
# → nginx: configuration file /etc/nginx/nginx.conf test is successful

# Проверка HAProxy конфигурации
haproxy -c -f /etc/haproxy/haproxy.cfg
# → Configuration file is valid

# Диагностика мониторинга
# Подробные команды см. в файле [Модули управления мониторингом и observability](./ansible_monitoring_modules.md)
```

## Рекомендации и оптимизация

### Базы данных

- **Идемпотентность**: Всегда используйте `state: present` для создания ресурсов. Повторный запуск не должен вызывать ошибок. Детали см. в [Модули управления базами данных](./ansible_database_modules.md).
- **Пароли**: Храните пароли в Ansible Vault. Используйте `no_log: true` для задач с секретами.
- **Репликация**: Для production используйте `community.postgresql.postgresql_slot` или `ansible.mysql.mysql_replication`. Детали см. в [Модули управления базами данных](./ansible_database_modules.md).
- **SSL/TLS**: Включайте `requires_ssl: yes` для пользователей MySQL. Настройте `ssl_cert`/`ssl_key` для PostgreSQL.
- **Резервное копирование**: Автоматизируйте через `community.general.borg` или `community.general.restic` с cron-заданиями.

### Веб-серверы

- **Валидация**: Используйте `validate: 'nginx -t -c %s'` или `validate: 'apachectl -t -f %s'` перед применением конфигурации.
- **Handlers**: Используйте `notify` + `handler` для перезапуска сервиса только при изменении конфига.
- **Модульность**: Для сложных конфигураций используйте `template` с переменными вместо `lineinfile`.
- **Безопасность**: Отключайте неиспользуемые модули Nginx/Apache. Ограничивайте доступ к `.git` и скрытым файлам.

### Мониторинг

Подробные рекомендации по управлению мониторингом см. в файле **[Модули управления мониторингом и observability](./ansible_monitoring_modules.md)**.

### Бэкапы

- **Шифрование**: Используйте `password` для шифрования репозитория Borg/Restic.
- **Prune**: Настраивайте политику хранения (`keep_daily`, `keep_weekly`, `keep_monthly`) через `state: pruned`.
- **Восстановление**: Тестируйте restore регулярно: `restic restore --dry-run`, `borg extract --dry-run`.
- **Изоляция**: Для air-gapped сред используйте `rest` сервер (Borg/Restic) или локальное хранилище с шифрованием.

### Очереди сообщений

- **Replication**: Для Kafka используйте `replication_factor >= 3` для production.
- **Persistence**: Для RabbitMQ настраивайте `durable: yes` и `delivery_mode=2` для критичных сообщений.
- **Мониторинг**: Экспортируйте метрики Kafka (`jmx_exporter`) и RabbitMQ (`rabbitmq_prometheus` plugin).

### Безопасность

- **Минимальные привилегии**: Создавайте пользователей БД только с необходимыми правами (`SELECT`, `INSERT` вместо `ALL`).
- **Сетевая изоляция**: Открывайте порты БД (5432, 3306) только для доверенных подсетей через `firewalld`/`ufw`.
- **Аудит**: Включайте логирование PostgreSQL (`log_statement = 'all'`), экспортируйте в Loki/ELK.
- **Секреты**: Никогда не храните пароли в открытом виде. Используйте Ansible Vault или внешние секреты-менеджеры.

## Дополнительная информация

- **[Развертывание PostgreSQL через Ansible](../../Ansible/examples/example_postgresql_setup.md)** — полный цикл установки PostgreSQL.
- **[Мониторинг PostgreSQL через Ansible](../../Ansible/examples/postgresql_prometheus_monitoring.md)** — настройка Prometheus + Grafana для PostgreSQL.
- **[Развертывание MySQL/MariaDB через Ansible](../../Ansible/examples/mysql_setup.md)** — полный цикл установки MySQL.
- **[Развертывание MongoDB через Ansible](../../Ansible/examples/mongodb_setup.md)** — развертывание Replica Set MongoDB.
- **[Модули управления базами данных](../../Databases/)** — обзор всех баз данных в базе знаний.
- **[Модули управления веб-серверами](../../WebServers/)** — Nginx, Apache, HAProxy, Traefik.
- **[Модули управления мониторингом](../../Prometheus/)** — Prometheus, exporters, Grafana.
- **[Модули управления бэкапами](../../Linux/SystemAdministration/backup_and_recovery.md)** — бэкапы в Linux.
- **[Антипаттерны Ansible](../ansible_bad_practices.md)** — частые ошибки при работе с модулями.
- **[Основные концепции Ansible](../ansible_core_concepts.md)** — архитектура и идемпотентность.
- **[Кроссплатформенные концепции](../CrossPlatform/concepts.md)** — различия между ОС.
- **[Официальная документация community.postgresql](https://docs.ansible.com/ansible/latest/collections/community/postgresql/)** — полный список модулей.
- **[Официальная документация ansible.mysql](https://docs.ansible.com/ansible/latest/collections/ansible/mysql/)** — полный список модулей.
- **[Официальная документация prometheus.prometheus](https://docs.ansible.com/ansible/latest/collections/prometheus/prometheus/)** — установка Prometheus и exporters.
