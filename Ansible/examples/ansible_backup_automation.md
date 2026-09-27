# Автоматизация резервного копирования через Ansible

## Определения

**Резервное копирование (backup)** — процесс создания копий данных (файлов, конфигураций, баз данных) для восстановления после сбоев, ошибок человека или атак. В контексте Ansible это означает автоматизацию создания, проверки и хранения бэкапов на управляемых хостах.

**Snapshot** — моментальный снимок состояния файловой системы или тома, который создается быстро и позволяет откатиться на предыдущее состояние без долгого копирования файлов. В production-среде часто используется для бэкапов баз данных и конфигураций.

**RPO (Recovery Point Objective)** — максимально допустимый интервал потери данных, определяющий, как часто нужно создавать бэкапы. Например, RPO=1h означает, что при сбое можно потерять не более часа данных.

**RTO (Recovery Time Objective)** — максимально допустимое время восстановления после сбоя. Определяет, как быстро должен работать процесс восстановления из бэкапа.

**Immutability** — свойство бэкапа, при котором он не может быть изменен или удален после создания. В контексте on-prem инфраструктуры это означает настройку WORM (Write Once Read Many) хранилища, snapshot-режим LVM/ZFS или lifecycle policies на локальном NAS.

**Point-in-time recovery** — возможность восстановить данные на произвольный момент времени, обычно реализуется через комбинацию полных бэкапов и WAL (Write-Ahead Log) архивов.

**Deduplication** — механизм сокращения объема хранения, при котором идентичные блоки данных хранятся единожды. В Ansible это может означать настройку бэкапов с дедупликацией на уровне хранилища или через Restic/BorgBackup.

**Air-gap backup** — бэкап, хранящийся на изолированном носителе или в сети, недоступной из production-сегмента. Критичен для защиты от ransomware.

**LUKS (Linux Unified Key Setup)** — стандарт шифрования дисков в Linux. Шифрование внешних носителей для бэкапов обеспечивает конфиденциальность при физической утере носителя.

## Базовые концепции

### Типы бэкапов

| Тип | Описание | Преимущества | Недостатки |
|---|---|---|---|
| **Полный бэкап (Full)** | Копия всех данных | Быстрое восстановление | Медленное создание, много места |
| **Инкрементальный (Incremental)** | Только изменения с последнего бэкапа | Быстрое создание, мало места | Медленное восстановление |
| **Дифференциальный (Differential)** | Все изменения с последнего полного бэкапа | Средняя скорость восстановления | Средний объем |
| **Снимок (Snapshot)** | Моментальный снимок тома | Мгновенное создание | Требует поддержки файловой системы |

### Жизненный цикл бэкапа

1. **Планирование** — определение RPO/RTO, частоты бэкапов, retention policy, maintenance windows.
2. **Создание** — выполнение бэкапа через Ansible tasks с учетом serial/throttle для production.
3. **Валидация** — проверка целостности бэкапа (checksum, пробное восстановление, pg_restore --list).
4. **Хранение** — размещение бэкапа в хранилище (локальное, NFS, CIFS/SMB, iSCSI, LTO tape).
5. **Ротация** — удаление устаревших бэкапов согласно retention policy.
6. **Мониторинг** — отслеживание статуса создания бэкапов, отправка алертов при ошибках, аудит изменений.

### Архитектура хранения бэкапов

```
Managed Nodes
    ├── Файлы конфигураций (/etc)
    ├── Данные приложений (/var/lib)
    ├── Базы данных (dump / WAL)
    │       ↓
    │   [Ansible Control Node / Bastion]
    │       ↓
    │   [Internal NAS / NFS / CIFS]
    │       ↓
    │   [LTO Tape / Disk Shelf (air-gap)]
    │       ↓
    [Monitoring / Alerting]
    ├── Prometheus node_exporter
    ├── Alertmanager
    └── Audit log → SIEM
```

