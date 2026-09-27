# Кроссплатформенная конфигурация системы: ядро, время, логи, файловые системы

## Версионирование и требования

| Компонент | Минимальная версия | Рекомендуемая версия | Примечание |
| :--- | :--- | :--- | :--- |
| **ansible-core** | 2.18+ | 2.21.4+ | 2.22.0b1 доступен (сентябрь 2026) |
| **systemd** | 235+ | 257+ / 261+ (stable) | 262 вышел 22 сентября 2026 |
| **OpenSSH** | 8.0+ | 10.5+ | 10.5 — актуальный релиз (август 2026) |
| **Chrony** | 4.0+ | 4.8+ / 4.9+ | 4.8 — стабильный релиз; 4.9 в testing/unstable |
| **Python** (control node) | 3.12+ | 3.14 | Для ansible-core 2.21 |
| **Python** (managed node, POSIX) | 3.9+ | 3.12+ | Для ansible-core 2.21 |
| **PowerShell** (Windows) | 5.1+ | 7.6 LTS | Для ansible-core 2.21/2.22 |

**Проверка окружения:**
```bash
ansible --version | head -1
# → ansible [core 2.21.4]

ansible all -m ping
# → pong: web01
# → pong: db01
```

## Определения

- **`sysctl`** — интерфейс чтения/записи параметров ядра Linux через виртуальную файловую систему `/proc/sys/`. Настройки применяются немедленно и сохраняются в `/etc/sysctl.conf` или `/etc/sysctl.d/*.conf`. Разделы: `net` (сеть), `fs` (файловые системы), `kernel` (ядро), `vm` (виртуальная память), `dev` (устройства).
- **`ansible.posix.sysctl`** — модуль Ansible для управления параметрами ядра. Поддерживает `sysctl_file` для записи в отдельные файлы в `/etc/sysctl.d/`, что обеспечивает модульность и предотвращает конфликты при обновлениях пакетов.
- **NTP (Network Time Protocol)** — протокол синхронизации времени. На современных Linux-системах дополнен NTS (Network Time Security) для аутентификации.
- **Chrony** — современный NTP-клиент и сервер, предпочтительный для виртуальных машин и нестабильных сетей. Использует `chronyd`. Поддерживает NTS, PTP, hardware timestamping.
- **systemd-timesyncd** — легковесный NTP-клиент, встроенный в systemd. Подходит для контейнеров и минимальных установок.
- **Systemd timer** — аналог cron в рамках systemd, реализованный через unit-файлы `.timer`. Поддерживает calendar-спецификации (`OnCalendar=*:0/5`), `Persistent=true` (догоняет пропущенные запуски), точность до секунды.
- **`logrotate`** — механизм ротации логов на уровне ОС. Архивирует, сжимает и удаляет устаревшие файлы логов. Работает на всех Linux-дистрибутивах.
- **journald** — системный демон сбора логов в Linux (бинарный формат). Предоставляет `journalctl` для поиска. Может выступать источником для rsyslog/Vector.
- **rsyslog** — высокопроизводительный демон сбора и пересылки логов. Поддерживает фильтры, модули и удаленную отправку.
- **`ansible.builtin.mount`** — декларативное управление точками монтирования через `/etc/fstab` (Linux/BSD) или `/etc/vfstab` (Unix/Solaris).
- **tmpfiles.d** — механизм systemd для создания временных файлов и директорий (`/tmp`, `/run`, `/var/run`) с правами и владельцами.
- **PAM (Pluggable Authentication Modules)** — фреймворк Linux для интеграции различных методов аутентификации. `/etc/security/limits.conf` и `/etc/security/limits.d/` управляют лимитами ресурсов через `pam_limits.so`.
- **Сервисный аккаунт** — выделенная учетная запись пользователя, созданная для запуска конкретного приложения или сервиса. Рекомендуется использовать `system: yes` и `shell: /usr/sbin/nologin`.
- **`ansible.builtin.hostname`** — модуль для управления именем хоста. Работает через `hostnamectl` на systemd-системах.
- **`ansible.builtin.timezone`** — модуль для настройки системного часового пояса. Использует `timedatectl` на systemd-системах или изменяет `/etc/localtime` symlink.
- **`community.general.locale_gen`** — модуль для генерации и настройки системных локалей. Изменяет `/etc/locale.gen` и запускает `locale-gen`.

## Основные концепции

### sysctl: тюнинг ядра через Ansible

