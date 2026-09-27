# Ansible: Модули управления службами и системой

## Версионирование и требования

| Компонент | Минимальная версия | Рекомендуемая версия |
| :--- | :--- | :--- |
| **ansible-core** | 2.15+ | 2.21+ |
| **Python** (control node) | 3.12+ | 3.14 |
| **Python** (managed node) | 3.9+ | 3.12+ |
| **systemd** (целевые хосты) | 235+ | Актуальная LTS |
| **rsync** (для модуля synchronize) | 3.1+ | 3.2+ |
| **sudo** (целевые хосты) | 1.8+ | Актуальная LTS |

**Проверка окружения:**
```bash
ansible --version | head -1
# → ansible [core 2.21.4]

ansible all -m ping
# → pong: web01
# → pong: db01
```

## Определения

**Модули управления службами и системой** — группа специализированных декларативных инструментов Ansible (преимущественно `ansible.builtin` и `ansible.posix`), предназначенных для администрирования жизненного цикла сервисов, тонкой настройки ядра Linux, управления системными ресурсами, лимитами и региональными параметрами.

**FQCN (Fully Qualified Collection Name)** — полное имя модуля, включающее пространство имен и коллекцию (например, `ansible.builtin.systemd`). Использование FQCN является обязательным стандартом для предотвращения конфликтов имен и обеспечения предсказуемости выполнения во всех современных версиях Ansible.

**Systemd unit** — основной объект управления в systemd: служба (`.service`), точка монтирования (`.mount`), таймер (`.timer`), сокет (`.socket`), целевой объект (`.target`). Каждый unit описывается секциями `[Unit]`, `[Service]`, `[Install]` в текстовом файле INI-формата.

**Cgroup (Control Group)** — механизм ядра Linux для ограничения, учета и приоритизации ресурсов (CPU, память, disk I/O) для групп процессов. Systemd использует cgroups v2 для управления ресурсами сервисов.

**Systemd timer** — аналог cron в рамках systemd, реализованный через unit-файлы `.timer`. Таймеры поддерживают точность до секунды, интеграцию с journald, calendar-спецификации и могут быть привязаны к конкретным сервисам.

**Runlevel / Target** — уровень выполнения системы. В systemd заменен на targets (например, `multi-user.target`, `graphical.target`). Целевые объекты определяют, какие сервисы должны быть активны на данном уровне.

**SELinux context** — метка безопасности, назначаемая файлам, процессам и сетевым портам в политике SELinux. Контекст состоит из: пользователя, роли, типа и уровня (MLS/MCS). Корректные контексты критичны для работы защищенных сервисов.

**Sysctl namespace** — иерархия параметров ядра Linux в виртуальной файловой системе `/proc/sys/`. Разделы: `net` (сеть), `fs` (файловые системы), `kernel` (ядро), `vm` (виртуальная память), `dev` (устройства).

**PAM (Pluggable Authentication Modules)** — фреймворк Linux для интеграции различных методов аутентификации. Файл `/etc/security/limits.conf` и директория `/etc/security/limits.d/` управляют лимитами ресурсов через PAM-модуль `pam_limits.so`.

**Сервисный аккаунт** — выделенная учетная запись пользователя, созданная для запуска конкретного приложения или сервиса. Рекомендуется использовать `system: yes` и `shell: /usr/sbin/nologin` для минимизации поверхности атаки.

### Возвращаемые данные (Return Values)

**Модули управления службами (`systemd`, `service`):**

| Параметр | Тип | Описание |
|----------|-----|----------|
| `name` | string | Имя управляемого ресурса |
| `state` | string | Текущее состояние ресурса |
| `changed` | boolean | Были ли произведены изменения |
| `enabled` | boolean | Включена ли служба в автозагрузку |
| `status` | dict | Детальная информация о состоянии |
| `invocation` | dict | Параметры вызова модуля |

**`service_facts` — `ansible_facts.services`:**

| Поле | Тип | Описание |
|------|-----|----------|
| `status` | string | `active`, `inactive`, `failed`, `activating` |
| `sub` | string | Подсостояние: `running`, `exited`, `dead`, `failed` |
| `loaded` | boolean | Загружен ли unit |
| `enabled` | boolean | Включена ли автозагрузка |
| `pid` | integer | PID главного процесса (для running) |
| `memory` | dict | Потребление памяти по cgroup |

**`sysctl`:**

| Параметр | Тип | Описание |
|----------|-----|----------|
| `value` | string | Текущее значение параметра |
| `changed` | boolean | Было ли значение изменено |
| `cmd` | string | Выполненная команда sysctl |

## Основные концепции

### Управление жизненным циклом служб

**Архитектура systemd:**
Systemd — это не просто менеджер инициализации (PID 1), а комплексная платформа управления системой, включающая journald (логи), logind (сессии), networkd (сеть), resolved (DNS), timesyncd (время) и другие компоненты. Все компоненты обмениваются событиями через D-Bus.

**Жизненный цикл unit-файла:**
```
Создание/обновление unit-файла →
daemon-reload (перечитывание конфигурации) →
enabling (создание симлинка в .wants/) →
starting (запуск процесса) →
running (активное состояние) →
stopping (остановка) →
disabled (удаление симлинка)
```

**Модули управления службами:**

1.  **`ansible.builtin.service`**: Модуль-абстракция, работающий через системный менеджер инициализации по умолчанию. Автоматически определяет систему (systemd, SysVinit, OpenRC). Рекомендуется для обеспечения кроссплатформенности ролей. При использовании с systemd не поддерживает продвинутые параметры (`daemon_reload`, `scope`, `masked`).
2.  **`ansible.builtin.systemd`**: Специализированный модуль для систем с systemd. Поддерживает продвинутые функции:
     *   **`daemon_reload`**: Перечитывает конфигурацию systemd с диска. Необходимо вызывать после изменения unit-файлов. Без этого новый unit-файл не будет обнаружен systemd.
     *   **`daemon_reexec`**: Полный перезапуск самого процесса systemd (актуально при обновлении пакета systemd). Вызывает `systemctl daemon-reexec`.
     *   **`scope`**: Позволяет управлять юнитами на уровне системы (`system`) или пользователя (`user`). При использовании `user` задачи обычно выполняются без `become: true`, но требуют настроенного ` lingering` для пользователя.
     *   **`masked`**: Состояние, полностью блокирующее возможность запуска службы (даже вручную или по зависимости). Модуль может установить `masked: yes/no`.
     *   **`force`**: При `state: stopped` принудительно завершает процесс, игнорируя `ExecStop`.
     *   **`user` / `group`**: Пользователь и группа, от имени которых запускается сервис. Должны существовать на системе.
 3.  **`ansible.builtin.service_facts`**: Сбор состояния всех известных сервисов в переменную `ansible_facts.services`. Позволяет строить сложную логику проверки работоспособности инфраструктуры через условия `when`.
 4.  **`ansible.builtin.wait_for`**: Ожидание наступления определенного условия (открытие порта, наличие файла, завершение процесса). Поддерживает `host`, `port`, `path`, `state`, `timeout`, `sleep`.
 5.  **`ansible.builtin.wait_for_connection`**: Ожидание восстановления подключения к хосту после перезагрузки. Используется в сочетании с `reboot` модулем для гарантии, что хост снова доступен по SSH перед продолжением плейбука. Требует `timeout` для предотвращения бесконечного ожидания.
 6.  **`ansible.builtin.at`**: Планирование выполнения команды через `atd`. Позволяет запустить задачу один раз в указанное время. Поддерживает `command`, `script`, `state` (present/absent), `count`, `units` (minutes/hours/days/weeks/months).