**Для SRE:** управление бэкапами через Ansible обеспечивает:
- **Идемпотентность** — повторный запуск не ломает конфигурацию хранения бэкапов
- **Change management** — обновление скриптов бэкапов проходит через maintenance windows с `serial` и `throttle`
- **Auditability** — все изменения фиксируются в Git, интеграция с SIEM через centralized logging
- **Verification** — каждый бэкап проверяется на целостность автоматически

### Предварительные требования

| Компонент | Минимальная версия | Проверка |
|---|---|---|
| Ansible Core | 2.21+ | `ansible --version` |
| Python (control node) | 3.12+ | `python3 --version` |
| Python (managed) | 3.11+ | `python3 --version` |
| Restic | 0.19+ | `restic version` |
| BorgBackup | 1.4+ | `borg --version` |
| PostgreSQL | 14+ | `pg_dump --version` |
| MySQL / MariaDB | 8.0+ / 10.5+ | `mysqldump --version` / `mariadb-dump --version` |
| community.general | 13.0+ | `ansible-galaxy collection list community.general` |
| community.postgresql | 3.0+ | `ansible-galaxy collection list community.postgresql` |

### Ключевые принципы

1. **3-2-1 rule** — 3 копии данных, 2 носителя, 1 копия offsite/air-gap.
2. **Automated validation** — каждый бэкап должен проверяться на целостность автоматически.
3. **Encryption at rest** — бэкапы должны шифроваться, особенно на съемных/air-gap носителях.
4. **Separation of duties** — доступ к бэкапам должен быть ограничен отдельной группой.
5. **Documentation** — каждый бэкап должен иметь документацию по восстановлению (runbook).

## Практические сценарии

### Сценарий 1: Бэкап конфигураций и данных с помощью Restic

Restic — быстрый, эффективный инструмент бэкапов с дедупликацией и шифрованием. В Ansible используется через модуль `community.general.restic`.

```yaml
---
- name: Настройка резервного копирования с Restic
  hosts: all
  become: true
  vars:
    restic_version: "0.19.1"
    backup_repository: "rest:http://backup.internal:8000/backup"
    backup_password: "{{ vault_restic_password }}"
    backup_paths:
      - /etc
      - /var/lib
    exclude_paths:
      - /var/cache
      - /var/log
    retention_daily: 7
    retention_weekly: 4
    retention_monthly: 12
    backup_tags:
      - "ansible-managed"
      - "{{ ansible_hostname }}"

  tasks:
    - name: Установка Restic
      ansible.builtin.unarchive:
        src: "https://github.com/restic/restic/releases/download/v{{ restic_version }}/restic_{{ restic_version }}_linux_amd64.bz2"
        dest: /usr/local/bin/
        remote_src: yes
        creates: /usr/local/bin/restic

    - name: Инициализация репозитория Restic
      community.general.restic:
        repo: "{{ backup_repository }}"
        password: "{{ backup_password }}"
        state: initialized

    - name: Создание snapshot
      community.general.restic:
        repo: "{{ backup_repository }}"
        password: "{{ backup_password }}"
        paths: "{{ backup_paths }}"
        exclude_paths: "{{ exclude_paths }}"
        tags: "{{ backup_tags }}"
        state: snapshotted
      register: restic_snapshot

    - name: Ротация старых snapshot'ов
      community.general.restic:
        repo: "{{ backup_repository }}"
        password: "{{ backup_password }}"
        keep_daily: "{{ retention_daily }}"
        keep_weekly: "{{ retention_weekly }}"
        keep_monthly: "{{ retention_monthly }}"
        state: pruned

    - name: Проверка целостности репозитория
      community.general.restic:
        repo: "{{ backup_repository }}"
        password: "{{ backup_password }}"
        state: checked
```

**Валидация:**