Параметры ядра критичны для производительности СУБД, сетевых сервисов и безопасности. `ansible.posix.sysctl` применяет параметры немедленно и сохраняет их в `/etc/sysctl.d/*.conf`.

| Параметр | Назначение | Типичное значение | Модуль |
| :--- | :--- | :--- | :--- |
| `vm.swappiness` | Склонность к свопу | `10` (СУБД), `60` (дефолт) | `ansible.posix.sysctl` |
| `vm.overcommit_memory` | Переcommit памяти | `2` для СУБД | `ansible.posix.sysctl` |
| `vm.dirty_ratio` | Порог dirty pages перед принудительной записью | `10` (СУБД) | `ansible.posix.sysctl` |
| `vm.dirty_background_ratio` | Порог для фоновой записи | `3` (СУБД) | `ansible.posix.sysctl` |
| `net.core.somaxconn` | Длина очереди слушающих сокетов | `4096` для высоконагруженных сервисов | `ansible.posix.sysctl` |
| `net.ipv4.ip_forward` | IP forwarding | `1` для роутеров | `ansible.posix.sysctl` |
| `net.ipv4.tcp_syncookies` | Защита от SYN flood | `1` | `ansible.posix.sysctl` |
| `fs.file-max` | Максимум открытых файлов | `2097152` | `ansible.posix.sysctl` |
| `kernel.sem` | Семафоры System V IPC | `250 256000 100 1024` (СУБД) | `ansible.posix.sysctl` |
| Сетевые параметры | IP forwarding, socket tuning, защита | См. [Ansible: Модули управления сетевой конфигурацией Linux](../Modules/ansible_network_configuration_modules.md) | `ansible.posix.sysctl` |

```yaml
# sysctl через ansible.posix.sysctl (рекомендуется)
- name: Тюнинг виртуальной памяти для СУБД
  ansible.posix.sysctl:
    name: "{{ item.name }}"
    value: "{{ item.value }}"
    state: present
    sysctl_file: /etc/sysctl.d/99-performance.conf
    reload: yes
  loop:
    - { name: 'vm.swappiness', value: '10' }
    - { name: 'vm.overcommit_memory', value: '2' }
    - { name: 'vm.dirty_ratio', value: '10' }
    - { name: 'vm.dirty_background_ratio', value: '3' }
  become: yes
  when: ansible_facts['system'] != 'Win32NT'
```

> **Production note:** `sysctl_file` позволяет сохранять настройки в отдельные файлы в `/etc/sysctl.d/` вместо редактирования `/etc/sysctl.conf`. Это обеспечивает модульность и предотвращает конфликты при обновлениях пакетов. `reload: yes` применяет параметры немедленно (`sysctl -p`). На Windows параметры ядра настраиваются через реестр (`ansible.windows.win_regedit`) — нет прямого аналога `sysctl`. Для сетевых параметров см. [Ansible: Модули управления сетевой конфигурацией Linux](../Modules/ansible_network_configuration_modules.md).

### NTP и timezone

Синхронизация времени критична для логов, сертификатов, кластеров и финансовых транзакций. Сдвиг более чем на 2 секунды может вызвать проблемы с SSL/TLS, Kerberos и распределенными системами.

| Модуль | ОС | Назначение |
| :--- | :--- | :--- |
| `ansible.builtin.timezone` | Linux (systemd), macOS | Установка часового пояса через `timedatectl` или `/etc/localtime` |
| `community.general.chrony` | Linux | Управление chrony (серверы, ключи, сервис) |
| `community.general.ntp` | Linux | Управление ntpd (устаревший, заменен chrony) |
| `ansible.windows.win_timezone` | Windows | Только часовой пояс, не NTP |

```yaml
# Настройка времени и часового пояса
- name: Установка часового пояса
  ansible.builtin.timezone:
    name: "{{ timezone | default('Europe/Moscow') }}"
  become: yes
  when: ansible_facts['system'] != 'Win32NT'

# Установка chrony (предпочтительно для RHEL/Debian)
- name: Установка chrony
  ansible.builtin.package:
    name: chrony
    state: present
  when: ansible_facts['os_family'] == 'RedHat' or ansible_facts['os_family'] == 'Debian'

- name: Настройка chrony с NTS
  community.general.chrony:
    servers:
      - "0.ru.pool.ntp.org iburst"
      - "1.ru.pool.ntp.org iburst"
      - "2.ru.pool.ntp.org iburst"
    driftfile: /var/lib/chrony/drift
    service: started
    enabled: yes
  become: yes
  when: ansible_facts['os_family'] == 'RedHat' or ansible_facts['os_family'] == 'Debian'
```

