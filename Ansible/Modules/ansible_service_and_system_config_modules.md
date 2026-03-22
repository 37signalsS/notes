# Ansible: Модули для управления службами и системной конфигурацией

## Определения

**Модули управления службами и системной конфигурацией** — это инструменты Ansible для управления системными сервисами (демонами), настройки времени, имени хоста и других системных параметров.

## Основные концепции

- **`systemd`**: Современный модуль для управления сервисами в системах с `systemd`. Поддерживает перезагрузку демонов (`daemon_reload`).
- **`service`**: Универсальный модуль для управления сервисами в различных системах инициализации (SysVinit, systemd).
- **`hostname`**: Управление именем хоста системы.
- **`timezone`**: Управление системным часовым поясом.

## Практические сценарии

### Модуль `ansible.builtin.systemd`

Более современный и предпочтительный модуль для систем, использующих `systemd`. Предоставляет дополнительные возможности, которых нет в `service`. Ключевое преимущество — опция `daemon_reload: yes`, которая выполняет команду `systemctl daemon-reload`. Это необходимо после создания или изменения `unit`-файлов сервисов, чтобы `systemd` узнал о них. Модуль `service` этого делать не умеет.

```yaml
- name: Reload systemd to apply new unit files
  ansible.builtin.systemd:
    daemon_reload: yes

- name: Restart service httpd, and sleep for 5 seconds
  ansible.builtin.systemd:
    name: httpd
    state: restarted
```

### Модуль `ansible.builtin.timezone`

Управляет системным часовым поясом.

```yaml
- name: Set timezone to Europe/Moscow
  ansible.builtin.timezone:
    name: Europe/Moscow
```

### Модуль `ansible.builtin.hostname`

Управляет именем хоста (hostname) системы.

```yaml
- name: Set hostname to 'webserver01'
  ansible.builtin.hostname:
    name: webserver01

- name: Set hostname based on inventory name
  ansible.builtin.hostname:
    name: "{{ inventory_hostname }}"
```

## Дополнительная информация

Официальная документация: [systemd](https://docs.ansible.com/ansible/latest/collections/ansible/builtin/systemd_module.html), [hostname](https://docs.ansible.com/ansible/latest/collections/ansible/builtin/hostname_module.html), [timezone](https://docs.ansible.com/ansible/latest/collections/ansible/builtin/timezone_module.html). Перезапуск сервисов через обработчики — в [Обработчики](../../PlaybookStructure/basics.md).