```bash
# Проверка snapshot'ов
restic snapshots --repo rest:http://backup.internal:8000/backup
# → ID        Date             Host        Tags  Paths
# → a1b2c3d4  2026-09-26 02:00 web01       []    /etc, /var/lib

# Проверка последнего бэкапа
restic ls latest --repo rest:http://backup.internal:8000/backup
# → показывает содержимое последнего бэкапа

# Пробное восстановление
restic restore latest --target /tmp/restore-test --repo rest:http://backup.internal:8000/backup
# → восстанавливает бэкап во временную директорию

# Проверка целостности
restic check --repo rest:http://backup.internal:8000/backup
# → no errors were found
```

### Сценарий 2: Бэкап баз данных PostgreSQL

Автоматизация дампа баз данных с ротацией и проверкой целостности. Подробные сценарии см. в **[Автоматизация PostgreSQL с помощью Ansible](../examples/example_postgresql_setup.md)**.

```yaml
---
- name: Бэкап PostgreSQL баз данных
  hosts: db_servers
  become: true
  vars:
    pg_version: "16"
    backup_dir: "/var/backups/postgresql"
    retention_days: 7
    databases:
      - app_production
      - app_staging
    pg_user: "postgres"
    backup_owner: "postgres"
    backup_group: "postgres"

  tasks:
    - name: Установка утилит PostgreSQL
      ansible.builtin.package:
        name:
          - postgresql-{{ pg_version }}
          - postgresql-client-{{ pg_version }}
        state: present

    - name: Создание директории для бэкапов
      ansible.builtin.file:
        path: "{{ backup_dir }}"
        state: directory
        mode: '0700'
        owner: "{{ backup_owner }}"
        group: "{{ backup_group }}"
        setype: "postgresql_db_t"

    - name: Создание дампа баз данных
      ansible.builtin.command: >
        pg_dump -U {{ pg_user }}
        --format=custom
        --compress=9
        --file={{ backup_dir }}/{{ item }}_{{ ansible_date_time.date }}.dump {{ item }}
      loop: "{{ databases }}"
      register: pg_dump_result
      changed_when: "'dump' in pg_dump_result.stdout"

    - name: Проверка целостности дампа
      ansible.builtin.command: pg_restore --list {{ backup_dir }}/{{ item }}_{{ ansible_date_time.date }}.dump > /dev/null
      loop: "{{ databases }}"
      register: pg_restore_check
      changed_when: false
      failed_when: pg_restore_check.rc != 0

    - name: Удаление старых бэкапов
      ansible.builtin.find:
        paths: "{{ backup_dir }}"
        patterns: "*.dump"
        age: "{{ retention_days }}d"
      register: old_backups

    - name: Удаление старых файлов
      ansible.builtin.file:
        path: "{{ item.path }}"
        state: absent
      loop: "{{ old_backups.files }}"

    - name: Создание systemd таймера для автоматических бэкапов
      ansible.builtin.copy:
        dest: /etc/systemd/system/postgresql-backup.service
        content: |
          [Unit]
          Description=PostgreSQL backup
          After=postgresql.service

          [Service]
          Type=oneshot
          ExecStart=/usr/bin/ansible-playbook /etc/ansible/playbooks/backup_postgres.yml
          User=postgres
        mode: '0644'

    - name: Создание systemd таймера
      ansible.builtin.copy:
        dest: /etc/systemd/system/postgresql-backup.timer
        content: |
          [Unit]
          Description=Daily PostgreSQL backup

          [Timer]
          OnCalendar=daily
          Persistent=true

          [Install]
          WantedBy=timers.target
        mode: '0644'

    - name: Включение таймера
      ansible.builtin.systemd:
        name: postgresql-backup.timer
        state: started
        enabled: true
```

**Валидация:**

```bash
# Проверка создания бэкапов
ls -la /var/backups/postgresql/
# → app_production_2026-09-26.dump, app_staging_2026-09-26.dump

# Проверка целостности
pg_restore --list /var/backups/postgresql/app_production_2026-09-26.dump | head -20
# → показывает список объектов в дампе

# Проверка таймера
systemctl list-timers | grep postgresql
# → показывает, когда следующий бэкап
```

### Сценарий 3: Бэкап баз данных MySQL/MariaDB