**Состояния unit-файлов в systemd:**

| Состояние | Описание |
|-----------|----------|
| `active` | Сервис запущен и работает |
| `inactive` | Сервис остановлен, но может быть запущен |
| `failed` | Сервис завершился с ошибкой |
| `activating` | Процесс запуска в progress |
| `deactivating` | Процесс остановки в progress |
| `masked` | Сервис заблокирован (symlink на /dev/null) |

### Привилегированный доступ (become)

Для управления службами, монтированием, параметрами ядра и другими защищенными ресурсами требуется root-доступ. Используйте `become: yes`.

```yaml
- name: "Перезагрузка systemd после изменения unit-файла"
  ansible.builtin.systemd:
    name: myapp
    daemon_reload: yes
  become: yes
  # → changed: [web01] => (item=None)
```

**Альтернатива для systemd:** параметр `sysupdate_path` или выполнение через `become: yes`. Для `ansible.posix.sysctl` с `reload: yes` также требуется `become: yes`.

### Настройка ресурсов и ядра Linux

**`ansible.posix.sysctl`**: Управление параметрами ядра через интерфейс `/proc/sys`.
*   **`sysctl_file`**: Позволяет сохранять настройки в отдельные файлы (например, `/etc/sysctl.d/99-performance.conf`). Это предпочтительнее редактирования `/etc/sysctl.conf`, так как обеспечивает модульность и предотвращает конфликты при обновлениях пакетов.
*   **`reload`**: Применяет параметры немедленно (`sysctl -p`). Требует `become: yes`.
*   **`ignoreerrors`**: Если `yes`, продолжает выполнение даже при ошибке применения параметра (например, если параметр не поддерживается ядром).
*   **Значения**: Для числовых параметров используйте кавычки: `value: '1024'`. Для строковых — без кавычек или в кавычках в зависимости от типа.

**`ansible.builtin.modprobe`**: Управление модулями ядра (загрузка и выгрузка). Позволяет декларативно гарантировать наличие необходимых драйверов или расширений ядра.
*   **`state`**: `present` (загрузить модуль) или `absent` (выгрузить модуль).
*   **Ограничение**: `modprobe` управляет только модулями, загруженными в текущем сеансе. Для постоянной загрузки при загрузке системы используйте файлы в `/etc/modules-load.d/`.

**`ansible.builtin.pam_limits`**: Настройка лимитов ресурсов (nofile, nproc) в `/etc/security/limits.conf`.
*   **`limit_type`**: `soft` (предупреждение), `hard` (жесткий запрет) или `-` (оба одновременно).
*   **`domain`**: Пользователь, группа или `*` (все).
*   **Лучшая практика**: Используйте отдельные файлы в `/etc/security/limits.d/` для каждого сервиса, а не общий `limits.conf`.

**`ansible.posix.selinux`**: Управление режимами работы SELinux (`enforcing`, `permissive`, `disabled`). Важно помнить, что переход из `disabled` в `enforcing` требует перезагрузки и перемаркировки файловой системы.
*   **`policy`**: `targeted` (стандартная политика RHEL/CentOS) или `mls` (multi-level security).
*   **`state`**: `enforcing`, `permissive`, `disabled`.
*   **Важно**: После изменения SELinux-контекстов используйте `restorecon` для восстановления правильных меток, а не `chcon` (который изменяет контекст временно).

### Управление пользователями и группами

**`ansible.builtin.user`**: Создание, модификация, блокировка и удаление пользователей. Управление домашними директориями, оболочками (shell), хешированными паролями, сроками их действия и автоматической генерацией SSH-ключей.
*   **`system`**: Если `yes`, создает системного пользователя без домашней директории по умолчанию (UID < 1000).
*   **`shell`**: Указывайте полный путь к оболочке. Для сервисных аккаунтов используйте `/usr/sbin/nologin` или `/bin/false`.
*   **`password_lock`**: Если `yes`, блокирует учетную запись (ставит `!` в парольный хеш).
*   **`expires`**: Дата истечения счета в формате YYYY-MM-DD.
*   **`ssh_key_ecdsa_public_key`**: Размещение ECDSA-ключа в `~/.ssh/authorized_keys`.

**`ansible.builtin.group`**: Управление системными группами и их GID.
*   **`gid`**: Явное указание GID (рекомендуется для системных групп).
*   **`system`**: Если `yes`, создает системную группу (GID < 1000).

### Управление хранилищем и сетевой безопасностью

**`ansible.builtin.mount`**: Декларативное управление точками монтирования в `/etc/fstab`.
*   **Состояния (`state`)**:
    *   `mounted`: Добавление в `fstab` и немедленное монтирование.
    *   `unmounted`: Размонтирование, но сохранение записи в `fstab`.
    *   `present`: Только добавление записи в `fstab`.
    *   `absent`: Размонтирование и удаление записи из `fstab`.
*   **`opts`**: Параметры монтирования (например, `defaults,noatime,nobarrier` для XFS/ext4).
*   **`dump` / `passno`**: Параметры для `dump` и `fsck`. Для корневой файловой системы `passno=1`, для остальных — `2`, для не-FS (`swap`, `tmpfs`) — `0`.

**`ansible.posix.firewalld` / `community.general.ufw`**: Высокоуровневое управление правилами брандмауэра. Для `firewalld` критично использовать `permanent: true` и `immediate: true` для синхронизации текущего и сохраненного состояний.

### Региональные параметры и время

**`ansible.builtin.hostname`**: Установка статического имени хоста. Работает через `hostnamectl` на systemd-системах или напрямую изменяет файлы на старых системах.

**`ansible.builtin.timezone`**: Настройка системного часового пояса. Использует `timedatectl` на systemd-системах или изменяет `/etc/localtime` symlink.

**`community.general.locale_gen`**: Генерация и настройка системных локалей для поддержки корректной кодировки и региональных стандартов. Изменяет `/etc/locale.gen` и запускает `locale-gen`.

**`community.general.ntp`**: Управление конфигурацией NTP-клиента. Настройка серверов времени, переключение между NTP и chrony.
*   **`server`**: Список NTP-серверов для синхронизации времени.
*   **`iburst`**: Использование burst-режима для быстрой синхронизации при старте.
*   **`ntpd`**: Путь к демону ntpd (обычно `/usr/sbin/ntpd` или `/usr/sbin/chronyd`).

