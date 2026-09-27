# Проверка целостности файлов в Linux

## Определения

**Проверка целостности файлов (File Integrity Checking)** — процесс подтверждения того, что системные файлы, исполняемые бинарные файлы и конфигурации не подвергались несанкционированному изменению. Это критический компонент стратегии защиты, позволяющий обнаружить последствия взлома, внедрение руткитов или бэкдоров.

При компрометации системы злоумышленники часто подменяют стандартные утилиты (например, `ls`, [`ps`](../../Diagnostics/Processes/ps.md), `top`, `ss`, `login`) для сокрытия своих процессов, сетевых соединений или создания скрытых каналов доступа. Регулярная проверка целостности позволяет выявить такие аномалии, даже если злоумышленник получил права `root`.

## Основные концепции

Проверка целостности в современных Linux-системах реализуется на нескольких уровнях:

1.  **Пользовательский уровень (База данных пакетов):** Менеджеры пакетов (`APT`, `RPM`) хранят контрольные суммы файлов, установленных из официальных репозиториев. Это быстрый способ проверить "чистоту" системных утилит.
2.  **Пользовательский уровень (HIDS — Host-based Intrusion Detection System):** Инструменты типа **AIDE** или **Tripwire** создают локальную базу данных (снимки) атрибутов файлов (хеши, права, владельцы). Проверка заключается в сравнении текущего состояния с доверенным эталоном.
3.  **Ядерный уровень (IMA/EVM):**
    *   **IMA (Integrity Measurement Architecture):** Компонент ядра Linux, который измеряет (хеширует) файлы перед их открытием для чтения или выполнением. Результаты (measurements) могут сохраняться в аппаратном модуле **TPM**, что гарантирует невозможность подделки лога проверки.
    *   **EVM (Extended Verification Module):** Защищает расширенные атрибуты файлов (xattrs), такие как контрольные суммы, права доступа и метки SELinux, от изменений в офлайн-режиме (например, при монтировании диска в другой системе).
4.  **Непрерывный мониторинг (FIM в SIEM/XDR):** Платформы вроде **Wazuh** используют механизмы ядра (inotify, auditd) для отслеживания изменений в реальном времени. Это позволяет мгновенно узнать не только о факте изменения, но и о том, какой пользователь и какой процесс внесли правки.

## Практические сценарии

### 1. Проверка через пакетные менеджеры (Первая линия обороны)

Самый быстрый способ проверить, были ли изменены файлы, установленные штатными средствами дистрибутива.

#### DEB-системы (Debian, Ubuntu, Kali)
Используется утилита `debsums`. Если она не установлена: `sudo apt install debsums`.

```bash
# Проверка всех файлов всех пакетов (показывает только ошибки)
sudo debsums -s

# Проверка конкретного пакета
sudo debsums -s coreutils
# → result: /bin/ls: FAILED (если файл изменен)

# Проверка только бинарных файлов (игнорируя конфигурации)
sudo debsums -a
```

#### RPM-системы (RHEL, CentOS, Rocky, Fedora)