> **Production note:** Chrony предпочтительнее ntpd для виртуальных машин и нестабильных сетей (быстрее синхронизируется, лучше обрабатывает дрейф). systemd-timesyncd — минималистичная альтернатива для контейнеров. На Windows время синхронизируется через домен (Domain Controller) или `ansible.windows.win_timezone` (только часовой пояс, не NTP). Chrony 4.8+ поддерживает NTS (Network Time Security) для аутентификации NTP-серверов.

### Systemd timers vs cron vs Scheduled Task

Планировщики задач различаются по платформам. Systemd timers предоставляют более точный контроль, интеграцию с journald и поддержку calendar-спецификаций.

| Платформа | Планировщик | Модуль Ansible | Примечания |
| :--- | :--- | :--- | :--- |
| Linux (systemd) | Systemd timer | `ansible.builtin.systemd` | Рекомендуется для systemd-систем |
| Linux (legacy) | cron | `ansible.builtin.cron` | Универсальный, работает на всех Linux |
| macOS | cron / launchd | `ansible.builtin.cron` | launchd управляется через templates |
| Windows | Task Scheduler | `ansible.windows.win_scheduled_task` | Только для Windows |

```yaml
# Systemd timer (предпочтительно для systemd)
- name: Создание systemd timer для cleanup
  ansible.builtin.systemd:
    name: cleanup.timer
    state: started
    enabled: yes
    daemon_reload: yes
  become: yes
  when: ansible_facts['service_mgr'] == 'systemd'

# /etc/systemd/system/cleanup.timer — через template
- name: Шаблон systemd timer
  ansible.builtin.template:
    src: cleanup.timer.j2
    dest: /etc/systemd/system/cleanup.timer
    mode: '0644'
  notify: systemd daemon-reload
  when: ansible_facts['service_mgr'] == 'systemd'
```

```ini
# templates/cleanup.timer.j2
[Unit]
Description=Cleanup old logs

[Timer]
OnCalendar=*:0/5
Persistent=true

[Install]
WantedBy=timers.target
```

```yaml
# cron (универсальный, legacy)
- name: Cron для cleanup
  ansible.builtin.cron:
    name: "Очистка логов"
    minute: "0"
    hour: "3"
    job: "/usr/local/bin/cleanup.sh"
    cron_file: /etc/cron.d/cleanup
  when: ansible_facts['service_mgr'] != 'systemd' or ansible_facts['system'] == 'Darwin'

# Windows Scheduled Task
- name: Scheduled Task для cleanup (Windows)
  ansible.windows.win_scheduled_task:
    name: cleanup_logs
    description: "Очистка логов"
    actions:
      - path: C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe
        arguments: "-ExecutionPolicy Bypass -File C:\\scripts\\cleanup.ps1"
    triggers:
      - type: daily
        start_boundary: '2026-09-26T03:00:00'
    state: present
    enabled: yes
  when: ansible_facts['os_family'] == 'Windows'
```

> **Production note:** Systemd timers предпочтительнее cron в modern Linux: точность до секунды, интеграция с journald, `Persistent=true` для догона пропущенных запусков, привязка к сервисам. Cron остается для legacy-систем (SysVinit, OpenRC, macOS). На Windows используйте Task Scheduler — нет прямого аналога cron. Для systemd timers используйте `cron_file` параметр в `ansible.builtin.cron` для создания отдельных файлов в `/etc/cron.d/`.

### Логи: logrotate, journald, rsyslog

Каждый хост должен хранить логи локально (local fallback) с ротацией, даже при наличии центрального логгера.

| Инструмент | ОС | Назначение | Модуль Ansible |
| :--- | :--- | :--- | :--- |
| logrotate | Linux | Ротация статических лог-файлов | `ansible.builtin.template` + `ansible.builtin.command` |
| journald | Linux (systemd) | Локальный сбор логов в бинарном формате | `ansible.builtin.template` + `ansible.builtin.systemd` |
| rsyslog | Linux | Фильтрация и forwarding логов | `ansible.builtin.template` + `ansible.builtin.service` |
| Windows Event Log | Windows | Централизованный сбор событий | `ansible.windows.win_eventlog` |