**`community.general.chrony`**: Управление службой chrony (NTP-клиент). Настройка серверов, ключей, опций синхронизации.
*   **`servers`**: Список NTP-серверов с опциями (iburst, prefer).
*   **`config`**: Словарь дополнительных параметров конфигурации chrony.
*   **`service`**: Управление службой chrony (started, stopped, restarted).
*   **`state`**: Управление службой (`started`, `stopped`, `restarted`).

### Системное планирование и обслуживание

**`ansible.builtin.cron`**: Управление заданиями в планировщике.
*   **`cron_file`**: Позволяет создавать отдельные файлы в `/etc/cron.d/` вместо редактирования общего `crontab`. Это упрощает управление и предотвращает конфликты при автоматизации.
*   **`user`**: Пользователь, от имени которого выполняется задача. По умолчанию — пользователь, запустивший crontab.
*   **`minute`, `hour`, `day`, `month`, `weekday`**: Поля временной спецификации. Используйте `*` для "любое значение", `*/5` для "каждые 5 единиц".

**`ansible.builtin.reboot`**: Модуль для безопасной перезагрузки. Дожидается доступности SSH-порта (или другого условия через `test_command`, например `whoami` или проверку доступности API) перед продолжением плейбука.
*   **`reboot_timeout`**: Максимальное время ожидания перезагрузки в секундах.
*   **`pre_reboot_delay` / `post_reboot_delay`**: Задержки перед и после перезагрузки.
*   **`test_command`**: Команда для проверки готовности системы после перезагрузки.

**Systemd timers vs Cron:**
Systemd timers предоставляют более точный контроль, интеграцию с journald и поддержку calendar-спецификаций (`OnCalendar=*:0/5` для каждых 5 минут). Cron остается предпочтительным для простых периодических задач в legacy-средах.

### Модули проверки и отладки

**`ansible.builtin.ping`**: Проверка доступности управляемых хостов и работоспособности Python на них.

**`ansible.builtin.setup`**: Сбор системных фактов (IP-адреса, ОС, архитектура CPU, смонтированные диски). Данные доступны через `ansible_facts`. Используйте `filter` для уменьшения объема собираемых данных.

**`ansible.builtin.assert`**: Прекращает выполнение, если условие не выполняется ("fail-fast" проверки).

**`ansible.builtin.fail`**: Принудительное завершение задачи с сообщением об ошибке.

**`ansible.builtin.debug`**: Вывод переменных или сообщений для отладки.

**`ansible.builtin.set_fact`**: Установка переменных во время выполнения плейбука.

**`ansible.builtin.wait_for`**: Ожидание наступления определенного условия (открытие порта, наличие файла, завершение процесса).

**`ansible.builtin.meta`**: Управление выполнением плейбука (flush_handlers, end_play, end_host).

**`ansible.builtin.get_url`**: Загрузка файлов по HTTP/HTTPS/FTP на управляемый хост.

**`ansible.builtin.uri`**: Выполнение HTTP/HTTPS запросов и проверка ответов.

## Практические сценарии

### Управление systemd service cgroups и ресурсами

Настройка лимитов CPU и памяти через systemd slice и resource control.

```yaml
- name: "Размещение unit-файла с лимитами ресурсов"
  ansible.builtin.template:
    src: templates/myapp.service.j2
    dest: /etc/systemd/system/myapp.service
    owner: root
    group: root
    mode: '0644'
  register: service_unit

- name: "Перезагрузка демона systemd"
  ansible.builtin.systemd:
    daemon_reload: yes
  when: service_unit is changed

- name: "Запуск сервиса с ограничениями"
  ansible.builtin.systemd:
    name: myapp
    state: started
    enabled: yes
  # → changed: [web01] => (item=None)
```

**Шаблон `templates/myapp.service.j2`:**
```ini
[Unit]
Description=My Application
After=network.target

[Service]
Type=simple
User=appuser
Group=appgroup
WorkingDirectory=/opt/myapp
ExecStart=/opt/myapp/bin/myapp
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

### Глубокое управление systemd (User Units)

Управление сервисом, запущенным от имени конкретного пользователя.

```yaml
- name: "Запуск пользовательского агента мониторинга"
  ansible.builtin.systemd:
    name: user-agent.service
    state: started
    enabled: true
    scope: user
  become: false # Выполняется в контексте сессии пользователя
  # → changed: [web01] => (item=None)
```

### Настройка базы данных: лимиты и тюнинг ядра

Комплексная подготовка системы для работы высоконагруженной СУБД (например, PostgreSQL).

```yaml
- name: "Тюнинг виртуальной памяти через sysctl"
  ansible.posix.sysctl:
    name: vm.swappiness
    value: '10'
    state: present
    sysctl_file: /etc/sysctl.d/database_tuning.conf
  become: yes
  # → changed: [db01] => (item=None)

- name: "Установка лимитов открытых файлов"
  ansible.builtin.pam_limits:
    domain: postgres
    limit_type: "-"
    limit_item: nofile
    value: 524288
  become: yes
  # → changed: [db01] => (item=None)

- name: "Загрузка модуля ядра XFS"
  ansible.builtin.modprobe:
    name: xfs
    state: present
  become: yes
  # → changed: [db01] => (item=None)
```

### Управление монтированием дисков

Использование UUID и различных состояний монтирования для обеспечения стабильности при смене имен устройств.

```yaml
- name: "Монтирование диска с данными по UUID"
  ansible.builtin.mount:
    path: /data
    src: UUID=b312a45c-e23f-4a3d-9f1e-1234567890ab
    fstype: xfs
    opts: defaults,noatime
    state: mounted
  become: yes
  # → changed: [storage01] => (item=None)
```

**Определение UUID диска:**
```bash
blkid /dev/sdb1
# → /dev/sdb1: UUID="b312a45c-e23f-4a3d-9f1e-1234567890ab" TYPE="xfs"
```

### Планирование через /etc/cron.d

Использование изолированных файлов для системных задач очистки.

```yaml
- name: "Добавление задачи очистки временных файлов"
  ansible.builtin.cron:
    name: "Daily cleanup"
    minute: "0"
    hour: "3"
    job: "/usr/bin/find /tmp -type f -atime +7 -delete"
    cron_file: "system-cleanup"
    user: root
  become: yes
  # → changed: [web01] => (item=None)
```

**Содержимое `/etc/cron.d/system-cleanup` после выполнения:**
```
# Ansible managed
0 3 * * * root /usr/bin/find /tmp -type f -atime +7 -delete
```

### Systemd timers вместо cron

Таймеры systemd интегрированы с journald и поддерживают calendar-спецификации.

```yaml
- name: "Создание unit-файла сервиса"
  ansible.builtin.copy:
    src: files/health-check.service
    dest: /etc/systemd/system/health-check.service
    owner: root
    group: root
    mode: '0644'
  become: yes
  notify: reload systemd

- name: "Создание unit-файла таймера"
  ansible.builtin.copy:
    src: files/health-check.timer
    dest: /etc/systemd/system/health-check.timer
    owner: root
    group: root
    mode: '0644'
  become: yes
  notify: reload systemd