Регулярное резервное копирование — ключевая задача SRE. Подробный сценарий см. в **[Автоматизация MySQL/MariaDB с помощью Ansible](../examples/mysql_setup.md)**.

```yaml
---
- name: Бэкап MySQL/MariaDB баз данных
  hosts: db_servers
  become: true
  vars:
    backup_dir: "/var/backups/mysql"
    retention_days: 7
    databases:
      - app_production
      - app_staging
    mysql_user: "root"
    mysql_password: "{{ vault_mysql_root_password }}"
    backup_owner: "mysql"
    backup_group: "mysql"

  tasks:
    - name: Установка клиента MySQL
      ansible.builtin.package:
        name:
          - mysql-client
          - pigz
        state: present

    - name: Создание директории для бэкапов
      ansible.builtin.file:
        path: "{{ backup_dir }}"
        state: directory
        mode: '0700'
        owner: "{{ backup_owner }}"
        group: "{{ backup_group }}"

    - name: Создание дампа баз данных
      ansible.builtin.command: >
        mysqldump -u {{ mysql_user }} -p{{ mysql_password }}
        --single-transaction
        --routines
        --triggers
        --events
        --all-databases
        | pigz > {{ backup_dir }}/backup_{{ ansible_date_time.date }}.sql.gz
      register: mysql_dump_result
      changed_when: "'mysqldump: Got' in mysql_dump_result.stdout or mysql_dump_result.rc == 0"
      no_log: true

    - name: Удаление старых бэкапов
      ansible.builtin.find:
        paths: "{{ backup_dir }}"
        patterns: "*.sql.gz"
        age: "{{ retention_days }}d"
      register: old_backups

    - name: Удаление старых файлов
      ansible.builtin.file:
        path: "{{ item.path }}"
        state: absent
      loop: "{{ old_backups.files }}"

    - name: Проверка целостности последнего бэкапа
      ansible.builtin.command: pigz -d < {{ backup_dir }}/backup_{{ ansible_date_time.date }}.sql.gz | head -5
      register: mysql_backup_check
      changed_when: false
```

### Сценарий 4: Бэкап с использованием BorgBackup

BorgBackup — инструмент бэкапов с дедупликацией и шифрованием, подходящий для production. В Ansible используется через модуль `community.general.borg`. Подробнее о модулях см. в **[Модули инфраструктуры](../Modules/ansible_infrastructure_modules.md)**.

```yaml
---
- name: Настройка бэкапов с BorgBackup
  hosts: all
  become: true
  vars:
    borg_repo: "/mnt/backup/borg-repo"
    borg_passphrase: "{{ vault_borg_passphrase }}"
    backup_paths:
      - /etc
      - /var/lib
    exclude_patterns:
      - /var/cache/**
      - /var/log/**
    retention_daily: 7
    retention_weekly: 4
    retention_monthly: 12

  tasks:
    - name: Установка BorgBackup
      ansible.builtin.package:
        name: borgbackup
        state: present

    - name: Создание директории репозитория
      ansible.builtin.file:
        path: "{{ borg_repo }}"
        state: directory
        mode: '0700'
        owner: root
        group: root

    - name: Инициализация репозитория Borg
      community.general.borg:
        repo: "{{ borg_repo }}"
        password: "{{ borg_passphrase }}"
        state: initialized
        encryption: repokey

    - name: Создание бэкапа
      community.general.borg:
        repo: "{{ borg_repo }}"
        password: "{{ borg_passphrase }}"
        paths: "{{ backup_paths }}"
        exclude_from: /tmp/borg-exclude.txt
        compression: lz4
        state: snapshotted

    - name: Ротация бэкапов
      community.general.borg:
        repo: "{{ borg_repo }}"
        password: "{{ borg_passphrase }}"
        keep_daily: "{{ retention_daily }}"
        keep_weekly: "{{ retention_weekly }}"
        keep_monthly: "{{ retention_monthly }}"
        state: pruned

    - name: Проверка репозитория
      community.general.borg:
        repo: "{{ borg_repo }}"
        password: "{{ borg_passphrase }}"
        state: checked
```