```yaml
# logrotate для приложения
- name: Создание конфигурации logrotate
  ansible.builtin.template:
    src: logrotate.conf.j2
    dest: /etc/logrotate.d/myapp
    mode: '0644'
  when: ansible_facts['system'] != 'Win32NT'

# Принудительная проверка logrotate
- name: Проверка logrotate
  ansible.builtin.command: logrotate -d /etc/logrotate.d/myapp
  register: logrotate_check
  changed_when: false
  failed_when: "'error' in logrotate_check.stdout.lower()"
  when: ansible_facts['system'] != 'Win32NT'
```

```yaml
# journald: настройка ротации и retention
- name: Настройка journald
  ansible.builtin.template:
    src: journald.conf.j2
    dest: /etc/systemd/journald.conf
    mode: '0644'
  notify: restart journald
  when: ansible_facts['service_mgr'] == 'systemd'
```

```ini
# templates/journald.conf.j2
[Journal]
SystemMaxUse=1G
MaxRetentionSec=30day
ForwardToSyslog=yes
```

```yaml
# rsyslog: отправка логов в центральный сервер
- name: Установка rsyslog
  ansible.builtin.package:
    name: rsyslog
    state: present
  when: ansible_facts['os_family'] == 'RedHat' or ansible_facts['os_family'] == 'Debian'

- name: Конфигурация rsyslog для forwarding
  ansible.builtin.template:
    src: rsyslog-forward.conf.j2
    dest: /etc/rsyslog.d/50-forward.conf
    mode: '0644'
  notify: restart rsyslog
  when: ansible_facts['os_family'] == 'RedHat' or ansible_facts['os_family'] == 'Debian'
```

> **Production note:** Локальный fallback обязателен — каждый хост должен хранить логи локально (journald/rsyslog) на случай отключения центра. На Windows логи пишутся в Event Log; для централизации используйте `ansible.windows.win_eventlog` или forwarding через WEF (Windows Event Forwarding). `logrotate` работает на всех Linux-дистрибутивах; на macOS используйте `newsyslog` или `log rotate` через `launchd`. Systemd 261+ включает улучшенную journal recovery и compaction.

### Файловые системы и монтирование

`ansible.builtin.mount` управляет точками монтирования через `/etc/fstab` (Linux/BSD) или `/etc/vfstab` (Solaris).

| Файловая система | Модуль Ansible | Особенности |
| :--- | :--- | :--- |
| XFS | `ansible.builtin.mount` | Только увеличивание, нельзя уменьшить |
| ext4 | `ansible.builtin.mount` | Универсальная, поддерживает уменьшение |
| Btrfs | `community.general.btrfs` | Snapshots, subvolumes |
| ZFS | `community.general.zfs` | Пулы, snapshots, checksumming |
| tmpfs | `ansible.builtin.mount` | RAM-диск, для `/tmp`, `/run` |

```yaml
# Монтирование XFS через fstab
- name: Создание файловой системы
  ansible.builtin.filesystem:
    fstype: xfs
    dev: /dev/sdb1
  when: ansible_facts['system'] != 'Win32NT'

- name: Монтирование и добавление в fstab
  ansible.builtin.mount:
    path: /data
    src: /dev/sdb1
    fstype: xfs
    state: mounted
    opts: defaults,noatime,nobarrier
  when: ansible_facts['system'] != 'Win32NT'
```

```yaml
# tmpfiles.d для /run (systemd)
- name: Создание временной директории через tmpfiles.d
  ansible.builtin.template:
    src: myapp.conf.j2
    dest: /etc/tmpfiles.d/myapp.conf
    mode: '0644'
  when: ansible_facts['service_mgr'] == 'systemd'
```

```ini
# templates/myapp.conf.j2
d /run/myapp 0755 deploy deploy -
```

> **Production note:** На Windows монтирование управляется через `ansible.windows.win_format` + `ansible.windows.win_mount`. `/etc/fstab` не существует — используется реестр (`HKLM:\SYSTEM\CurrentControlSet\Services\mountmgr`). Для временных директорий на Windows используйте `ansible.windows.win_file` с `state: directory`. На macOS монтирование через `/etc/fstab` или `autofs`. Systemd 262 включает улучшенную поддержку IMDSD и TPM-backed encryption для монтирования.

### Hostname, locale и региональные параметры

Базовые параметры системы часто игнорируются, но критичны для кластеров и соответствия политикам.

```yaml
# Установка hostname
- name: Установка статического hostname
  ansible.builtin.hostname:
    name: "{{ inventory_hostname }}"
  become: yes
  when: ansible_facts['system'] != 'Win32NT'

# Установка locale
- name: Генерация locale
  community.general.locale_gen:
    name: "{{ locale | default('en_US.UTF-8') }}"
    state: present
  become: yes
  when: ansible_facts['system'] != 'Win32NT'
```