- name: "Запуск таймера"
  ansible.builtin.systemd:
    name: health-check.timer
    state: started
    enabled: yes
  become: yes
  # → changed: [web01] => (item=None)
```

**Шаблон `files/health-check.timer`:**
```ini
[Unit]
Description=Health check timer

[Timer]
OnBootSec=5min
OnUnitActiveSec=5min
AccuracySec=1s

[Install]
WantedBy=timers.target
```

### Кроссплатформенное управление фаерволом

Адаптация правил под разные менеджеры в зависимости от дистрибутива.

```yaml
- name: "Открытие HTTP порта через Firewalld (RHEL)"
  ansible.posix.firewalld:
    port: 80/tcp
    permanent: true
    state: enabled
    immediate: true
  become: yes
  when: ansible_os_family == "RedHat"
  # → changed: [web01] => (item=None)

- name: "Открытие HTTP порта через UFW (Debian)"
  community.general.ufw:
    rule: allow
    port: '80'
    proto: tcp
  become: yes
  when: ansible_os_family == "Debian"
  # → changed: [web02] => (item=None)
```

### Безопасная перезагрузка после обновления ядра

Ожидание готовности системы и проверка корректности загрузки. Подробные стратегии условной перезагрузки (Debian vs RHEL) описаны в руководстве **[Patch Management: Умная перезагрузка](../ansible_patch_management.md#умная-перезагрузка-conditional-reboot)**.

```yaml
- name: "Перезагрузка после обновления ядра"
  ansible.builtin.reboot:
    reboot_timeout: 600
    pre_reboot_delay: 10
    test_command: "whoami"
  become: yes
  # → changed: [web01] => (item=None)
  # → Ожидание SSH-порта... (таймаут 600 сек)
  # → Проверка команды whoami... OK
```

### Управление модулями ядра

Гарантированная загрузка модуля для поддержки специфичной файловой системы.

```yaml
- name: "Загрузка модуля ядра XFS"
  ansible.builtin.modprobe:
    name: xfs
    state: present
  become: yes
  # → changed: [storage01] => (item=None)

- name: "Постоянная загрузка модуля при старте"
  ansible.builtin.copy:
    dest: /etc/modules-load.d/xfs.conf
    content: "xfs\n"
    owner: root
    group: root
    mode: '0644'
  become: yes

### Настройка синхронизации времени через chrony

Гарантированная синхронизация времени на серверах с использованием chrony.

```yaml
- name: "Установка chrony"
  ansible.builtin.package:
    name: chrony
    state: present
  become: yes

- name: "Настройка серверов времени"
  community.general.chrony:
    servers:
      - "0.ru.pool.ntp.org iburst"
      - "1.ru.pool.ntp.org iburst"
      - "2.ru.pool.ntp.org iburst"
    config:
      driftfile: /var/lib/chrony/drift
      makestep: 1.0 3
      rtcsync: yes
    state: started
    enabled: yes
  become: yes
  # → changed: [web01] => (item=None)

- name: "Проверка синхронизации времени"
  ansible.builtin.command: chronyc tracking
  register: chrony_status
  changed_when: false
  failed_when: chrony_status.rc != 0
```

### Управление пользователями и группами

```yaml
- name: "Создание системного пользователя для приложения"
  ansible.builtin.user:
    name: appuser
    system: yes
    shell: /usr/sbin/nologin
    home: /opt/app
    create_home: yes
    groups: appgroup
    append: yes
    state: present
  become: yes
  # → changed: [web01] => (item=None)

- name: "Создание групп для приложений"
  ansible.builtin.group:
    name: appgroup
    system: yes
    gid: 1500
    state: present
  become: yes
  # → changed: [web01] => (item=None)
```

### Загрузка файлов по URL

```yaml
- name: "Загрузка установочного пакета"
  ansible.builtin.get_url:
    url: "https://example.com/app-v1.0.tar.gz"
    dest: "/tmp/app-v1.0.tar.gz"
    mode: '0644'
    checksum: "sha256:1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef"
  # → changed: [web01] => (item=None)
```

### Выполнение HTTP-запросов и проверка API

```yaml
- name: "Проверка доступности API"
  ansible.builtin.uri:
    url: "http://localhost:8080/health"
    method: GET
    return_content: yes
  register: health_check
  until: health_check.status == 200
  retries: 5
  delay: 10
  # → changed: [web01] => (item=None)
  # → status: 200
```

### Проверка доступности сервисов

```yaml
- name: "Ожидание готовности PostgreSQL"
  ansible.builtin.wait_for:
    host: localhost
    port: 5432
    timeout: 60
    state: started
  # → changed: [db01] => (item=None)
```

### Сбор и использование фактов

```yaml
- name: "Сбор информации о системе"
  ansible.builtin.setup:
    filter: ansible_distribution*

- name: "Вывод информации о дистрибутиве"
  ansible.builtin.debug:
    var: ansible_distribution
  # → ansible_distribution: Ubuntu
```

### Условное выполнение задач

```yaml
- name: "Запуск сервиса только на CentOS"
  ansible.builtin.service:
    name: httpd
    state: started
    enabled: yes
  become: yes
  when: ansible_distribution == "CentOS"
  # → changed: [centos01] => (item=None)

- name: "Запуск сервиса только на Ubuntu"
  ansible.builtin.service:
    name: apache2
    state: started
    enabled: yes
  become: yes
  when: ansible_distribution == "Ubuntu"
  # → changed: [ubuntu01] => (item=None)
```

### Обработка ошибок с assert

```yaml
- name: "Проверка минимальной версии Python"
  ansible.builtin.assert:
    that:
      - ansible.python.version.major >= 3
      - ansible.python.version.minor >= 12
    fail_msg: "Требуется Python 3.12 или выше"
    success_msg: "Версия Python подходит"
  # → ok: [web01] => {
  # →     "msg": "Версия Python подходит"
  # → }
```

### Установка переменных во время выполнения

```yaml
- name: "Определение конфигурации на основе ОС"
  ansible.builtin.set_fact:
    package_manager: "{{ 'apt' if ansible_os_family == 'Debian' else 'yum' }}"
    service_name: "{{ 'apache2' if ansible_os_family == 'Debian' else 'httpd' }}"
```

### Управление конфигурацией через шаблоны

```yaml
- name: "Генерация конфигурации Nginx"
  ansible.builtin.template:
    src: templates/nginx.conf.j2
    dest: /etc/nginx/nginx.conf
    owner: root
    group: root
    mode: '0644'
    validate: "nginx -t -c %s"
  notify: "restart nginx"
  # → changed: [web01] => (item=None)

- name: "Перезапуск Nginx после изменений"
  ansible.builtin.systemd:
    name: nginx
    state: restarted
    daemon_reload: yes
  listen: "restart nginx"
  become: yes
```

### Проверка и восстановление сервисов