**Валидация:**

```bash
# Проверка списка бэкапов
BORG_PASSPHRASE="password" borg list /mnt/backup/borg-repo
# → показывает список архивов

# Проверка последнего бэкапа
BORG_PASSPHRASE="password" borg list /mnt/backup/borg-repo::2026-09-26-02
# → показывает содержимое архива

# Пробное восстановление
BORG_PASSPHRASE="password" borg extract /mnt/backup/borg-repo::2026-09-26-02 /etc/nginx/nginx.conf
# → восстанавливает конкретный файл

# Проверка целостности
BORG_PASSPHRASE="password" borg check /mnt/backup/borg-repo
# → проверяет целостность репозитория
```

### Сценарий 5: Файловые системы и LVM snapshots

Бэкап файловых систем с использованием LVM snapshots для атомарного снимка состояния тома. Подходит для баз данных и больших файловых систем.

```yaml
---
- name: Бэкап файловых систем с LVM snapshots
  hosts: db_servers
  become: true
  vars:
    vg_name: "vg_data"
    lv_name: "lv_app"
    mount_point: "/var/lib/app"
    snapshot_size: "5G"
    backup_dir: "/var/backups/lvm"
    retention_days: 7

  tasks:
    - name: Создание директории для бэкапов
      ansible.builtin.file:
        path: "{{ backup_dir }}"
        state: directory
        mode: '0700'
        owner: root
        group: root

    - name: Создание LVM snapshot
      community.general.lvol:
        vg: "{{ vg_name }}"
        lv: "{{ lv_name }}_snapshot"
        size: "{{ snapshot_size }}"
        state: present

    - name: Монтирование snapshot
      ansible.builtin.mount:
        path: "/mnt/snapshot"
        src: "/dev/{{ vg_name }}/{{ lv_name }}_snapshot"
        fstype: ext4
        state: mounted

    - name: Создание архива snapshot
      ansible.builtin.command: >
        tar czf {{ backup_dir }}/{{ lv_name }}_{{ ansible_date_time.date }}.tar.gz
        -C /mnt/snapshot .
      register: tar_result
      changed_when: tar_result.rc == 0

    - name: Отмонтирование snapshot
      ansible.builtin.mount:
        path: "/mnt/snapshot"
        state: absent

    - name: Удаление LVM snapshot
      community.general.lvol:
        vg: "{{ vg_name }}"
        lv: "{{ lv_name }}_snapshot"
        state: absent

    - name: Удаление старых бэкапов
      ansible.builtin.find:
        paths: "{{ backup_dir }}"
        patterns: "*.tar.gz"
        age: "{{ retention_days }}d"
      register: old_backups

    - name: Удаление старых файлов
      ansible.builtin.file:
        path: "{{ item.path }}"
        state: absent
      loop: "{{ old_backups.files }}"
```

### Сценарий 6: Верификация и тестирование Disaster Recovery

Каждый бэкап должен проверяться на целостность. SRE практика: автоматическое пробное восстановление на staging-хосте.

```yaml
---
- name: Верификация бэкапов и DR тестирование
  hosts: backup_validators
  become: true
  vars:
    backup_mount_point: "/mnt/backup-restore"
    restore_target: "/tmp/restore-test"
    validation_databases:
      - app_production

  tasks:
    - name: Создание директории для восстановления
      ansible.builtin.file:
        path: "{{ restore_target }}"
        state: directory
        mode: '0750'

    - name: Восстановление PostgreSQL дампа
      ansible.builtin.command: >
        pg_restore --clean --create
        --dbname=postgres
        {{ backup_mount_point }}/{{ item }}_{{ ansible_date_time.date }}.dump
      loop: "{{ validation_databases }}"
      register: pg_restore_result
      changed_when: false

    - name: Проверка конфигурации Nginx
      ansible.builtin.command: nginx -t -c {{ restore_target }}/etc/nginx/nginx.conf
      register: nginx_check
      changed_when: false

    - name: Отчет о верификации
      ansible.builtin.debug:
        msg: |
          PostgreSQL restore: {{ 'PASS' if pg_restore_result.rc == 0 else 'FAIL' }}
          Nginx config: {{ 'PASS' if nginx_check.rc == 0 else 'FAIL' }}
```

