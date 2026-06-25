# Модули управления службами и системной конфигурацией Ansible

## Определения

**Модули управления службами и системной конфигурацией** — это инструменты Ansible для управления жизненным циклом сервисов и настройки параметров операционной системы (время, имя хоста, параметры ядра, задачи по расписанию).

## Основные концепции

### Управление сервисами

* **`service`**: Универсальный модуль, работающий с различными системами инициализации (SysVinit (System V Initialization), OpenRC, systemd). Рекомендуется для обеспечения переносимости.
* **`systemd`**: Специализированный модуль для систем с `systemd`. Позволяет выполнять `daemon-reload` и управлять сложными параметрами юнитов.
* **`service_facts`**: Сбор информации о состоянии всех сервисов на хосте. Возвращает `ansible_facts.services` — словарь, где ключ — имя юнита, значение — состояние (`state`, `status`). Используется для проверок и валидации перед/после изменений.

### Настройка параметров системы

* **`hostname`**: Управление именем хоста.
* **`timezone`**: Настройка часового пояса.
* **`ansible.posix.sysctl`**: Управление параметрами ядра Linux в реальном времени и в файлах конфигурации. Относится к коллекции `ansible.posix` (Portable Operating System Interface), а не к `ansible.builtin` (см. ниже).
* **`cron`**: Управление заданиями в планировщике `crontab`.
* **`reboot`**: Безопасная перезагрузка хоста с ожиданием его возвращения в строй.

### Управление брандмауэром

* **`firewalld`**: Для систем на базе RHEL (Red Hat Enterprise Linux). Подробнее см. в **[Firewalld: динамический межсетевой экран](../../Linux/Networking/Settings/tools/firewalld.md)**.
* **`ufw`**: Для систем на базе Debian/Ubuntu. Расшифровывается как UFW (Uncomplicated Firewall).

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

### Сбор информации о сервисах

```yaml
- name: Получить список всех сервисов
  ansible.builtin.service_facts:

- name: Проверить, что Nginx запущен
  ansible.builtin.debug:
    msg: "Nginx {{ 'запущен' if 'nginx.service' in ansible_facts.services and ansible_facts.services['nginx.service'].state == 'running' else 'остановлен' }}"
```

Подробнее о проверках с `service_facts` и `assert` — в [сценарии проверки состояний](../PlaybookStructure/advanced.md#сценарий-7-проверка-состояний).

### Настройка ядра через `ansible.posix.sysctl`

Модуль `sysctl` находится в коллекции `ansible.posix`, так как в Ansible 2.10+ модули разделили по коллекциям — в `ansible.builtin` входит только то, что поставляется с `ansible-core`. Коллекция `ansible.posix` обычно устанавливается вместе с пакетом `ansible`, но если её нет — требуется `ansible-galaxy collection install ansible.posix`.

```yaml
- name: Включение IP (Internet Protocol) forwarding
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
- name: Разрешить HTTP (HyperText Transfer Protocol) трафик в UFW
  community.general.ufw:
    rule: allow
    port: '80'
    proto: tcp # TCP (Transmission Control Protocol)
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

* [Официальная документация: модуль systemd](https://docs.ansible.com/ansible/latest/collections/ansible/builtin/systemd_module.html)
* [Обработчики (Handlers) и уведомления (Notify)](../ansible_core_concepts.md#обработчики-handlers-и-уведомления-notify) — для перезапуска сервисов при изменении конфигурационных файлов.
* [Кроссплатформенные плейбуки](../CrossPlatform/concepts.md) — выбор между `ufw` и `firewalld`.