```yaml
- name: "Проверка работоспособности сервиса"
  ansible.builtin.uri:
    url: "http://localhost:8080/health"
    method: GET
    status_code: 200
  register: health_check
  ignore_errors: yes

- name: "Восстановление сервиса при сбое"
  ansible.builtin.systemd:
    name: myapp
    state: restarted
  become: yes
  when: health_check is failed
  # → changed: [web01] => (item=None)
```

### Управление сервисами с зависимостями

```yaml
- name: "Остановка зависимых сервисов"
  ansible.builtin.systemd:
    name: "{{ item }}"
    state: stopped
  loop:
    - nginx
    - php-fpm
    - redis
  become: yes
  # → changed: [web01] => (item=nginx)
  # → changed: [web01] => (item=php-fpm)
  # → changed: [web01] => (item=redis)

- name: "Обновление приложения"
  ansible.builtin.copy:
    src: "dist/app.jar"
    dest: "/opt/app/app.jar"
    owner: appuser
    group: appgroup
    mode: '0755'
  become: yes

- name: "Запуск сервисов в правильном порядке"
  ansible.builtin.systemd:
    name: "{{ item }}"
    state: started
    enabled: yes
  loop:
    - redis
    - php-fpm
    - nginx
  become: yes
  # → changed: [web01] => (item=redis)
  # → changed: [web01] => (item=php-fpm)
  # → changed: [web01] => (item=nginx)
```

### Каталожные задания через cron

```yaml
- name: "Настройка заданий для мониторинга"
  ansible.builtin.cron:
    name: "Health check"
    minute: "*/5"
    job: "/usr/local/bin/health_check.sh >> /var/log/health.log 2>&1"
    cron_file: "monitoring"
    user: monitor
  become: yes
  # → changed: [web01] => (item=None)

- name: "Настройка заданий для ротации логов"
  ansible.builtin.cron:
    name: "Log rotation"
    minute: "0"
    hour: "0"
    job: "/usr/sbin/logrotate /etc/logrotate.conf"
    cron_file: "maintenance"
    user: root
  become: yes
  # → changed: [web01] => (item=None)
```

### Управление SELinux

```yaml
- name: "Включение SELinux в режиме enforcing"
  ansible.posix.selinux:
    policy: targeted
    state: enforcing
  become: yes
  when: ansible_distribution in ["CentOS", "RedHat"]
  # → changed: [db01] => (item=None)

- name: "Установка контекста SELinux для директории"
  ansible.builtin.command:
    cmd: "chcon -R -t httpd_sys_content_t /var/www/html"
  changed_when: false
  become: yes
```

**Восстановление контекстов SELinux:**
```bash
restorecon -Rv /var/www/html
# → restorecon reset /var/www/html/index.html context unconfined_u:object_r:user_home_t:s0->system_u:object_r:httpd_sys_content_t:s0
```

### Настройка временной зоны и локалей

```yaml
- name: "Установка часового пояса"
  ansible.builtin.timezone:
    name: Europe/Moscow
  become: yes
  # → changed: [web01] => (item=None)

- name: "Генерация русской локали"
  community.general.locale_gen:
    name: ru_RU.UTF-8
    state: present
  become: yes
  # → changed: [web01] => (item=None)
```

### Управление сервисами с async

```yaml
- name: "Долгая операция с проверкой статуса"
  ansible.builtin.command:
    cmd: "/opt/app/backup.sh"
  async: 3600
  poll: 0
  register: backup_job
  become: yes

- name: "Ожидание завершения бэкапа"
  ansible.builtin.async_status:
    jid: "{{ backup_job.ansible_job_id }}"
  register: job_result
  until: job_result.finished
  retries: 60
  delay: 60
  # → changed: [web01] => (item=None)
  # → job_result.finished: true
```

### Безопасное управление сервисами

```yaml
- name: "Остановка сервиса для обслуживания"
  ansible.builtin.systemd:
    name: myapp
    state: stopped
  become: yes
  become_user: root
  register: service_stopped
  # → changed: [web01] => (item=None)

- name: "Выполнение обслуживания"
  ansible.builtin.command:
    cmd: "/opt/app/maintenance.sh"
  when: service_stopped.changed

- name: "Запуск сервиса после обслуживания"
  ansible.builtin.systemd:
    name: myapp
    state: started
    enabled: yes
  become: yes
  # → changed: [web01] => (item=None)
```

### Использование meta для управления выполнением

```yaml
- name: "Flush handlers перед продолжением"
  ansible.builtin.meta: flush_handlers

- name: "Завершение play на текущем хосте"
  ansible.builtin.meta: end_host
  when: ansible_distribution == "Ubuntu"
```

### Проверка файла и его наличие

```yaml
- name: "Проверка наличия конфигурационного файла"
  ansible.builtin.stat:
    path: /etc/nginx/nginx.conf
  register: nginx_config

- name: "Создание конфигурационного файла если отсутствует"
  ansible.builtin.template:
    src: templates/nginx.conf.j2
    dest: /etc/nginx/nginx.conf
    owner: root
    group: root
    mode: '0644'
  when: not nginx_config.stat.exists
```

### Ожидание файла или порта

```yaml
- name: "Ожидание создания лог-файла"
  ansible.builtin.wait_for:
    path: /var/log/myapp/app.log
    timeout: 30
  # → changed: [web01] => (item=None)

- name: "Ожидание закрытия порта перед обновлением"
  ansible.builtin.wait_for:
    port: 8080
    state: stopped
    timeout: 30
  # → changed: [web01] => (item=None)
```

### Комплексное развертывание с обработкой ошибок

```yaml
- name: "Комплексное развертывание приложения"
  block:
    - name: "Проверка свободного места"
      ansible.builtin.assert:
        that:
          - ansible_mounts | selectattr('mount', 'eq', '/opt') | map(attribute='size_available') | first > 1073741824
        fail_msg: "Недостаточно места на диске /opt"

    - name: "Остановка сервиса"
      ansible.builtin.systemd:
        name: myapp
        state: stopped
      become: yes
      # → changed: [web01] => (item=None)

    - name: "Бэкап текущей версии"
      ansible.builtin.copy:
        src: "/opt/app/"
        dest: "/opt/backup/{{ ansible_date_time.iso8601_basic_short }}/"
        remote_src: yes
      become: yes

    - name: "Развертывание новой версии"
      ansible.builtin.unarchive:
        src: "app-{{ version }}.tar.gz"
        dest: /opt/app/
        remote_src: yes
      become: yes

    - name: "Запуск миграций"
      ansible.builtin.command:
        cmd: "/opt/app/migrate.sh"
      become: yes
      become_user: appuser

    - name: "Запуск сервиса"
      ansible.builtin.systemd:
        name: myapp
        state: started
        daemon_reload: yes
      become: yes
      # → changed: [web01] => (item=None)

  rescue:
    - name: "Откат к предыдущей версии"
      ansible.builtin.copy:
        src: "/opt/backup/latest/"
        dest: "/opt/app/"
        remote_src: yes
      become: yes

    - name: "Запуск сервиса после отката"
      ansible.builtin.systemd:
        name: myapp
        state: started
      become: yes
```

### Blue-green развертывание с cutover