### Управление PAM и лимитами ресурсов

Лимиты ресурсов (nofile, nproc) управляются через PAM. Для production-сервисов требуется отдельная настройка.

```yaml
# Установка лимитов для сервисного аккаунта
- name: Настройка лимитов для deploy пользователя
  ansible.builtin.pam_limits:
    domain: deploy
    limit_type: soft
    limit_item: nofile
    value: '65536'
  become: yes
  when: ansible_facts['system'] != 'Win32NT'
```

> **Production note:** Для production-сервисов создавайте отдельные файлы в `/etc/security/limits.d/` вместо редактирования общего `limits.conf`. Это предотвращает конфликты при обновлениях пакетов. Рекомендуемые значения: `nofile` 65536–131072 для веб-серверов и СУБД, `nproc` 65536.

## Практические сценарии

### Сценарий 1: Комплексный sysctl для СУБД (PostgreSQL)

```yaml
- name: Тюнинг ядра для PostgreSQL
  ansible.posix.sysctl:
    name: "{{ item.name }}"
    value: "{{ item.value }}"
    state: present
    sysctl_file: /etc/sysctl.d/99-postgresql.conf
    reload: yes
  loop:
    - { name: 'vm.swappiness', value: '10' }
    - { name: 'vm.overcommit_memory', value: '2' }
    - { name: 'vm.dirty_ratio', value: '10' }
    - { name: 'vm.dirty_background_ratio', value: '3' }
    - { name: 'fs.file-max', value: '2097152' }
    - { name: 'kernel.sem', value: '250 256000 100 1024' }
  become: yes
  when: ansible_facts['system'] != 'Win32NT'
```

### Сценарий 2: Chrony + timezone для mixed-парка

```yaml
- name: Установка timezone
  ansible.builtin.timezone:
    name: "{{ timezone | default('Europe/Moscow') }}"
  become: yes
  when: ansible_facts['system'] != 'Win32NT'

- name: Установка chrony (Linux)
  ansible.builtin.package:
    name: chrony
    state: present
  when: ansible_facts['os_family'] == 'RedHat' or ansible_facts['os_family'] == 'Debian'

- name: Настройка chrony с NTS
  community.general.chrony:
    servers:
      - "0.ru.pool.ntp.org iburst"
      - "1.ru.pool.ntp.org iburst"
    driftfile: /var/lib/chrony/drift
    service: started
    enabled: yes
  become: yes
  when: ansible_facts['os_family'] == 'RedHat' or ansible_facts['os_family'] == 'Debian'

- name: Проверка синхронизации времени
  ansible.builtin.command: chronyc tracking
  register: chrony_status
  changed_when: false
  when: ansible_facts['os_family'] == 'RedHat' or ansible_facts['os_family'] == 'Debian'
```

### Сценарий 3: Systemd timer для periodic cleanup

```yaml
- name: Развертывание cleanup сервиса
  ansible.builtin.template:
    src: cleanup.service.j2
    dest: /etc/systemd/system/cleanup.service
    mode: '0644'
  notify: systemd daemon-reload
  when: ansible_facts['service_mgr'] == 'systemd'

- name: Развертывание cleanup таймера
  ansible.builtin.template:
    src: cleanup.timer.j2
    dest: /etc/systemd/system/cleanup.timer
    mode: '0644'
  notify: systemd daemon-reload
  when: ansible_facts['service_mgr'] == 'systemd'

- name: Запуск таймера
  ansible.builtin.systemd:
    name: cleanup.timer
    state: started
    enabled: yes
  when: ansible_facts['service_mgr'] == 'systemd'
```

### Сценарий 4: Логирование: journald + rsyslog + logrotate

```yaml
- name: Настройка journald retention
  ansible.builtin.template:
    src: journald.conf.j2
    dest: /etc/systemd/journald.conf
    mode: '0644'
  notify: restart journald
  when: ansible_facts['service_mgr'] == 'systemd'

- name: Установка rsyslog
  ansible.builtin.package:
    name: rsyslog
    state: present
  when: ansible_facts['system'] != 'Win32NT'

- name: Forwarding логов в центральный сервер
  ansible.builtin.template:
    src: rsyslog-forward.conf.j2
    dest: /etc/rsyslog.d/50-forward.conf
    mode: '0644'
  notify: restart rsyslog
  when: ansible_facts['system'] != 'Win32NT'

- name: Ротация логов приложения
  ansible.builtin.template:
    src: logrotate.conf.j2
    dest: /etc/logrotate.d/myapp
    mode: '0644'
  when: ansible_facts['system'] != 'Win32NT'
```