## Операции и команды

### Основные команды для управления бэкапами

| Команда | Назначение | Пример |
|---|---|---|
| `restic snapshots` | Список бэкапов | `restic snapshots --repo rest:http://backup:8000` |
| `restic check` | Проверка целостности | `restic check --repo rest:http://backup:8000` |
| `restic forget --prune` | Ротация бэкапов | `restic forget --keep-daily 7 --prune --repo rest:http://backup:8000` |
| `borg list` | Список архивов | `borg list /mnt/backup/borg-repo` |
| `borg check` | Проверка репозитория | `borg check /mnt/backup/borg-repo` |
| `borg prune` | Ротация архивов | `borg prune --keep-daily=7 /mnt/backup/borg-repo` |
| `pg_dump` | Дамп PostgreSQL | `pg_dump -U postgres app_production > backup.dump` |
| `pg_restore --list` | Проверка дампа | `pg_restore --list backup.dump` |
| `mysqldump` | Дамп MySQL | `mysqldump -u root app_production > backup.sql` |
| `tar czf` | Создание архива | `tar czf backup.tar.gz /etc /var/lib` |
| `lvm lvcreate -L` | Создание snapshot | `lvcreate -L 5G -s -n lv_snapshot /dev/vg/lv` |
| `rsync -a` | Синхронизация файлов | `rsync -a --delete /etc /mnt/nfs/backup/etc` |

### Команды для проверки бэкапов

| Команда | Назначение | Пример |
|---|---|---|
| `restic restore --dry-run` | Проверка восстановления | `restic restore latest --dry-run` |
| `borg extract --dry-run` | Проверка извлечения | `borg extract --dry-run repo::archive` |
| `pg_restore --list` | Проверка дампа PostgreSQL | `pg_restore --list backup.dump` |
| `tar tzf` | Просмотр архива | `tar tzf backup.tar.gz` |
| `sha256sum` | Проверка checksum | `sha256sum backup.tar.gz` |
| `gpg --verify` | Проверка подписи | `gpg --verify backup.tar.gz.sig backup.tar.gz` |

## Устранение типичных неполадок

| Ошибка | Причина | Решение |
|---|---|---|
| `Restic: unable to open repository` | Неверный URL или пароль | Проверьте `RESTIC_REPOSITORY` и `RESTIC_PASSWORD` |
| `Borg: Repository is not initialized` | Репозиторий не инициализирован | Запустите `borg init` |
| `pg_dump: connection to database failed` | PostgreSQL недоступен | Проверьте `systemctl status postgresql` |
| `mysqldump: Got error` | Неверные учетные данные или lock | Используйте `--single-transaction` для InnoDB |
| `Backup integrity check failed` | Поврежденный бэкап | Проверьте `restic check` или `borg check`, создайте новый бэкап |
| `Insufficient disk space` | Недостаточно места | Увеличьте место или настройте cleanup |
| `Backup too slow` | Большой объем или медленное хранилище | Используйте инкрементальные бэкапы, снимки, `pigz` |
| `Encryption key lost` | Утерян пароль/ключ шифрования | Храните ключи в HashiCorp Vault, используйте escrow |
| `LVM snapshot failed` | Недостаточно места в VG | Увеличьте размер `snapshot_size` или очистите VG |
| `Lock timeout` | Блокировка файлов/СУБД | Увеличьте `lock_timeout`, используйте `--single-transaction` |

## Рекомендации

### Best Practices