Паттерн для бесшовного обновления сервиса с минимальным downtime.

```yaml
- name: "Развертывание зеленой версии"
  ansible.builtin.systemd:
    name: "myapp-green"
    state: started
    daemon_reload: yes
  become: yes
  # → changed: [web01] => (item=None)

- name: "Проверка работоспособности зеленой версии"
  ansible.builtin.uri:
    url: "http://localhost:8081/health"
    method: GET
    status_code: 200
  register: green_health
  ignore_errors: yes

- name: "Переключение symlink на зеленую версию"
  ansible.builtin.file:
    src: /opt/myapp-green
    dest: /opt/myapp-current
    state: link
  become: yes
  when: green_health is success

- name: "Остановка старой синей версии"
  ansible.builtin.systemd:
    name: "myapp-blue"
    state: stopped
  become: yes
```

### Массовое развертывание с контролем скорости

```yaml
- name: "Развертывание на кластер с batch-стратегией"
  ansible.builtin.systemd:
    name: myapp
    state: restarted
    daemon_reload: yes
  serial: "25%"
  throttle: 10
  become: yes
  # → changed: [web01] => (item=None)
  # → changed: [web02] => (item=None)
  # → Выполнение последовательно на 25% хостов, максимум 10 параллельно
```

### Работа в air-gapped средах

В air-gapped средах отсутствует доступ к внешним репозиториям. Все пакеты должны быть предварительно загружены и размещены в локальном репозитории.

```yaml
- name: "Настройка локального репозитория"
  ansible.builtin.copy:
    src: "local-repo/myapp-1.2.3.rpm"
    dest: "/opt/packages/"
    owner: root
    group: root
    mode: '0644'
  become: yes

- name: "Установка из локального репозитория"
  ansible.builtin.yum:
    name: "/opt/packages/myapp-1.2.3.rpm"
    state: present
  become: yes
  # → changed: [web01] => (item=None)

- name: "Запуск сервиса"
  ansible.builtin.systemd:
    name: myapp
    state: started
    enabled: yes
  become: yes
  # → changed: [web01] => (item=None)
```

### Compliance-аудит конфигурации

```yaml
- name: "Аудит: проверка состояния сервисов"
  ansible.builtin.service_facts:
  register: service_facts

- name: "Аудит: проверка параметров ядра"
  ansible.posix.sysctl:
    name: "{{ item }}"
  register: sysctl_audit
  loop:
    - net.ipv4.ip_forward
    - net.ipv4.conf.all.send_redirects
    - net.ipv4.conf.all.accept_redirects

- name: "Аудит: проверка лимитов"
  ansible.builtin.pam_limits:
    domain: "*"
    limit_type: "{{ item.limit_type }}"
    limit_item: "{{ item.limit_item }}"
    value: "{{ item.value }}"
  loop:
    - { limit_type: '-', limit_item: nofile, value: 65536 }
    - { limit_type: '-', limit_item: nproc, value: 65536 }
  register: limits_audit

- name: "Отчет по compliance"
  ansible.builtin.debug:
    msg: |
      Audit completed:
      Services: {{ service_facts.services | length }}
      Sysctl: {{ sysctl_audit.results | length }}
      Limits: {{ limits_audit.results | length }}
```

### Синхронизация конфигурации через delegate_to

Копирование unit-файлов и конфигураций с артефакторного сервера на целевые хосты.

```yaml
- name: "Копирование unit-файла с артефакторного сервера"
  ansible.builtin.copy:
    src: "/opt/artifacts/myapp.service"
    dest: "/etc/systemd/system/myapp.service"
    owner: root
    group: root
    mode: '0644'
  delegate_to: artifactory.internal
  become: yes
  # → changed: [web01] => (item=None)

- name: "Перезагрузка systemd"
  ansible.builtin.systemd:
    daemon_reload: yes
  become: yes
```

### Проверка и восстановление сервисов с retries

```yaml
- name: "Ожидание запуска сервиса с повторами"
  ansible.builtin.systemd:
    name: myapp
    state: started
  become: yes
  register: service_start
  until: service_start is success
  retries: 5
  delay: 10
  # → changed: [web01] => (item=None)
```

## Операции и команды

### Управление службами (systemd)

| Операция | Модуль | Параметры | Пример |
| :--- | :--- | :--- | :--- |
| **Запуск/остановка** | `ansible.builtin.systemd` | `name`, `state` | `state: started` / `state: stopped` |
| **Автозагрузка** | `ansible.builtin.systemd` | `name`, `enabled` | `enabled: true` / `enabled: false` |
| **Перезагрузка конфигурации** | `ansible.builtin.systemd` | `name`, `daemon_reload` | `daemon_reload: yes` |
| **Маскировка службы** | `ansible.builtin.systemd` | `name`, `masked` | `masked: yes` |
| **Кроссплатформенный запуск** | `ansible.builtin.service` | `name`, `state` | `state: started` |
| **Сбор фактов о службах** | `ansible.builtin.service_facts` | — | Регистрирует `ansible_facts.services` |
| **Блокировка учетной записи** | `ansible.builtin.service` | `name`, `enabled`, `state` | Комбинация `enabled: false` + `state: stopped` |

### Управление ядром и модулями

| Операция | Модуль | Параметры | Пример |
| :--- | :--- | :--- | :--- |
| **Изменение параметров ядра** | `ansible.posix.sysctl` | `name`, `value`, `state`, `sysctl_file` | `name: vm.swappiness`, `value: '10'` |
| **Немедленное применение** | `ansible.posix.sysctl` | `reload` | `reload: yes` |
| **Загрузка модуля ядра** | `ansible.builtin.modprobe` | `name`, `state` | `name: xfs`, `state: present` |
| **Выгрузка модуля ядра** | `ansible.builtin.modprobe` | `name`, `state` | `name: xfs`, `state: absent` |

### Управление пользователями и группами

| Операция | Модуль | Параметры | Пример |
| :--- | :--- | :--- | :--- |
| **Создание пользователя** | `ansible.builtin.user` | `name`, `state`, `system`, `shell`, `home` | `state: present`, `system: yes` |
| **Блокировка пользователя** | `ansible.builtin.user` | `name`, `password_lock` | `password_lock: yes` |
| **Создание группы** | `ansible.builtin.group` | `name`, `state`, `gid`, `system` | `state: present`, `system: yes` |
| **Настройка лимитов** | `ansible.builtin.pam_limits` | `domain`, `limit_type`, `limit_item`, `value` | `limit_type: '-'`, `limit_item: nofile`, `value: 524288` |

### Управление хранилищем

| Операция | Модуль | Параметры | Пример |
| :--- | :--- | :--- | :--- |
| **Монтирование** | `ansible.builtin.mount` | `path`, `src`, `fstype`, `state` | `state: mounted` |
| **Размонтирование** | `ansible.builtin.mount` | `path`, `state` | `state: unmounted` |
| **Добавление в fstab** | `ansible.builtin.mount` | `path`, `src`, `fstype`, `opts`, `state` | `state: present` |
| **Удаление из fstab** | `ansible.builtin.mount` | `path`, `state` | `state: absent` |

