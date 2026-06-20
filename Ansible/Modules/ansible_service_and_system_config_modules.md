# Ansible: Модули управления службами и системной конфигурацией

## Определения

**Модули управления службами и системной конфигурацией** — это инструменты Ansible для управления жизненным циклом сервисов и настройки параметров операционной системы (время, имя хоста, параметры ядра, задачи по расписанию).

## Основные концепции

### Управление сервисами

* **`service`**: Универсальный модуль, работающий с различными системами инициализации (SysVinit, OpenRC, systemd). Рекомендуется для обеспечения переносимости.
* **`systemd`**: Специализированный модуль для систем с `systemd`. Позволяет выполнять `daemon-reload` и управлять сложными параметрами юнитов.

### Настройка параметров системы

* **`hostname`**: Управление именем хоста.
* **`timezone`**: Настройка часового пояса.
* **`ansible.posix.sysctl`**: Управление параметрами ядра Linux в реальном времени и в файлах конфигурации. Относится к коллекции `ansible.posix`, а не к `ansible.builtin` (см. ниже).
* **`cron`**: Управление заданиями в планировщике `crontab`.
* **`reboot`**: Безопасная перезагрузка хоста с ожиданием его возвращения в строй.

### Управление брандмауэром

* **`firewalld`**: Для систем на базе RHEL (CentOS, Fedora). Подробнее см. в **[Firewalld: динамический межсетевой экран](../../Linux/Networking/Settings/tools/firewalld.md)**.
* **`ufw`**: Для систем на базе Debian/Ubuntu.

## Практические сценарии

### Управление службами через `ansible.builtin.systemd`

Используйте `daemon_reload`, если вы изменили файл конфигурации юнита.

```yaml
- name: Перезагрузка конфигурации systemd и запуск сервиса
  ansible.builtin.systemd:
    name: nginx
    state: restarted
    enabled: yes
    daemon_reload: yes
```

### Настройка ядра через `ansible.posix.sysctl`

Модуль `sysctl` находится в коллекции `ansible.posix`, так как в Ansible 2.10+ модули разделили по коллекциям — в `ansible.builtin` входит только то, что поставляется с `ansible-core`. Коллекция `ansible.posix` обычно устанавливается вместе с пакетом `ansible`, но если её нет — требуется `ansible-galaxy collection install ansible.posix`.

```yaml
- name: Включение IP forwarding
  ansible.posix.sysctl:
    name: net.ipv4.ip_forward
    value: '1'
    state: present
    reload: yes # применить немедленно
```

### Планирование задач через `ansible.builtin.cron`

```yaml
- name: Ежедневный бэкап базы данных в 2 часа ночи
  ansible.builtin.cron:
    name: "db backup"
    minute: "0"
    hour: "2"
    job: "/usr/local/bin/backup.sh"
```

### Безопасная перезагрузка через `ansible.builtin.reboot`

```yaml
- name: Перезагрузка сервера после обновления ядра
  ansible.builtin.reboot:
    reboot_timeout: 600 # ждать до 10 минут
```

### Настройка брандмауэра (UFW)

```yaml
- name: Разрешить HTTP трафик в UFW
  community.general.ufw:
    rule: allow
    port: '80'
    proto: tcp
```

Подробнее о синтаксисе и возможностях UFW см. в **[UFW — Uncomplicated Firewall](../../Linux/Networking/Settings/tools/ufw.md)**.

### Установка часового пояса и имени хоста

```yaml
- name: Настройка базовых параметров системы
  block:
    - ansible.builtin.hostname:
        name: "{{ inventory_hostname }}"
    - ansible.builtin.timezone:
        name: Europe/Moscow
```

## Дополнительная информация

* [Официальная документация: модули управления сервисами](https://docs.ansible.com/ansible/latest/collections/ansible/builtin/systemd_module.html)
* [Обработчики (Handlers) и уведомления](../ansible_core_concepts.md#обработчики-handlers-и-уведомления-notify) — для перезапуска сервисов при изменении конфигов.
* [Кроссплатформенные плейбуки](../CrossPlatform/concepts.md) — выбор между `ufw` и `firewalld`.