### Сценарий 5: Монтирование файловых систем (Linux/macOS)

```yaml
- name: Создание XFS на новом диске
  ansible.builtin.filesystem:
    fstype: xfs
    dev: /dev/sdb1
  when: ansible_facts['system'] == 'Linux'

- name: Монтирование и добавление в fstab
  ansible.builtin.mount:
    path: /data
    src: /dev/sdb1
    fstype: xfs
    state: mounted
    opts: defaults,noatime,nobarrier
  when: ansible_facts['system'] == 'Linux'

- name: Создание tmpfs для кэша
  ansible.builtin.mount:
    path: /tmp/myapp
    src: tmpfs
    fstype: tmpfs
    state: mounted
    opts: size=2G,mode=1777
  when: ansible_facts['system'] == 'Linux'
```

### Сценарий 6: Hostname, timezone, locale для нового сервера

```yaml
- name: Базовая конфигурация нового сервера
  hosts: new_servers
  gather_facts: yes
  tasks:
    - name: Установка hostname
      ansible.builtin.hostname:
        name: "{{ inventory_hostname }}"
      become: yes
      when: ansible_facts['system'] != 'Win32NT'

    - name: Установка timezone
      ansible.builtin.timezone:
        name: "{{ timezone | default('Europe/Moscow') }}"
      become: yes
      when: ansible_facts['system'] != 'Win32NT'

    - name: Генерация locale
      community.general.locale_gen:
        name: "{{ locale | default('en_US.UTF-8') }}"
        state: present
      become: yes
      when: ansible_facts['system'] != 'Win32NT'

    - name: Создание сервисного аккаунта
      ansible.builtin.user:
        name: deploy
        system: yes
        shell: /usr/sbin/nologin
        create_home: no
      become: yes
      when: ansible_facts['system'] != 'Win32NT'
```

### Сценарий 7: PAM limits для высоконагруженного сервиса

```yaml
- name: Настройка лимитов для веб-сервиса
  ansible.builtin.pam_limits:
    domain: deploy
    limit_type: soft
    limit_item: nofile
    value: '131072'
  become: yes
  when: ansible_facts['system'] != 'Win32NT'

- name: Настройка жесткого лимита nofile
  ansible.builtin.pam_limits:
    domain: deploy
    limit_type: hard
    limit_item: nofile
    value: '131072'
  become: yes
  when: ansible_facts['system'] != 'Win32NT'
```

## Операции и команды

| Команда | Назначение | Ожидаемый результат |
| :--- | :--- | :--- |
| `ansible all -m ansible.builtin.setup -a "filter=ansible_sysctl*"` | Проверка собранных sysctl фактов | `"ansible_facts": { "sysctl": {...} }` |
| `sysctl -a \| grep vm.swappiness` | Проверка параметра ядра | `vm.swappiness = 10` |
| `sysctl --system` | Применение всех `/etc/sysctl.d/*.conf` | `Applying /etc/sysctl.d/99-performance.conf ...` |
| `chronyc tracking` | Проверка статуса chrony | `Reference ID`, `Stratum`, `System time` |
| `timedatectl status` | Проверка времени и timezone | `Time zone: Europe/Moscow (MSK, +0300)` |
| `systemctl list-timers` | Список активных таймеров | Таблица таймеров с следующим запуском |
| `logrotate -d /etc/logrotate.d/myapp` | Проверка конфигурации logrotate | `reading config file` без ошибок |
| `journalctl --disk-usage` | Проверка размера journald | `Archived and active journals take up 1.2G` |
| `mount | grep /data` | Проверка mounted точек | `/dev/sdb1 on /data type xfs` |
| `df -h /data` | Проверка использования диска | `Filesystem Size Used Avail` |
| `ansible all -m ansible.builtin.stat -a "path=/data"` | Проверка точки монтирования | `stat.exists: true`, `stat.isdir: true` |
| `hostnamectl status` | Проверка hostname и systemd info | `Static hostname`, `Icon name`, `Chassis` |
| `locale` | Проверка текущей locale | `LANG=en_US.UTF-8` |
| `ulimit -n` | Проверка лимита открытых файлов | `65536` |
| `journalctl -u myapp --since "1 hour ago"` | Просмотр логов сервиса | Вывод логов за последний час |
| `rsyslogd -N1` | Проверка конфигурации rsyslog | `rsyslogd: Check End` |