Функционал встроен в команду `rpm`. Подробное описание флагов верификации и расшифровка кодов приведено в **[Анализ и получение пакетов](../Linux/PackageManagement/package_analysis.md#rpm-верификация)**.

```bash
# Полная проверка всех файлов системы
sudo rpm -Va

# Проверка конкретной утилиты
sudo rpm -V coreutils | grep '/bin/ls'
```

### 2. Глубокий аудит с помощью AIDE

**AIDE (Advanced Intrusion Detection Environment)** — это мощный инструмент для мониторинга любых файлов, включая те, что не управляются пакетным менеджером. В отличие от пакетных менеджеров, AIDE проверяет не только файлы из репозиториев, но и пользовательские скрипты, конфигурации, веб-приложения и любые другие критические данные.

#### 2.1 Структура и настройка конфигурации (`/etc/aide/aide.conf`)

Конфигурация AIDE состоит из трех разделов: **Database**, **Rules** и **Macros/Definitions**. Понимание этой структуры критично для эффективного мониторинга.

```bash
# === МАКРОСЫ (определения групп атрибутов) ===
# p  = permissions (права доступа)
# i  = inode (номер индексного дескриптора)
# n  = number of links (количество жестких ссылок)
# u  = user (владелец UID)
# g  = group (группа GID)
# s  = size (размер файла)
# b  = block count (количество блоков)
# m  = mtime (время модификации содержимого)
# a  = atime (время последнего доступа)
# c  = ctime (время изменения метаданных)
# S  = check growing files (проверка только роста, игнорируем усечение)
# md5/sha1/sha256/sha512/rmd160/tiger/whirlpool = хеш-функции

# Предустановленные макросы (Debian/Ubuntu):
# FIPSR  = p+i+n+u+g+s+m+c+md5+sha256    (полная проверка для критичных файлов)
# NORMAL = FIPSR+sha512                   (расширенная)
# DATAONLY = p+u+g+i+n+s+b+m+c+sha256     (только данные, без atime)
# CONFIG   = p+i+n+u+g+s+m+c+md5+sha256   (конфигурационные файлы)
# LOG      = p+i+n+u+g+s+b+m+c            (логи — проверяем рост)
# LSPP     = FIPSR+sha512+rmd160+tiger    (профиль LSPP/Common Criteria)
```

**Собственные правила (Rules):**
Синтаксис: `путь/к/файлу  макрос_или_атрибуты`

```bash
# === ПРИМЕР ПОЛНОЙ КОНФИГУРАЦИИ (/etc/aide/aide.conf.d/custom.conf) ===

# 1. Критичные системные бинарники — полная проверка (FIPSR)
/boot                              FIPSR
/sbin                              FIPSR
/bin                               FIPSR
/usr/bin                           FIPSR
/usr/sbin                          FIPSR
/usr/lib                           FIPSR
/usr/lib64                         FIPSR
/lib                               FIPSR
/lib64                             FIPSR

# 2. Конфигурационные файлы — проверка изменений содержимого и метаданных
/etc                               CONFIG

# Исключения для часто меняющихся файлов в /etc
!/etc/mtab
!/etc/adjtime
!/etc/ld.so.cache
!/etc/udev/hwdb.bin
!/etc/passwd-
!/etc/group-
!/etc/shadow-
!/etc/gshadow-
!/etc/*.bak
!/etc/*.orig
!/etc/*.dpkg-*
!/etc/*.rpmnew
!/etc/*.rpmsave

# 3. SSH ключи и конфигурация — строгая проверка
/etc/ssh                           FIPSR
!/etc/ssh/ssh_host_*_key           # Приватные ключи хоста меняются при регенерации
!/etc/ssh/ssh_host_*_key.pub

# 4. Веб-приложения и пользовательские данные — проверка данных
/var/www                           DATAONLY
# Исключаем загружаемые пользователями файлы и кэш
!/var/www/html/uploads
!/var/www/html/cache
!/var/www/html/tmp
!/var/www/html/.git

# 5. Лог-файлы — проверяем только рост (добавление строк), игнорируем ротацию
/var/log                           LOG
!/var/log/*.gz
!/var/log/*.old
!/var/log/*.log.[0-9]*
!/var/log/journal

# 6. Cron и systemd — критично для персистентности
/etc/cron*                         FIPSR
/etc/systemd                       FIPSR
/usr/lib/systemd                   FIPSR
/etc/init.d                        FIPSR

# 7. Пользовательские скрипты и инструменты администрирования
/usr/local/bin                     FIPSR
/usr/local/sbin                    FIPSR
/opt                               FIPSR

# 8. Игнорирование временных и runtime директорий
!/proc
!/sys
!/dev
!/run
!/tmp
!/var/tmp
!/var/lib/docker
!/var/lib/containers
!/var/cache
!/var/spool
!/home/*/.cache
!/root/.cache
```

#### 2.2 Расширенные правила с регулярными выражениями

AIDE поддерживает POSIX расширенные регулярные выражения для сложных паттернов:

```bash
# === ПРОДВИНУТЫЕ ПАТТЕРНЫ ===

# Мониторинг всех .conf файлов в поддиректориях /etc
/etc/.*\.conf$                     CONFIG

# Исключение всех файлов в /etc, заканчивающихся на ~ или .bak
!/etc/.*[~]$
!/etc/.*\.bak$

# Мониторинг только исполняемых файлов в /usr/local (регулярка для ELF)
# Примечание: AIDE не проверяет MIME-тип, но можно ограничить по расширению
/usr/local/bin/.*                  FIPSR
/usr/local/sbin/.*                 FIPSR

# Исключение директорий с динамическим содержимым (regex)
!/var/lib/apt/lists/.*
!/var/lib/dpkg/info/.*
!/var/lib/systemd/timers/.*
!/var/lib/AccountsService/.*

# Мониторинг изменений в sudoers.d с атрибуцией
/etc/sudoers.d/.*                  FIPSR

# Docker/Containerd — только метаданные конфигурации, не слои
/etc/docker                        CONFIG
/etc/containerd                    CONFIG
!/var/lib/docker/overlay2
!/var/lib/containerd/io.containerd.metadata.v1.bolt
```

#### 2.3 Инициализация и работа с базой данных

```bash
# 1. Генерация начальной базы на чистой системе (после установки ОС и базовой настройки)
sudo aideinit -y -f
# -y: не задавать вопросы, -f: force overwrite

# Результат: /var/lib/aide/aide.db.new.gz
# Перемещаем в рабочую:
sudo mv /var/lib/aide/aide.db.new.gz /var/lib/aide/aide.db.gz

# 2. Проверка конфигурации перед запуском (валидация синтаксиса)
sudo aide --config-check /etc/aide/aide.conf

# 3. Запуск проверки (сравнение текущего состояния с базой)
sudo aide --check
# Коды возврата:
# 0 — изменений нет
# 1 — ошибка конфигурации/ввода-вывода
# 2 — найдены изменения (new/changed/removed files)
# 4 — ошибка чтения базы
# 8 — ошибка инициализации

# 4. Обновление базы после легитимных изменений (обновление пакетов, деплой)
sudo aide --update
# Создает aide.db.new.gz — проверьте отчет перед заменой основной базы!
sudo mv /var/lib/aide/aide.db.new.gz /var/lib/aide/aide.db.gz

# 5. Проверка конкретного пути/правила (для отладки)
sudo aide --check --verbose=5 /etc/passwd
sudo aide --check --report=changed /etc

# 6. Сравнение двух баз данных (форензика)
sudo aide --compare --database=old.db.gz --database-new=new.db.gz
```

#### 2.4 Автоматизация через systemd (современный подход)

Вместо cron рекомендуется использовать systemd timers для лучшего контроля, логирования и управления зависимостями:

```ini
# /etc/systemd/system/aide-check.service
[Unit]
Description=AIDE Integrity Check
Documentation=man:aide(1)
After=network.target
Wants=aide-update.timer

[Service]
Type=oneshot
ExecStart=/usr/bin/aide --check
# Отправляем вывод в journal и (опционально) на email
StandardOutput=journal
StandardError=journal
# Увеличиваем таймаут для больших файловых систем
TimeoutSec=3600
Nice=10
IOSchedulingClass=best-effort
IOSchedulingPriority=7
MemoryLimit=512M

[Install]
WantedBy=multi-user.target
```

```ini
# /etc/systemd/system/aide-check.timer
[Unit]
Description=Daily AIDE Integrity Check
Requires=aide-check.service

[Timer]
OnCalendar=daily
# Случайная задержка 0-4 часа для распределения нагрузки на диск
RandomizedDelaySec=4h
Persistent=true

[Install]
WantedBy=timers.target
```

```ini
# /etc/systemd/system/aide-update.service
[Unit]
Description=AIDE Database Update
Documentation=man:aide(1)
After=aide-check.service

[Service]
Type=oneshot
ExecStart=/usr/bin/aide --update
ExecStartPost=/bin/mv /var/lib/aide/aide.db.new.gz /var/lib/aide/aide.db.gz
StandardOutput=journal
StandardError=journal
TimeoutSec=3600

[Install]
WantedBy=multi-user.target
```

```ini
# /etc/systemd/system/aide-update.timer
[Unit]
Description=Weekly AIDE Database Update
Requires=aide-update.service

[Timer]
OnCalendar=weekly
Persistent=true

[Install]
WantedBy=timers.target
```

**Активация:**
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now aide-check.timer
sudo systemctl enable --now aide-update.timer

# Проверка статуса
systemctl list-timers aide-*
journalctl -u aide-check.service -f
```

#### 2.5 Управление базой данных в Git (Infrastructure as Code)

Для воспроизводимости и аудита храните эталонную базу в Git (зашифрованную):

```bash
# 1. Шифрование базы перед коммитом (GPG)
gpg --symmetric --cipher-algo AES256 /var/lib/aide/aide.db.gz
# Вводите пароль — сохраняйте его в менеджере секретов (Pass, Vault)

# 2. Добавление в репозиторий инфраструктуры
git add aide.db.gz.gpg
git commit -m "chore(security): update AIDE baseline after kernel upgrade v6.8.12"

# 3. Автоматизация через CI/CD (GitLab CI пример)
# .gitlab-ci.yml
aide_baseline_update:
  stage: security
  image: debian:stable-slim
  before_script:
    - apt-get update && apt-get install -y aide gpg
  script:
    - aide --init
    - gpg --batch --yes --passphrase "$AIDE_DB_PASS" --symmetric /var/lib/aide/aide.db.new.gz
    - mv /var/lib/aide/aide.db.new.gz.gpg aide-baseline.db.gz.gpg
    # Коммит через GitLab API или push в защищенную ветку
  rules:
    - if: $CI_PIPELINE_SOURCE == "schedule"  # Только по расписанию
    - if: $CI_COMMIT_TAG =~ /^v/             # Или при тегировании релиза
```

#### 2.6 Производительность и тюнинг на больших файловых системах

```bash
# 1. Использование быстрых хешей для первичного скрининга
# В aide.conf замените sha256 на md5+sha1 для некритичных путей:
/var/www/html                      p+i+n+u+g+s+b+m+c+md5+sha1
# sha256 оставьте только для /bin, /sbin, /usr/bin, /etc/ssh, /boot

# 2. Параллельная проверка (AIDE 0.17+)
# Используйте несколько процессов для разных файловых систем
sudo aide --check --config=/etc/aide/aide.conf.rootfs &
sudo aide --check --config=/etc/aide/aide.conf.var &
sudo aide --check --config=/etc/aide/aide.conf.opt &
wait

# 3. Ограничение I/O (ionice) и CPU (nice) в systemd unit (см. выше)
# Nice=10, IOSchedulingClass=best-effort, IOSchedulingPriority=7

# 4. Исключение больших бинарных файлов, которые не должны меняться
# (базы данных, образы ВМ, большие медиафайлы)
!/var/lib/postgresql
!/var/lib/mysql
!/var/lib/libvirt/images
!/var/lib/machines

# 5. Использование tmpfs для временных файлов AIDE
# В /etc/aide/aide.conf:
# database=file:/var/lib/aide/aide.db.gz
# database_out=file:/tmp/aide.db.new.gz  # Быстрее на tmpfs
# gzip_dbout=yes
```

#### 2.7 Интеграция с Ansible для управления конфигурацией

```yaml
# roles/aide/tasks/main.yml
- name: Install AIDE
  ansible.builtin.apt:
    name: aide
    state: present
    update_cache: yes
  when: ansible_os_family == "Debian"

- name: Install AIDE (RHEL)
  ansible.builtin.dnf:
    name: aide
    state: present
  when: ansible_os_family == "RedHat"

- name: Deploy custom AIDE configuration
  ansible.builtin.template:
    src: aide.conf.j2
    dest: /etc/aide/aide.conf.d/custom.conf
    mode: '0640'
    owner: root
    group: root
  notify: Reinitialize AIDE database

- name: Deploy systemd units for AIDE
  ansible.builtin.copy:
    src: "{{ item }}"
    dest: "/etc/systemd/system/{{ item }}"
    mode: '0644'
  loop:
    - aide-check.service
    - aide-check.timer
    - aide-update.service
    - aide-update.timer
  notify: Reload systemd and enable timers

- name: Initialize AIDE database (first run only)
  ansible.builtin.command: aideinit -y -f
  args:
    creates: /var/lib/aide/aide.db.gz
  register: aide_init

- name: Move initial database
  ansible.builtin.command: mv /var/lib/aide/aide.db.new.gz /var/lib/aide/aide.db.gz
  when: aide_init.changed

- name: Verify AIDE configuration
  ansible.builtin.command: aide --config-check
  changed_when: false
  failed_when: false
  register: aide_config_check

- name: Assert configuration is valid
  ansible.builtin.assert:
    that: aide_config_check.rc == 0
    fail_msg: "AIDE configuration check failed: {{ aide_config_check.stderr }}"

# handlers/main.yml
- name: Reinitialize AIDE database
  ansible.builtin.command: aide --update && mv /var/lib/aide/aide.db.new.gz /var/lib/aide/aide.db.gz
  listen: Reinitialize AIDE database

- name: Reload systemd and enable timers
  ansible.builtin.systemd:
    daemon_reload: true
    name: "{{ item }}"
    enabled: true
    state: started
  loop:
    - aide-check.timer
    - aide-update.timer
  listen: Reload systemd and enable timers
```

```jinja2
# roles/aide/templates/aide.conf.j2
# Managed by Ansible - DO NOT EDIT MANUALLY
# Generated: {{ ansible_date_time.iso8601 }}
# Host: {{ inventory_hostname }}

# Macros
FIPSR = p+i+n+u+g+s+m+c+md5+sha256
NORMAL = FIPSR+sha512
DATAONLY = p+u+g+i+n+s+b+m+c+sha256
CONFIG = p+i+n+u+g+s+m+c+md5+sha256
LOG = p+i+n+u+g+s+b+m+c

# {{ aide_custom_rules | default([]) | join('\n') }}

# Default rules
{% for path, rule in aide_default_rules.items() %}
{{ path }}  {{ rule }}
{% endfor %}

# Exclusions
{% for excl in aide_exclusions | default([]) %}
!{{ excl }}
{% endfor %}
```

```yaml
# group_vars/all/security.yml
aide_default_rules:
  "/boot": "FIPSR"
  "/bin": "FIPSR"
  "/sbin": "FIPSR"
  "/usr/bin": "FIPSR"
  "/usr/sbin": "FIPSR"
  "/usr/lib": "FIPSR"
  "/usr/lib64": "FIPSR"
  "/lib": "FIPSR"
  "/lib64": "FIPSR"
  "/etc": "CONFIG"
  "/etc/ssh": "FIPSR"
  "/var/www": "DATAONLY"
  "/var/log": "LOG"
  "/etc/cron*": "FIPSR"
  "/etc/systemd": "FIPSR"
  "/usr/lib/systemd": "FIPSR"
  "/usr/local/bin": "FIPSR"
  "/usr/local/sbin": "FIPSR"
  "/opt": "FIPSR"

aide_exclusions:
  - "/etc/mtab"
  - "/etc/adjtime"
  - "/etc/ld.so.cache"
  - "/etc/udev/hwdb.bin"
  - "/etc/passwd-"
  - "/etc/group-"
  - "/etc/shadow-"
  - "/etc/gshadow-"
  - "/etc/*.bak"
  - "/etc/*.orig"
  - "/etc/*.dpkg-*"
  - "/etc/*.rpmnew"
  - "/etc/*.rpmsave"
  - "/etc/ssh/ssh_host_*_key"
  - "/etc/ssh/ssh_host_*_key.pub"
  - "/var/www/html/uploads"
  - "/var/www/html/cache"
  - "/var/www/html/tmp"
  - "/var/www/html/.git"
  - "/var/log/*.gz"
  - "/var/log/*.old"
  - "/var/log/*.log.[0-9]*"
  - "/var/log/journal"
  - "/var/lib/apt/lists/.*"
  - "/var/lib/dpkg/info/.*"
  - "/var/lib/systemd/timers/.*"
  - "/var/lib/AccountsService/.*"
  - "/var/lib/docker"
  - "/var/lib/containers"
  - "/var/cache"
  - "/var/spool"
  - "/proc"
  - "/sys"
  - "/dev"
  - "/run"
  - "/tmp"
  - "/var/tmp"
  - "/home/*/.cache"
  - "/root/.cache"
  - "/var/lib/postgresql"
  - "/var/lib/mysql"
  - "/var/lib/libvirt/images"
  - "/var/lib/machines"
```

---

### 3. Настройка Tripwire (Классическая альтернатива)

Tripwire обеспечивает более высокий уровень безопасности за счет шифрования базы данных и конфигурации. Он использует два типа ключей: **Site Key** (защищает файлы политики и конфигурации) и **Local Key** (защищает базы данных и отчеты).

#### 3.1 Установка и генерация ключей

```bash
# Установка (Debian/Ubuntu)
sudo apt install tripwire

# В процессе установки debconf попросит:
# 1. Создать Site Key — введите надежную парольную фразу (хранится в /etc/tripwire/site.key)
# 2. Создать Local Key — введите другую надежную парольную фразу (хранится в /etc/tripwire/hostname-local.key)

# Ручная генерация ключей (если пропущена при установке или для ротации):
sudo tripwire-setup-keyfiles
# Или по отдельности:
sudo twadmin --generate-keys --site-keyfile /etc/tripwire/site.key
sudo twadmin --generate-keys --local-keyfile /etc/tripwire/$(hostname)-local.key
```

#### 3.2 Структура политики (`/etc/tripwire/twpol.txt`)

Политика определяет, что проверять и какие атрибуты контролировать. Синтаксис: `путь -> набор_правил;`

```bash
# === ПРИМЕР ПОЛИТИКИ ДЛЯ PRODUCTION СЕРВЕРА ===

# Глобальные переменные
{
  TWBIN = /usr/sbin;
  TWPOL = /etc/tripwire;
  TWDB = /var/lib/tripwire;
  TWSKEY = /etc/tripwire/site.key;
  TWLKEY = /etc/tripwire/$(HOSTNAME)-local.key;
  TWREPORT = /var/lib/tripwire/report;
  HOSTNAME = $(HOSTNAME);
}

# Наборы правил (Property Masks)
# ReadOnly:   +pinugtsdrbmM   (все атрибуты, без хешей - для файлов, где хеш не нужен)
# Dynamic:    +pinugtsdrbmM   (все атрибуты + изменение размера допустимо)
# Growing:    +pinugtsdrbml   (только рост файла, для логов)
# Device:     +pinugtsdrbmM   (устройства)
# IgnoreAll:  -pinugtsdrbmM   (игнорировать всё)
# Invariant:  +pinugtsdrbmM   (неизменяемые файлы)

(
  rulename = "Invariant",
  severity = 100,
  emailto = root,
  recurse = true
)
{
  /boot                 -> $(Invariant);
  /sbin                 -> $(Invariant);
  /bin                  -> $(Invariant);
  /usr/bin              -> $(Invariant);
  /usr/sbin             -> $(Invariant);
  /usr/lib              -> $(Invariant);
  /usr/lib64            -> $(Invariant);
  /lib                  -> $(Invariant);
  /lib64                -> $(Invariant);
}

(
  rulename = "ConfigFiles",
  severity = 100,
  emailto = root,
  recurse = true
)
{
  /etc                  -> $(ConfigFiles);
  # Исключения
  !/etc/mtab;
  !/etc/adjtime;
  !/etc/ld.so.cache;
  !/etc/udev/hwdb.bin;
  !/etc/passwd-;
  !/etc/group-;
  !/etc/shadow-;
  !/etc/gshadow-;
  !/etc/*.bak;
  !/etc/*.orig;
  !/etc/*.dpkg-*;
  !/etc/*.rpmnew;
  !/etc/*.rpmsave;
  !/etc/ssh/ssh_host_*_key;
  !/etc/ssh/ssh_host_*_key.pub;
}

(
  rulename = "ConfigFiles",
  severity = 100,
  emailto = root
)
{
  /etc/passwd           -> $(ConfigFiles);
  /etc/group            -> $(ConfigFiles);
  /etc/shadow           -> $(ConfigFiles);
  /etc/gshadow          -> $(ConfigFiles);
  /etc/sudoers          -> $(ConfigFiles);
  /etc/sudoers.d        -> $(ConfigFiles);
  /etc/ssh/sshd_config  -> $(ConfigFiles);
  /etc/fstab            -> $(ConfigFiles);
  /etc/crontab          -> $(ConfigFiles);
}

(
  rulename = "LogFiles",
  severity = 50,
  emailto = root,
  recurse = true
)
{
  /var/log              -> $(Growing);
  !/var/log/*.gz;
  !/var/log/*.old;
  !/var/log/*.log.[0-9]*;
  !/var/log/journal;
}

(
  rulename = "WebContent",
  severity = 75,
  emailto = root,
  recurse = true
)
{
  /var/www              -> $(Dynamic);
  !/var/www/html/uploads;
  !/var/www/html/cache;
  !/var/www/html/tmp;
  !/var/www/html/.git;
}

(
  rulename = "SystemState",
  severity = 100,
  emailto = root,
  recurse = true
)
{
  /etc/cron*            -> $(ConfigFiles);
  /etc/systemd          -> $(ConfigFiles);
  /usr/lib/systemd      -> $(Invariant);
  /etc/init.d           -> $(Invariant);
  /usr/local/bin        -> $(Invariant);
  /usr/local/sbin       -> $(Invariant);
  /opt                  -> $(Invariant);
}

# Игнорируемые директории
(
  rulename = "IgnoreAll",
  severity = 0,
  recurse = true
)
{
  /proc                 -> $(IgnoreAll);
  /sys                  -> $(IgnoreAll);
  /dev                  -> $(IgnoreAll);
  /run                  -> $(IgnoreAll);
  /tmp                  -> $(IgnoreAll);
  /var/tmp              -> $(IgnoreAll);
  /var/cache            -> $(IgnoreAll);
  /var/spool            -> $(IgnoreAll);
  /var/lib/docker       -> $(IgnoreAll);
  /var/lib/containers   -> $(IgnoreAll);
  /var/lib/postgresql   -> $(IgnoreAll);
  /var/lib/mysql        -> $(IgnoreAll);
  /home/*/.cache        -> $(IgnoreAll);
  /root/.cache          -> $(IgnoreAll);
}
```

#### 3.3 Компиляция политики и инициализация базы

```bash
# 1. Компиляция текстовой политики в бинарный формат (требует Site Key)
sudo twadmin -m P /etc/tripwire/twpol.txt
# Вводите пароль Site Key
# Результат: /etc/tripwire/tw.pol

# 2. Инициализация базы данных (требует Local Key)
sudo tripwire --init
# Вводите пароль Local Key
# Результат: /var/lib/tripwire/$(HOSTNAME).twd

# 3. Проверка (сравнение с базой)
sudo tripwire --check
# Отчет сохраняется в /var/lib/tripwire/report/$(HOSTNAME)-YYYYMMDD-HHMMSS.twr

# 4. Просмотр отчета в читаемом виде
sudo twprint --print-report -r /var/lib/tripwire/report/$(HOSTNAME)-20260910-120000.twr

# 5. Обновление базы после легитимных изменений
sudo tripwire --update -r /var/lib/tripwire/report/$(HOSTNAME)-20260910-120000.twr
# Интерактивно выбирайте какие изменения принять (y/n)
# Требует Local Key

# 6. Обновление политики (после изменения twpol.txt)
sudo twadmin -m P /etc/tripwire/twpol.txt  # Новая подпись Site Key
sudo tripwire --init                       # Пересоздание базы Local Key
```

#### 3.4 Автоматизация Tripwire через systemd

```ini
# /etc/systemd/system/tripwire-check.service
[Unit]
Description=Tripwire Integrity Check
After=network.target

[Service]
Type=oneshot
ExecStart=/usr/sbin/tripwire --check
Environment=TRIPWIRE_PASSWORD_FILE=/etc/tripwire/local_pass
# Файл с паролем Local Key (chmod 600, root:root)
StandardOutput=journal
StandardError=journal
TimeoutSec=7200

[Install]
WantedBy=multi-user.target
```

```ini
# /etc/systemd/system/tripwire-check.timer
[Unit]
Description=Daily Tripwire Integrity Check
Requires=tripwire-check.service

[Timer]
OnCalendar=daily
RandomizedDelaySec=6h
Persistent=true

[Install]
WantedBy=timers.target
```

**Важно:** Для автоматического запуска создайте `/etc/tripwire/local_pass` с паролем Local Key (только `chmod 600 root:root`), или используйте `expect` скрипт для интерактивного ввода.

#### 3.5 Сравнение AIDE vs Tripwire для выбора

| Характеристика | AIDE | Tripwire |
|---|---|---|
| **Лицензия** | GPLv2+ (Open Source) | Open Source (Tripwire) / Коммерческая (Tripwire Enterprise) |
| **Шифрование БД** | Нет (только gzip) | Да (AES, подпись ключами) |
| **Разделение ролей** | Нет | Да (Site Key / Local Key) |
| **Конфигурация** | Простая (aide.conf) | Сложная (twpol.txt + компиляция) |
| **Производительность** | Быстрее на больших ФС | Медленнее из-за криптографии |
| **Отчеты** | Текстовые, stdout | Бинарные, требуют twprint |
| **Интеграция SIEM** | Простая (stdout/json) | Требует парсинга twprint |
| **Рекомендация** | Большинство случаев, DevOps, CI/CD | Высокобезопасные среды, разделение обязанностей, аудит |

---

### 4. Мониторинг IMA (Integrity Measurement Architecture) и EVM

Если ядро скомпилировано с поддержкой IMA, можно просмотреть лог измерений:

```bash
# Проверка статуса в ядре
grep IMA /boot/config-$(uname -r)

# Просмотр измерений в реальном времени
sudo cat /sys/kernel/security/ima/ascii_runtime_measurements | tail -n 5
# → result: 10 <hash> ima-ng sha256:<hash> /usr/bin/sudo
```
*Примечание: Для полноценной работы IMA требуется настройка политик и (желательно) наличие TPM.*

#### 4.1 Настройка политик IMA (Custom Policy)

Политики IMA определяют, **какие** файлы измерять и **когда**. Загружаются через securityfs до включения IMA (обычно в initramfs или ранние стадии загрузки).

```bash
# Проверка текущей политики
cat /sys/kernel/security/ima/policy

# Стандартные политики (выбираются при загрузке ядра параметром ima_policy=):
# - ima_policy=tcb          # Trusted Computing Base (исполняемые файлы, mmap, модули ядра)
# - ima_policy=secure_boot  # Файлы, подписанные доверенными ключами
# - ima_policy=critical_data # Критичные данные (/etc, ключи, сертификаты)
# - ima_policy=fail_securely # Запрет исполнения не измеренных файлов (IMA-appraisal)
```

**Своя политика (загрузка в runtime — требует CAP_SYS_ADMIN и незаблокированной политики):**

```bash
# Пример: измерять все исполняемые файлы + чтение /etc + модули ядра
cat > /etc/ima/ima-policy << 'EOF'
# Измерение всех execve() (запуск программ)
measure func=FILE_CHECK mask=MAY_EXEC uid=0 fowner=0
measure func=FILE_CHECK mask=MAY_EXEC uid=0 fowner=1000

# Измерение mmap с PROT_EXEC (динамические библиотеки)
measure func=MMAP_CHECK mask=MAY_EXEC

# Измерение загрузки модулей ядра
measure func=MODULE_CHECK

# Измерение чтения критичных файлов (ключи, сертификаты, конфиги)
measure func=FILE_CHECK mask=MAY_READ uid=0 obj_type=etc_t
measure func=FILE_CHECK mask=MAY_READ uid=0 obj_type=cert_t
measure func=FILE_CHECK mask=MAY_READ uid=0 obj_type=ssh_key_t

# Исключение шумных путей
dont_measure func=FILE_CHECK mask=MAY_EXEC fstype=tmpfs
dont_measure func=FILE_CHECK mask=MAY_EXEC fstype=proc
dont_measure func=FILE_CHECK mask=MAY_EXEC fstype=sysfs
dont_measure func=FILE_CHECK mask=MAY_READ fstype=tmpfs
EOF

# Загрузка политики (до включения ima_appraise)
cat /etc/ima/ima-policy > /sys/kernel/security/ima/policy
```

**Для постоянного применения добавьте в initramfs:**
```bash
# /etc/dracut.conf.d/ima.conf
install_items+=" /etc/ima/ima-policy /sys/kernel/security/ima/policy "
# Пересборка initramfs
sudo dracut -f
```

#### 4.2 IMA Appraisal (Оценка целостности) — Блокировка измененных файлов

IMA Appraisal сравнивает измеренный хеш с **эталонным значением (reference value)**, хранящимся в расширенном атрибуте `security.ima`. Если не совпадает — доступ запрещается.

```bash
# 1. Проверка поддержки в ядре
grep -E "CONFIG_IMA.*APPRAISE" /boot/config-$(uname -r)
# CONFIG_IMA_APPRAISE=y
# CONFIG_IMA_APPRAISE_BOOTPARAM=y

# 2. Генерация эталонных хешей для файлов (на чистой системе)
# Используйте evmctl для подписи атрибутов
sudo apt install evmctl  # или dnf install evmctl

# Создание ключей для подписи (храните приватный ключ офлайн!)
openssl genrsa -out /root/ima-priv.pem 2048
openssl rsa -in /root/ima-priv.pem -pubout -out /root/ima-pub.pem

# Подписание файлов (пример для /usr/bin)
sudo evmctl ima_sign --key /root/ima-priv.pem --hash sha256 /usr/bin/*
# Это запишет security.ima xattr на каждый файл

# 3. Загрузка публичного ключа в ядро (keyring .ima)
sudo evmctl import /root/ima-pub.pem /etc/keys/ima-pub.x509
# Добавьте в initramfs или загрузите через ключ ядра ima_appraise=fix

# 4. Параметры загрузки ядра (GRUB_CMDLINE_LINUX_DEFAULT)
ima_policy=appraise_tcb ima_appraise=fix ima_hash=sha256
# ima_appraise=fix    — блокировать исполнение неверных файлов
# ima_appraise=log    — только логировать (для тестирования)
# ima_appraise=off    — отключить appraisal
```

#### 4.3 EVM (Extended Verification Module) — Защита xattr

EVM защищает расширенные атрибуты (включая `security.ima`, `security.selinux`, `security.capability`) от офлайн-модификации.

```bash
# Проверка поддержки
grep CONFIG_EVM /boot/config-$(uname -r)

# Генерация ключа EVM
openssl genrsa -out /root/evm-priv.pem 2048
openssl rsa -in /root/evm-priv.pem -pubout -out /root/evm-pub.pem

# Инициализация EVM HMAC ключа в ядре (требует доверенной загрузки)
# Ключ генерируется из TPM или вводится при загрузке
# evmctl evm_init --key /root/evm-priv.pem

# Параметры загрузки для EVM
evm=fix evm_hash=sha256
# evm=fix — блокировать изменение защищенных xattr
```

#### 4.4 Интеграция с TPM (Trusted Platform Module)

Для максимальной безопасности измерения IMA записываются в PCR (Platform Configuration Registers) TPM:

```bash
# Проверка TPM
ls /dev/tpm*
dmesg | grep -i tpm

# IMA с TPM (в политике ядра)
CONFIG_IMA_TPM=y
CONFIG_IMA_WRITE_POLICY=y

# Просмотр PCR расширений
tpm2_pcrread sha256:10  # PCR 10 обычно для IMA
# Вывод показывает цепочку измерений от загрузки

# Удаленная аттестация (Remote Attestation)
# Клиент подписывает PCR значения ключом AK (Attestation Key)
# Сервер верифицирует подпись и сравнивает с эталонными значениями
```

#### 4.5 Практический мониторинг IMA в продакшене

```bash
# 1. Настройка аудита IMA событий через auditd
# /etc/audit/rules.d/ima.rules
-w /sys/kernel/security/ima/ -p wa -k ima_events
-a always,exit -F arch=b64 -S open,openat -F path=/sys/kernel/security/ima/* -k ima_access

# 2. Парсинг логов IMA для SIEM
# Формат строки: pcr template-hash algorithm:file-hash path
# Пример парсинга на Python:
python3 << 'EOF'
import re
pattern = r'(\d+)\s+([a-f0-9]+)\s+ima-ng\s+(\w+):([a-f0-9]+)\s+(.+)'
with open('/sys/kernel/security/ima/ascii_runtime_measurements') as f:
    for line in f:
        m = re.match(pattern, line.strip())
        if m:
            pcr, template_hash, algo, file_hash, path = m.groups()
            print(f"PCR={pcr} ALGO={algo} HASH={file_hash} PATH={path}")
EOF

# 3. Интеграция с Wazuh (пересылка IMA логов)
# В ossec.conf агента:
# <localfile>
#   <location>/sys/kernel/security/ima/ascii_runtime_measurements</location>
#   <log_format>syslog</log_format>
# </localfile>
```

---

### 5. Проверка подписей пакетов

Безопасность начинается с установки. Убедитесь, что система проверяет GPG-подписи репозиториев.

```bash
# Для APT: проверка ключей доверия
apt-key list  # (устаревший метод)
ls /etc/apt/trusted.gpg.d/

# Для RPM: проверка импортированных ключей
rpm -q gpg-pubkey --qf '%{name}-%{version}-%{release} --> %{summary}\n'
```

### 6. Целостность контейнерных образов (Container Image Integrity)

В современных инфраструктурах контейнеры — основной артефакт развертывания. Проверка их целостности критична на всех этапах: сборка, хранение, запуск.

#### 6.1 Подпись и верификация образов (Cosign/Sigstore)

```bash
# Установка cosign
curl -O -L "https://github.com/sigstore/cosign/releases/latest/download/cosign-linux-amd64"
sudo mv cosign-linux-amd64 /usr/local/bin/cosign && sudo chmod +x /usr/local/bin/cosign

# Генерация ключей (или использование keyless через OIDC)
cosign generate-key-pair
# Вводите пароль для приватного ключа
# Создает cosign.key и cosign.pub

# Подпись образа в реестре
cosign sign --key cosign.key registry.example.com/myapp:v1.2.3
# Или keyless (GitHub Actions, GitLab CI, Google Cloud):
cosign sign registry.example.com/myapp:v1.2.3

# Верификация подписи
cosign verify --key cosign.pub registry.example.com/myapp:v1.2.3
# Код возврата 0 = валидно, 1 = ошибка

# Верификация с политикой (ReKor transparency log)
cosign verify --key cosign.pub \
  --certificate-identity-regexp ".*@mycompany\.com" \
  --certificate-oidc-issuer-regexp "https://token.actions.githubusercontent.com" \
  registry.example.com/myapp:v1.2.3
```

#### 6.2 SBOM (Software Bill of Materials) и проверка уязвимостей

```bash
# Генерация SBOM через Syft
syft registry.example.com/myapp:v1.2.3 -o spdx-json > sbom.spdx.json
syft registry.example.com/myapp:v1.2.3 -o cyclonedx-json > sbom.cdx.json

# Проверка уязвимостей через Grype
grype registry.example.com/myapp:v1.2.3 -o table
grype sbom:sbom.spdx.json --fail-on high

# Аттач SBOM к образу (Cosign)
cosign attest --predicate sbom.spdx.json --type spdx registry.example.com/myapp:v1.2.3

# Верификация SBOM
cosign verify-attestation --type spdx --key cosign.pub registry.example.com/myapp:v1.2.3
```

#### 6.3 Проверка целостности на этапе запуска (Admission Controllers)

В Kubernetes используйте **Kyverno** или **OPA Gatekeeper** для блокировки неподписанных образов:

```yaml
# Kyverno Policy: require cosign signature
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: require-image-signature
spec:
  validationFailureAction: Enforce
  background: false
  rules:
    - name: check-cosign-signature
      match:
        any:
          - resources:
              kinds: ["Pod"]
      verifyImages:
        - imageReferences: ["registry.example.com/*"]
          attestations:
            - type: cosign
              conditions:
                - all:
                    - key: "{{ json_parse(attestation.statement).predicate.slsa_level }}"
                      operator: Equals
                      value: "Build_L3"
```

#### 6.4 Проверка слоев образа (Layer Integrity)

```bash
# Скачивание манифеста и проверка дайджестов слоев
crane manifest registry.example.com/myapp:v1.2.3 | jq '.layers[].digest'

# Локальная проверка после pull (Docker)
docker pull registry.example.com/myapp:v1.2.3
docker image inspect registry.example.com/myapp:v1.2.3 --format '{{json .RootFS.Layers}}'

# Верификация каждого слоя через sha256
# Сравните с дайджестами из доверенного источника (CI/CD pipeline, SBOM)
```

#### 6.5 Защита runtime (Falco, Tetragon)

Для обнаружения изменений файлов **внутри работающего контейнера**:

```yaml
# Falco rule: обнаружение записи в исполняемые файлы контейнера
- rule: Write to Binary in Container
  desc: Detect writes to binary directories in containers
  condition: >
    container.id != host and
    evt.type in (openat, open) and
    evt.arg.flags contains O_WRONLY and
    fd.name pmatch (/bin/*, /usr/bin/*, /sbin/*, /usr/sbin/*, /lib/*, /usr/lib/*)
  output: >
    Container binary write (user=%user.name container=%container.name image=%container.image.repository cmdline=%proc.cmdline file=%fd.name)
  priority: ERROR
  tags: [container, mitre_persistence, T1546]
```

---

### 10. Типичные проблемы и решения (Troubleshooting)

#### 10.1 AIDE: "Couldn't open database" / "Database not found"

```bash
# Причина: базы нет или путь неверен в aide.conf
# Проверка конфига
grep ^database /etc/aide/aide.conf
# database=file:/var/lib/aide/aide.db.gz
# database_out=file:/var/lib/aide/aide.db.new.gz

# Решение: инициализация
sudo aideinit -y -f
sudo mv /var/lib/aide/aide.db.new.gz /var/lib/aide/aide.db.gz
```

#### 10.2 AIDE: Ложные срабатывания на часто меняющихся файлах

```bash
# Симптом: ежедневные алерты на /etc/adjtime, /etc/ld.so.cache, /var/log/*
# Решение: добавьте исключения в aide.conf
!/etc/adjtime
!/etc/ld.so.cache
!/var/log/*.gz
!/var/log/journal

# Для systemd таймеров и машинных ID
!/etc/machine-id
!/var/lib/systemd/timers/*
!/var/lib/AccountsService/*
```

#### 10.3 AIDE: Высокая нагрузка на диск/CPU при проверке

```bash
# 1. Используйте ionice/nice (в systemd unit)
Nice=10
IOSchedulingClass=best-effort
IOSchedulingPriority=7

# 2. Исключите большие динамические директории
!/var/lib/docker
!/var/lib/containers
!/var/lib/postgresql
!/var/lib/mysql
!/var/cache
!/var/spool

# 3. Разбейте проверку на несколько проходов по файловым системам
# aide.conf.rootfs, aide.conf.var, aide.conf.opt
sudo aide --check --config=/etc/aide/aide.conf.rootfs &
sudo aide --check --config=/etc/aide/aide.conf.var &
wait
```

#### 10.4 RPM: "Missing dependencies" при rpm -V

```bash
# rpm -V показывает 'D' (missing dependency) для файлов, пакет которых удален но файлы остались
# Решение: найдите-какой пакет владел файлом
rpm -qf /path/to/file
# Если пакет не установлен — файл "сиротский", удалите или восстановите пакет
```

#### 10.5 RPM/debsums: Конфигурационные файлы помечены как измененные

```bash
# Это НОРМАЛЬНО для конфигов, которые меняет админ
# Код 'c' в выводе rpm -V означает "config file"
rpm -V | grep '^.c'
# S.5....T.  c /etc/httpd/conf/httpd.conf

# В AIDE используйте макрос CONFIG для конфигов (проверяет хеш, но ожидает изменения)
# В Tripwire используйте правило ConfigFiles (проверяет атрибуты + хеш)
```

#### 10.6 Tripwire: "Error: Cannot open key file"

```bash
# Причина: неправильный путь к ключу или пароль
# Проверка путей в tw.cfg
grep -E "TWSKEY|TWLKEY" /etc/tripwire/tw.cfg

# Решение: перегенерация ключей
sudo tripwire-setup-keyfiles
# Или вручную
sudo twadmin --generate-keys --site-keyfile /etc/tripwire/site.key
sudo twadmin --generate-keys --local-keyfile /etc/tripwire/$(hostname)-local.key
```

#### 10.7 IMA: "Policy is locked" при попытке загрузить политику

```bash
# Причина: политика уже загружена и зафиксирована (IMA_APPRAISE=fix)
# Решение: загружайте политику РАНЬШЕ включения appraisal
# 1. В initramfs (dracut) — добавьте политику в образ
# 2. Или параметр ядра ima_policy=... на этапе загрузки
# В runtime политику изменить нельзя без reboot (если не ima_appraise=off)
```

#### 10.8 IMA Appraisal: "Permission denied" при запуске легитимных бинарников

```bash
# Причина: отсутствует или неверный security.ima xattr
# Проверка
getfattr -n security.ima /usr/bin/ls

# Решение: переподписать файлы (на чистой системе!)
evmctl ima_sign --key /root/ima-priv.pem --hash sha256 /usr/bin/ls
# Или временно: ima_appraise=log (только логировать, не блокировать)
# В GRUB: ima_appraise=log ima_hash=sha256
```

#### 10.9 Wazuh FIM: Слишком много алертов (Event Flood)

```bash
# 1. Исключите шумные пути в ossec.conf
<ignore>/var/log/nginx/access.log</ignore>
<ignore type="sregex">/var/log/.*\.log$</ignore>

# 2. Отключите whodata для высоконагруженных директорий
<directories check_all="yes" whodata="no">/var/log</directories>

# 3. Настройте auto_ignore
<auto_ignore frequency="10" timeframe="3600">yes</auto_ignore>
# Игнорирует файлы, меняющиеся >10 раз в час

# 4. Используйте eBPF провайдер (Linux 4.14+)
<whodata>
  <provider>ebpf</provider>
</whodata>
```

#### 10.10 Общее: База данных FIM скомпрометирована

```bash
# Симптом: изменения есть, но AIDE/Tripwire их не видят
# Причина: злоумышленник обновил базу после изменений
# Проверка: сравните хеш базы с эталонным (в Git, на внешнем носителе)
sha256sum /var/lib/aide/aide.db.gz
# Должен совпадать с эталоном

# Профилактика:
# 1. Храните эталонную БД на read-only носителе (USB, CD-R)
# 2. Отправляйте хеш базы в удаленную SIEM/Wazuh Manager
# 3. Подписывайте БД GPG ключом (храните приватный ключ офлайн)
gpg --sign /var/lib/aide/aide.db.gz
# 4. Используйте IMA Appraisal + TPM для защиты самих инструментов FIM
```

---

## Дополнительная информация

### Лучшие практики (Best Practices)

1.  **Многослойная защита (Defense in Depth):** Не полагайтесь на один инструмент. Комбинируйте:
    *   Пакетные менеджеры (rpm/debsums) — для файлов из репозиториев
    *   HIDS (AIDE/Tripwire) — для всех файлов, включая пользовательские
    *   Ядерные механизмы (IMA/EVM + TPM) — для неизменяемого лога измерений
    *   Непрерывный FIM (Wazuh) — для реального времени и атрибуции
    *   Immutable флаги (chattr +i) — для критичных конфигов

2.  **Защита базы данных — приоритет №1:** Самое слабое место локальных проверок — сама база данных. Злоумышленник с root может обновить её после внесения изменений.
    *   **Решение:** Храните эталонную БД на внешнем read-only носителе (USB, CD-R) или отправляйте её хеш/подпись в удаленную систему мониторинга (SIEM, Wazuh Manager, Git).
    *   Подписывайте БД GPG ключом (приватный ключ хранится офлайн).
    *   Используйте IMA Appraisal для защиты самих бинарников AIDE/Tripwire/aide.

3.  **Автоматизация и IaC:** Управляйте конфигурациями AIDE/Tripwire через Ansible/Salt/Puppet. Храните эталонные базы в Git (зашифрованные). Обновляйте базу только через CI/CD pipeline после ревью изменений.

4.  **Регулярное тестирование:** Раз в квартал проводите "Fire Drill" — намеренно измените файл, проверьте, что алерт сработал, процесс реагирования отработал, база обновилась корректно.

5.  **Интеграция с SIEM:** Все алерты FIM должны попадать в SIEM (Wazuh, Elastic, Splunk) с обогащением контекстом (MITRE ATT&CK теги, активы, владельцы).

### Соответствие стандартам (Compliance)

Проверка целостности файлов является обязательным требованием многих стандартов безопасности:

*   **PCI DSS v4.0** — Требование 11.5: "Внедрите механизм обнаружения изменений для критичных файлов"
*   **CIS Benchmarks** — Рекомендации по настройке AIDE/Tripwire для конкретных ОС
*   **ФСТЭК (Россия)** — Требования к средствам контроля целостности (СКЦИ)
*   **NIST 800-53** — SI-7 (Integrity Monitoring), CM-3 (Configuration Change Control)
*   **ISO 27001** — A.12.2.1 (Controls against malware), A.12.4.1 (Event logging)

### Производительность и масштабирование

| Инструмент | Подход | Масштаб | Нагрузка | Рекомендация |
|---|---|---|---|---|
| **rpm/debsums** | По требованию | Любой | Низкая | Базовая проверка |
| **AIDE** | Периодический (cron/timer) | до 500k файлов | Средняя (I/O bound) | Основной HIDS для серверов |
| **Tripwire** | Периодический | до 300k файлов | Высокая (криптография) | Высокобезопасные среды |
| **Wazuh FIM** | Real-time + Scheduled | 100k+ на агента | Низкая (eBPF) | Корпоративные парки, облако |
| **IMA/EVM** | Ядерный (continuous) | Весь FS | Минимальная | Критичная инфраструктура, TPM |
| **Auditd** | Ядерный (continuous) | Выборочно | Настраиваемая | Форензика, compliance |

### См. также

* [Мониторинг целостности файлов (FIM) в Wazuh](../../../Security/Tools/Wazuh/wazuh-fim.md) — централизованный FIM с whodata и Active Response
* [auditd: Аудит системных вызовов](../../SystemAdministration/Logging/auditd.md) — детальное логирование доступа к файлам
* [Обзор механизмов безопасности в Linux](../Linux_Security_Mechanisms_Overview.md) — контекст всех механизмов защиты
* [Атрибуты файлов (Immutable, ACL, xattr)](../File_Permissions/acl_immutable_timestamps.md) — защита на уровне ФС
* [Безопасность модулей ядра](../Mechanisms/kernel_module_security.md) — подпись и контроль загрузки модулей
* [Безопасность цепочки поставок: Целостность сборки](../../../Security/Supply_Chain_Security/build_integrity.md) — SLSA, Cosign, SBOM для артефактов
* [Docker SBOM и подпись образов](../../../Docker/Docker_security/docker_sbom.md) — целостность контейнерных образов
* [Безопасность systemd](./systemd_security.md) — изоляция и защита сервисов
* [Реагирование на инциденты](./incident_response.md) — процедуры реагирования на нарушения безопасности
* [Основы шифрования](./encryption_basics.md) — LUKS, TLS/SSL, GPG
* [Безопасность контейнеров](./container_security.md) — концепции и механизмы защиты контейнеров
* [PAM (Pluggable Authentication Modules)](../../Security/pam_overview.md) — аутентификация и управление доступом
* [SELinux](../../Security/Mechanisms/SELinux.md) — принудительный контроль доступа
* [AppArmor](../../Security/Mechanisms/AppArmor.md) — принудительный контроль доступа на основе путей
* [SSH Hardening](../../Security/ssh/server/ssh_hardening_best_practices.md) — безопасность SSH-сервера