1. **3-2-1 rule** — 3 копии данных, 2 носителя, 1 копия air-gap/offsite.
2. **Automated validation** — каждый бэкап должен проверяться на целостность автоматически.
3. **Encryption at rest** — шифруйте бэкапы, особенно на съемных и air-gap носителях.
4. **Separation of duties** — доступ к бэкапам должен быть ограничен отдельной группой.
5. **Documentation** — каждый бэкап должен иметь runbook по восстановлению.
6. **Regular testing** — регулярно тестируйте восстановление из бэкапов (как минимум раз в квартал).
7. **Monitoring** — мониторьте статус создания бэкапов и отправляйте алерты при ошибках.
8. **Change management** — обновляйте скрипты бэкапов через maintenance windows с `serial` и `throttle`.
9. **Retention policy** — настраивайте ротацию согласно RPO/RTO и compliance требованиям.
10. **Audit** — все изменения бэкапов фиксируются в Git, ведется журнал пакетных изменений.

### Чек-лист валидации после настройки

| Проверка | Команда | Ожидаемый результат |
|---|---|---|
| Restic инициализирован | `restic snapshots` | Список снапшотов пуст или содержит предыдущие |
| Создание бэкапа | `restic snapshots` после запуска | Появляется новый снапшот |
| Целостность бэкапа | `restic check` | `no errors were found` |
| Borg репозиторий | `borg list /mnt/backup/borg-repo` | Список архивов |
| Пробное восстановление | `restic restore latest --target /tmp/restore-test` | Файлы восстанавливаются без ошибок |
| Дамп PostgreSQL | `pg_restore --list backup.dump` | Список объектов в дампе |
| Дамп MySQL | `pigz -d < backup.sql.gz | head -5` | Начало SQL дампа |
| Checksum | `sha256sum backup.tar.gz` | Контрольная сумма совпадает |
| Systemd таймер | `systemctl list-timers | grep backup` | Таймер активен |
| Журнал бэкапов | `journalctl -u postgresql-backup.service` | Нет ошибок |

## Дополнительная информация

### Смотрите также

- **[Модули инфраструктуры Ansible](../Modules/ansible_infrastructure_modules.md)** — `community.general.borg`, `community.general.restic`, `community.general.rclone`, параметры модулей, примеры использования.
- **[Автоматизация PostgreSQL с помощью Ansible](../examples/example_postgresql_setup.md)** — полный сценарий бэкапа PostgreSQL, репликация, восстановление.
- **[Рекомендации по безопасности Ansible](../ansible_security_best_practices.md)** — управление ключами шифрования, хранение секретов.

### Интеграция с другими системами

| Система | Назначение | Интеграция |
|---|---|---|
| **NFS / CIFS** | Сетевое хранилище | Restic/Borg → NAS |
| **LTO Tape** | Долгосрочное air-gap хранение | borg → tape via `mt` |
| **HashiCorp Vault** | Управление ключами | Vault → Restic/Borg encryption keys |
| **Prometheus** | Мониторинг бэкапов | Внешние скрипты → node_exporter metrics |
| **Alertmanager** | Алерты | Monitoring → Alertmanager |
| **ELK / Loki** | Централизованный аудит | Backup logs → SIEM |

### Граничные случаи

| Сценарий | Проблема | Решение |
|---|---|---|
| Большой объем данных | Бэкап занимает много времени | Используйте LVM snapshots, инкрементальные бэкапы, дедупликацию |
| Ограниченная пропускная способность | Передача по сети занимает много времени | Используйте сжатие `pigz`/`zstd`, инкрементальные бэкапы |
| Утерян ключ шифрования | Невозможно восстановить бэкап | Храните ключи в Vault, используйте key escrow, multi-sig |
| Бэкап не прошел проверку | Целостность compromised | Создайте новый бэкап, проверьте storage, проведите forensic |
| Отсутствие air-gap копии | Риск потери данных при ransomware | Настройте автоматическую репликацию на изолированный носитель |
| Concurrent backup runs | Два бэкапа запущены одновременно | Используйте `flock` или `lock_timeout` в systemd service |