### Управление временем и локалями

| Операция | Модуль | Параметры | Пример |
| :--- | :--- | :--- | :--- |
| **Установка часового пояса** | `ansible.builtin.timezone` | `name` | `name: Europe/Moscow` |
| **Генерация локали** | `community.general.locale_gen` | `name`, `state` | `name: ru_RU.UTF-8`, `state: present` |
| **Установка имени хоста** | `ansible.builtin.hostname` | `name` | `name: myhost.example.com` |

### Управление планировщиком

| Операция | Модуль | Параметры | Пример |
| :--- | :--- | :--- | :--- |
| **Добавление задачи cron** | `ansible.builtin.cron` | `name`, `minute`, `hour`, `job`, `user` | `minute: "0"`, `hour: "3"` |
| **Отдельный файл cron** | `ansible.builtin.cron` | `cron_file` | `cron_file: "system-cleanup"` |
| **Удаление задачи** | `ansible.builtin.cron` | `name`, `state` | `state: absent` |

### Управление брандмауэром

| Операция | Модуль | Параметры | Пример |
| :--- | :--- | :--- | :--- |
| **Firewalld (RHEL)** | `ansible.posix.firewalld` | `port`, `state`, `permanent`, `immediate` | `port: 80/tcp`, `permanent: true` |
| **UFW (Debian)** | `community.general.ufw` | `rule`, `port`, `proto` | `rule: allow`, `port: '80'`, `proto: tcp` |

### Диагностика и проверка

| Операция | Модуль | Параметры | Пример |
| :--- | :--- | :--- | :--- |
| **Проверка доступности** | `ansible.builtin.ping` | — | `ansible all -m ansible.builtin.ping` |
| **Сбор фактов** | `ansible.builtin.setup` | `filter` | `filter: ansible_distribution*` |
| **Ожидание порта** | `ansible.builtin.wait_for` | `host`, `port`, `state`, `timeout` | `port: 5432`, `timeout: 60` |
| **Ожидание файла** | `ansible.builtin.wait_for` | `path`, `state`, `timeout` | `path: /var/log/myapp/app.log` |
| **HTTP-проверка** | `ansible.builtin.uri` | `url`, `method`, `status_code` | `status_code: 200` |
| **Проверка условия** | `ansible.builtin.assert` | `that`, `fail_msg`, `success_msg` | `that: ansible_python.version.major >= 3` |
| **Принудительный сбой** | `ansible.builtin.fail` | `msg` | `msg: "Критическая ошибка"` |
| **Вывод отладки** | `ansible.builtin.debug` | `var`, `msg` | `var: ansible_facts` |
| **Установка переменной** | `ansible.builtin.set_fact` | `key: value` | `package_manager: "{{ 'apt' if ansible_os_family == 'Debian' else 'yum' }}"` |
| **Управление выполнением** | `ansible.builtin.meta` | `flush_handlers`, `end_play`, `end_host` | `meta: flush_handlers` |
| **Загрузка файла** | `ansible.builtin.get_url` | `url`, `dest`, `mode`, `checksum` | `url: "https://example.com/app.tar.gz"` |

### Перезагрузка и обслуживание

| Операция | Модуль | Параметры | Пример |
| :--- | :--- | :--- | :--- |
| **Безопасная перезагрузка** | `ansible.builtin.reboot` | `reboot_timeout`, `test_command` | `reboot_timeout: 600`, `test_command: "whoami"` |
| **Долгая операция** | `ansible.builtin.command` + `async`/`poll` | `cmd`, `async`, `poll` | `async: 3600`, `poll: 0` |
| **Проверка статуса async** | `ansible.builtin.async_status` | `jid` | `jid: "{{ backup_job.ansible_job_id }}"` |

## Устранение неполадок

### Типичные ошибки и их решение

| Ошибка | Причина | Решение |
|--------|---------|---------|
| `Failed to start service` | Нет прав или нарушены зависимости | Используйте `become: yes`. Проверьте `systemctl status` и `journalctl -u` |
| `Unit not found` | Unit-файл не зарегистрирован в systemd | Выполните `daemon_reload: yes` после размещения unit-файла. Проверьте путь: `/etc/systemd/system/` |
| `Access denied` | Нет прав root | Используйте `become: yes` |
| `No such file or directory` | Отсутствует unit-файл или конфигурация | Создайте файл через `ansible.builtin.template` или `ansible.builtin.copy` |
| `Job is already running` | Попытка запуска уже запущенного сервиса без `force` | Используйте `force: yes` или проверяйте состояние перед запуском |
| `Connection refused` | Сервис не запущен | Запустите сервис или проверьте `ListenStream` в unit-файле |
| `Timeout expired` | Таймаут истек | Увеличьте `reboot_timeout` или проверьте сетевою доступность |
| `SELinux denied` | Конфликт контекста SELinux | Проверьте контексты через `ls -Z` и `sealert` или временно отключите для тестирования |
| `sysctl: permission denied` | Нет прав на запись в `/proc/sys/` | Используйте `become: yes` |
| `modprobe: ERROR could not insert` | Модуль не найден или конфликт версий ядра | Проверьте `uname -r` и доступность модуля: `/lib/modules/$(uname -r)/` |
| `fsck locked` | Файловая система требует проверки | Запустите `fsck` вручную или добавьте `fsck.mode=skip` в kernel parameters |
| `mount: wrong fs type` | Некорректный тип файловой системы | Проверьте `blkid` и `lsblk -f` |
| `cron: bad minute` | Некорректное значение поля minute | Используйте целые числа 0-59 или `*/5` |
| `firewalld: ZONE_ALREADY_SET` | Правило уже добавлено в зону | Используйте `state: enabled` идемпотентно |

### Диагностика systemd

```bash
# Проверка состояния unit-файла
systemctl status myapp
# → ● myapp.service - My Application
# →      Loaded: loaded (/etc/systemd/system/myapp.service; enabled; vendor preset: disabled)
# →      Active: active (running) since Mon 2026-09-22 10:00:00 UTC; 2h 30min ago

# Просмотр логов сервиса
journalctl -u myapp -f
# → Sep 22 10:00:00 web01 systemd[1]: Started My Application.
# → Sep 22 10:00:00 web01 myapp[1234]: Server started on port 8080

# Проверка зависимостей
systemctl list-dependencies myapp
# → myapp.service
# → └─network-online.target
# →   └─network.target

# Проверка cgroup-ресурсов
systemctl show myapp -p MemoryCurrent -p CPUUsageNSec
# → MemoryCurrent=536870912
# → CPUUsageNSec=1234567890

# Проверка автозагрузки
systemctl is-enabled myapp
# → enabled

# Список неудачных сервисов
systemctl --failed
# → UNIT               LOAD   ACTIVE SUB    DESCRIPTION
# → myapp-failed.service loaded failed failed My Application (crashed)
```

### Диагностика sysctl

