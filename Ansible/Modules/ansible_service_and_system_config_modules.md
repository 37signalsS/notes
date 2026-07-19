# Ansible: Модули управления службами и системой

## Определения

**Модули управления службами и системной конфигурацией** — это группа инструментов Ansible для управления жизненным циклом сервисов, настройкой параметров ядра, планированием задач и базовыми параметрами операционной системы (ОС). Эти модули абстрагируют различия между системами инициализации (systemd, SysVinit) и предоставляют унифицированный интерфейс для администрирования.

## Основные концепции

### Управление сервисами
- **`ansible.builtin.service`**: Универсальный модуль для управления службами. Автоматически определяет систему инициализации. Рекомендуется для обеспечения кроссплатформенности.
- **`ansible.builtin.systemd`**: Специализированный модуль для систем с [systemd](../../Linux/Core/systemd/service_management.md). Поддерживает специфичные функции: `daemon_reload`, управление пользовательскими юнитами (`scope: user`) и маскировку.
- **`ansible.builtin.service_facts`**: Сбор состояния всех сервисов в переменную `ansible_facts.services`. Позволяет строить логику на основе состояния процессов.

### Настройка системных ресурсов и ядра
- **`ansible.posix.sysctl`**: Управление параметрами ядра Linux (через `/proc/sys`). Позволяет вносить изменения «на лету» и сохранять их в `sysctl.conf`. См. также: [sysctl в Linux](../../Linux/Core/kernel/sysctl.md).
- **`ansible.builtin.modprobe`**: Загрузка и выгрузка модулей ядра.
- **`ansible.builtin.pam_limits`**: Управление лимитами ресурсов (через `/etc/security/limits.conf`).
- **`ansible.builtin.mount`**: Управление точками монтирования в `/etc/fstab` и активными монтированиями. Подробнее: [Монтирование в Linux](../../Linux/FileSystems/mounting/index.md).
- **`ansible.posix.selinux`**: Управление состоянием и политиками SELinux (Security-Enhanced Linux).

### Базовая конфигурация ОС
- **`ansible.builtin.hostname`**: Установка имени хоста.
- **`ansible.builtin.timezone`**: Настройка часового пояса системы.
- **`ansible.builtin.cron`**: Управление заданиями в планировщике [crontab](../../Linux/SystemAdministration/cron.md).
- **`ansible.builtin.reboot`**: Безопасная перезагрузка хоста с ожиданием доступности.
- **`ansible.builtin.locale_gen` / `debconf`**: Настройка локалей и параметров конфигурации (преимущественно для Debian-based систем).

### Сетевая безопасность и брандмауэры
- **`community.general.ufw`**: Управление [UFW](../../Linux/Networking/Settings/tools/ufw.md) (Uncomplicated Firewall) в Ubuntu/Debian.
- **`ansible.posix.firewalld`**: Управление [Firewalld](../../Linux/Networking/Settings/tools/firewalld.md) в RHEL/CentOS.
- **`ansible.builtin.iptables`**: Прямое управление правилами iptables.

## Практические сценарии

### Управление службой с перезагрузкой конфигурации (`systemd`)
Использование `daemon_reload` необходимо после ручного изменения unit-файлов на диске.

```yaml
- name: Обновление и перезапуск кастомного сервиса
  ansible.builtin.systemd:
    name: my_app.service
    state: restarted
    enabled: yes
    daemon_reload: yes
# → result: сервис my_app перезапущен, конфигурация systemd обновлена
```

### Проверка состояния сервиса перед действием
Использование фактов о сервисах для предотвращения ошибок.

```yaml
- name: Сбор фактов о сервисах
  ansible.builtin.service_facts:

- name: Выполнение задачи, только если Nginx запущен
  ansible.builtin.command: /usr/local/bin/check_nginx_config
  when: ansible_facts.services['nginx.service'].state == 'running'
  changed_when: false
# → result: команда выполняется только при статусе 'running' в ansible_facts
```

### Настройка параметров ядра (`sysctl`)
Пример включения пересылки пакетов для настройки NAT (Network Address Translation).

```yaml
- name: Включение IP Forwarding
  ansible.posix.sysctl:
    name: net.ipv4.ip_forward
    value: '1'
    state: present
    reload: yes
# → result: переменная net.ipv4.ip_forward=1 установлена в памяти и в /etc/sysctl.conf
```

### Управление состоянием SELinux
Переключение режима работы SELinux без перезагрузки (если поддерживается).

```yaml
- name: Перевод SELinux в режим Permissive
  ansible.posix.selinux:
    policy: targeted
    state: permissive
# → result: SELinux переведен в режим permissive, изменения внесены в /etc/selinux/config
```

### Настройка лимитов ресурсов (`pam_limits`)
Увеличение максимального количества открытых файлов для высоконагруженных приложений.

```yaml
- name: Установка лимитов для пользователя nginx
  ansible.builtin.pam_limits:
    domain: nginx
    limit_type: soft
    limit_item: nofile
    value: 65536
# → result: лимит nofile установлен в /etc/security/limits.conf
```

### Монтирование дисков (`mount`)
Автоматическое добавление записи в fstab и монтирование.

```yaml
- name: Монтирование диска с данными
  ansible.builtin.mount:
    path: /data
    src: UUID=b3...
    fstype: ext4
    opts: defaults,noatime
    state: mounted
# → result: диск смонтирован в /data, запись добавлена в /etc/fstab
```

### Планирование периодических задач (`cron`)
```yaml
- name: Ежедневная очистка временных файлов
  ansible.builtin.cron:
    name: "Cleanup tmp"
    minute: "0"
    hour: "3"
    job: "/usr/bin/find /tmp -type f -atime +7 -delete"
# → result: задача добавлена в crontab пользователя root
```
## Дополнительная информация

- [systemd: управление службами](../../Linux/Core/systemd/service_management.md) — основной раздел по системе инициализации.
- [cron: планировщик задач](../../Linux/SystemAdministration/cron.md) — подробнее о синтаксисе crontab.
- [sysctl: параметры ядра](../../Linux/Core/kernel/sysctl.md) — документация по тюнингу ядра Linux.
- [Монтирование в Linux](../../Linux/FileSystems/mounting/index.md) — детальный обзор fstab и монтирования.
- [Firewalld: динамический межсетевой экран](../../Linux/Networking/Settings/tools/firewalld.md)
- [UFW: Uncomplicated Firewall](../../Linux/Networking/Settings/tools/ufw.md)
- [Обработчики (Handlers)](../ansible_core_concepts.md#обработчики-и-уведомления) — стандартный способ перезапуска служб в Ansible.
- [Официальная документация: builtin модули](https://docs.ansible.com/ansible/latest/collections/ansible/builtin/index.html)