## Диагностика и устранение неполадок

### sysctl

| Симптом | Причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| `sysctl: permission denied` | Недостаточно прав | `sudo sysctl -w vm.swappiness=10` | Используйте `become: yes` в Ansible |
| `sysctl: setting key not found` | Параметр не поддерживается ядром | `sysctl -a \| grep vm.swappiness` | Проверьте поддержку параметра в текущем ядре |
| `sysctl: cannot stat /proc/sys/...` | Ядро собрано без поддержки | `zcat /proc/config.gz \| grep CONFIG_SWAP` | Пересоберите ядро с нужным параметром |
| Изменения не сохраняются после reboot | Отсутствует файл в `/etc/sysctl.d/` | `ls /etc/sysctl.d/` | Убедитесь, что `sysctl_file` указан правильно |

### NTP и время

| Симптом | Причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| `chronyc: Cannot talk to daemon` | chronyd не запущен | `systemctl status chronyd` | `systemctl start chronyd` |
| `System clock not synchronized` | Нет связи с NTP-сервером | `chronyc sources -v` | Проверьте firewall, DNS, доступность NTP-серверов |
| `Server not found (NTS)` | NTS не поддерживается сервером | `chronyc -N authdata` | Используйте серверы с NTS или отключите NTS |
| `Time drift > 5 seconds` | Нестабильная сеть или виртуальная машина | `chronyc tracking` | Проверьте `maxdelay` и `maxdelaydevratio` в конфигурации |
| `timedatectl shows "NTP synchronized: no"` | NTP-сервис отключен | `timedatectl status` | Включите `systemd-timesyncd` или `chronyd` |

### Systemd timers

| Симптом | Причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| `Timer unit not found` | Файл timer не создан или не загружен | `systemctl list-unit-files \| grep cleanup` | Убедитесь, что файл `.timer` существует и `daemon-reload` выполнен |
| `Timer not triggered` | `Persistent=true` отсутствует или `OnCalendar` неверен | `systemctl status cleanup.timer` | Проверьте синтаксис `OnCalendar`, добавьте `Persistent=true` |
| `Service failed but timer succeeded` | Ошибка в сервисе, а не в таймере | `journalctl -u cleanup.service` | Проверьте логи сервиса, убедитесь в идемпотентности |

### Логирование

| Симптом | Причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| `journald: Disk space threshold reached` | `SystemMaxUse` превышен | `journalctl --disk-usage` | Увеличьте `SystemMaxUse` или очистите старые логи (`journalctl --vacuum-time=7d`) |
| `logrotate: error: stat` | Файл логов отсутствует | `ls -la /var/log/myapp/` | Создайте файл или настройте `create` в конфигурации |
| `rsyslog: connection refused` | rsyslog не запущен | `systemctl status rsyslog` | `systemctl start rsyslog` |
| `Logs lost after rotation` | `copytruncate` отсутствует или приложение не переоткрывает файл | `journalctl -u myapp` | Используйте `copytruncate` в logrotate или отправляйте логи в journald |

### Файловые системы

| Симптом | Причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| `mount: wrong fs type` | Неправильный `fstype` или модуль ядра не загружен | `blkid /dev/sdb1` | Проверьте тип ФС, загрузите модуль (`modprobe xfs`) |
| `XFS: cannot shrink` | XFS не поддерживает уменьшение | `xfs_growfs` | Используйте `xfs_growfs` только для увеличения |
| `tmpfs: No space left on device` | `size` опция превышает RAM+swap | `df -h /tmp/myapp` | Уменьшите `size` в опциях монтирования |
| `fstab: mount error` | Неверные опции или устройство | `mount -a` | Проверьте `/etc/fstab` синтаксис, опции монтирования |

### Граничные случаи и ограничения