```bash
# Проверка параметра
sysctl net.ipv4.ip_forward
# → net.ipv4.ip_forward = 1

# Применение всех параметров из /etc/sysctl.d/
sysctl --system
# → Applying /etc/sysctl.d/99-performance.conf ...
# → net.ipv4.ip_forward = 1
# → net.core.somaxconn = 1024

# Проверка всех параметров из файла
sysctl -p /etc/sysctl.d/99-performance.conf
```

### Диагностика cron

```bash
# Проверка crontab пользователя
crontab -l
# → 0 3 * * * /usr/bin/find /tmp -type f -atime +7 -delete

# Проверка системного cron
ls -la /etc/cron.d/
# → total 16
# → -rw-r--r-- 1 root root  82 Sep 22 10:00 system-cleanup

# Проверка логов cron
grep CRON /var/log/syslog | tail -20
# → Sep 22 03:00:01 web01 CRON[12345]: (root) CMD (/usr/bin/find /tmp -type f -atime +7 -delete)
```

## Рекомендации и оптимизация

### Оптимизация производительности

**Параметры для ускорения работы:**
- Используйте `ansible.builtin.service` вместо `ansible.builtin.systemd` для кроссплатформенности
- Кэшируйте факты с помощью `ansible.builtin.set_fact` для повторного использования
- Ограничивайте сбор фактов через `gather_facts: no` и используйте `ansible.builtin.setup` только при необходимости
- Используйте `ansible.builtin.wait_for` вместо циклов ожидания

**Оптимизация systemd:**
- Используйте `Type=oneshot` для одноразовых задач миграции
- Используйте `RestartSec=5` вместо `sleep` в скриптах инициализации
- Используйте `After=` и `Wants=` для явного управления зависимостями
- Используйте `Slice=` для группировки сервисов в cgroup-слайсы

### Обработка ошибок

**Типичные ошибки и их решение:**

| Ошибка | Причина | Решение |
|--------|---------|---------|
| `Failed to start service` | Нет прав или зависимость | Используйте `become: yes` и проверьте зависимости |
| `Unit not found` | Неправильное имя unit-файла | Проверьте имя через `systemctl list-units` |
| `Access denied` | Нет прав на изменение | Используйте `become: yes` |
| `No such file or directory` | Отсутствует конфигурационный файл | Создайте файл или используйте `ansible.builtin.template` |
| `Invalid parameter` | Неправильный синтаксис | Проверьте документацию модуля |
| `Connection refused` | Сервис не запущен | Запустите сервис перед выполнением задачи |
| `Timeout expired` | Таймаут истек | Увеличьте значение параметра `timeout` или проверьте сетевую доступность |
| `SELinux denied` | Конфликт контекста SELinux | Проверьте контексты через `ls -Z` и `sealert` или временно отключите для тестирования |
| `Job is already running` | Сервис уже запущен | Используйте `force: yes` или проверяйте состояние перед запуском |

### Рекомендации по безопасности

- **Привилегии**: Всегда используйте `become: yes` для операций, требующих root-доступа. Избегайте `become: false` для системных модулей, если нет явной необходимости.
- **Секреты**: При работе с паролями и ключами используйте `no_log: true` для предотвращения утечки в логи. Храните секреты в Ansible Vault или внешних системах (HashiCorp Vault).
- **Сетевые сервисы**: При открытии портов через брандмауэр используйте `permanent: true` + `immediate: true` (firewalld) для синхронизации текущего и сохраненного состояний.
- **SELinux**: После изменения контекстов или политик проверяйте логи через `ausearch` и `sealert`. Не отключайте SELinux в production без крайней необходимости.
- **Валидация**: Используйте параметр `validate` в модулях `template` и `copy` для проверки синтаксиса перед применением (например, `validate: 'nginx -t -c %s'`).

### Идемпотентность и повторное выполнение

- **State-based управление**: Всегда явно указывайте `state` (`present`, `absent`, `started`, `stopped`, `enabled`, `disabled`). Это гарантирует предсказуемое поведение при повторном запуске плейбука.
- **Условные задачи**: Используйте `when` для адаптации логики под дистрибутив или состояние системы. Пример: `when: ansible_os_family == "RedHat"`.
- **Регистрация результатов**: Используйте `register` для сохранения возвращаемых данных модулей и построения сложной логики в последующих задачах.
- **Обработчики (Handlers)**: Используйте `notify` + handlers для перезапуска служб только при изменении конфигурации, а не на каждом запуске.

### Управление конфигурацией

- **Юнит-файлы systemd**: Храните пользовательские unit-файлы в `/etc/systemd/system/`, а не в `/lib/systemd/system/`, чтобы избежать перезаписи при обновлении пакетов.
- **Sysctl-параметры**: Используйте отдельные файлы в `/etc/sysctl.d/*.conf` вместо редактирования `/etc/sysctl.conf` для модульности.
- **Лимиты ресурсов**: Настраивайте `pam_limits` через отдельные файлы в `/etc/security/limits.d/` для каждого сервиса, а не через общий `limits.conf`.
- **Cron-задания**: Используйте `/etc/cron.d/` для системных задач вместо редактирования crontab пользователя root. Это обеспечивает централизованное управление и автоматическую валидацию синтаксиса.

### Мониторинг и observability

- **Журналы systemd**: Используйте `journalctl -u <service> -f` для просмотра логов в реальном времени.
- **Статус сервисов**: Используйте `systemctl is-active` и `systemctl is-enabled` для проверки состояния.
- **Метрики**: Интегрируйте `node_exporter` textfile collector для экспорта статуса сервисов в Prometheus.
- **Алертинг**: Настраивайте алерты на `systemd --failed` и `journalctl -p err` для быстрого реагирования на сбои.

## Дополнительная информация

- **[systemd: управление службами](../../Linux/Core/systemd/service_management.md)** — архитектура systemd и команды диагностики.
- **[Настройка параметров ядра (sysctl)](../../Linux/Core/kernel/sysctl.md)** — справочник производительности Linux.
- **[Планировщик задач cron](../../Linux/SystemAdministration/cron.md)** — нюансы работы и синтаксис.
- **[Обработчики (Handlers)](../ansible_core_concepts.md#обработчики-и-уведомления)** — стандартный способ перезапуска служб в ответ на изменения конфигурации.
- **[SELinux: основы безопасности](../../Linux/Security/Mechanisms/SELinux.md)** — управление контекстами и режимами.
- **[Основные концепции Ansible](../ansible_core_concepts.md)** — архитектура и идемпотентность.
- **[Модули безопасности](./ansible_security_and_user_management_modules.md)** — управление пользователями и правами доступа.
- **[Модули управления файлами](./ansible_file_management_modules.md)** — копирование, шаблонизация и управление файлами.
- **[Модули управления пакетами](./ansible_package_management_modules.md)** — установка и управление программным обеспечением.
- **[Тестирование с Molecule](../ansible_testing_with_molecule.md)** — проверка кода автоматизации.
- **[Безопасность в Ansible](../ansible_security_best_practices.md)** — управление секретами и привилегиями.