- **Windows и sysctl**: нет прямого аналога. Параметры ядра настраиваются через реестр (`ansible.windows.win_regedit`).
- **Chrony vs systemd-timesyncd**: chrony — для серверов и рабочих станций; systemd-timesyncd — для контейнеров и минимальных установок.
- **MacOS и sysctl**: работает через `ansible.builtin.command` или `ansible.posix.sysctl` (если установлен Python). SIP ограничивает изменения некоторых параметров.
- **logrotate и journald**: если сервис пишет в journald, `logrotate` для его статических логов может не требоваться. Используйте `MaxRetentionSec` в journald.
- **XFS и уменьшение**: XFS нельзя уменьшить (`shrink`). Только увеличивать (`grow`). Для изменения размера используйте `ansible.builtin.command: xfs_growfs`.
- **tmpfiles.d и права**: директивы `d` создают директории с указанными правами и владельцем. Работает только на systemd-системах.
- **mount и Windows**: используйте `ansible.windows.win_format` + `ansible.windows.win_mount`. `/etc/fstab` не существует.
- **ZFS и ядро**: модули ZFS должны быть загружены (`modprobe zfs`). Проверяйте через `ansible.builtin.command: lsmod | grep zfs`.
- **SELinux и монтирование**: после изменения контекстов SELinux используйте `restorecon` для восстановления правильных меток.
- **PAM limits и systemd**: systemd игнорирует `limits.conf` для сервисов, запущенных через `systemd`. Используйте `LimitNOFILE=` в unit-файле.
- **systemd-timesyncd и chrony**: не запускайте оба одновременно. Используйте `systemctl disable --now systemd-timesyncd` при установке chrony.

## Рекомендации и лучшие практики

1. **`sysctl_file` вместо `/etc/sysctl.conf`**: модульность, предотвращение конфликтов при обновлениях.
2. **Chrony вместо ntpd**: лучше для виртуальных машин и нестабильных сетей. Chrony 4.8+ поддерживает NTS.
3. **Systemd timers вместо cron**: точность, `Persistent=true`, интеграция с journald.
4. **Local fallback для логов**: каждый хост должен хранить логи локально, даже при центральном логгере.
5. **`logrotate` для статических логов**: journald сам управляет размером, но статические файлы требуют `logrotate`.
6. **`noatime,nobarrier` для дисков**: уменьшает I/O, но оцените риски для отказоустойчивости.
7. **tmpfs для `/tmp` и кэшей**: ускоряет доступ, но данные теряются при перезагрузке.
8. **`mount` вместо `command`**: декларативный подход, идемпотентность, автоматическая запись в fstab.
9. **Проверка применения sysctl**: `sysctl --system` или `ansible.builtin.command: sysctl -p /etc/sysctl.d/99-*.conf`.
10. **`journald` retention**: настройте `SystemMaxUse` и `MaxRetentionSec` для контроля размера.
11. **Chrony NTS**: используйте NTP-серверы с поддержкой NTS для аутентификации времени.
12. **Проверка синхронизации**: регулярно проверяйте `chronyc tracking` и `chronyc sources` в мониторинге.
13. **Capacity planning для `fs.file-max`**: при parc > 500 узлов увеличивайте `fs.file-max` постепенно, контролируя `nofile` лимиты.
14. **`hostname` через `hostnamectl`**: используйте `ansible.builtin.hostname` вместо ручного редактирования `/etc/hostname`.
15. **`locale` через `locale_gen`**: используйте `community.general.locale_gen` вместо ручного редактирования `/etc/locale.gen`.
16. **PAM limits через `/etc/security/limits.d/`**: создавайте отдельные файлы для каждого сервиса, а не редактируйте общий `limits.conf`.
17. **Тестируйте изменения на pilot-группе**: при изменении `sysctl`, `sysctl_file` или системных параметров тестируйте на небольшой группе хостов перед массовым применением.
18. **Используйте Molecule**: тестируйте идемпотентность и корректность конфигурации на изолированных инстансах.

## Дополнительная информация

- [Управление параметрами ядра (sysctl)](../../Linux/Core/kernel/sysctl.md) — полный справочник параметров ядра Linux.
- [Модули управления службами и системой](../Modules/ansible_service_and_system_config_modules.md) — `sysctl`, `timezone`, `chrony`, `mount`, `systemd`, `pam_limits`.
- [Модули управления файловыми системами и хранилищем](../Modules/ansible_storage_and_disk_management_modules.md) — `filesystem`, `mount`, `zfs`, `btrfs`, `lvg`, `lvol`.
- [Управление логами](../examples/ansible_log_management.md) — `logrotate`, `rsyslog`, `journald`, централизованный сбор.
- [Кроссплатформенные концепции](./concepts.md) — матрица платформ, `ansible_facts`, общие паттерны.
- [Кроссплатформенное выполнение](./ansible_cross_platform_execution_flow.md) — `strategy`, `serial`, `throttle`, `check_mode`, `async`, `tags`, `--limit`.
