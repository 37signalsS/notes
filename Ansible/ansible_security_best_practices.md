# Ansible: Рекомендации по безопасности

## Определения

**Ключевой принцип безопасности Ansible** — не ограничивать возможности инструмента, а строго контролировать доступ к нему. Это означает предоставление Ansible полных прав `sudo` на Managed Nodes через выделенного пользователя и смещение фокуса безопасности на защиту **Control Node**.

## Основные концепции

### Необходимость полных прав `sudo`

Ansible для выполнения большинства задач (установка пакетов, управление службами, изменение конфигураций) требует прав суперпользователя. Попытки ограничить `sudo` для пользователя Ansible набором разрешенных команд — **крайне плохая практика**, которая приводит к двум основным проблемам:

1. **Хрупкость автоматизации:** Ansible использует множество системных команд и временных скриптов. Поддержка "белого списка" команд практически невозможна.
2. **Сложность отладки:** При любом изменении в Playbook или версии Ansible может потребоваться новая команда. Если она не разрешена, Playbook упадет с неинформативной ошибкой, поиск причины которой отнимает много времени.

Поэтому для большинства задач в Playbook следует использовать директиву `become: true`.

### Выделенный пользователь для Ansible

На всех Managed Nodes рекомендуется создать отдельного пользователя (например, `ansible-runner`) с полными, беспарольными правами `sudo`.

**Преимущества:**

* **Аудит и прозрачность:** В системных логах (`/var/log/auth.log`, [`journalctl`](../Linux/Diagnostics/journalctl.md)) четко видно, какие действия выполнены именно Ansible.
* **Разделение ответственности:** Это помогает отделить проблемы, внесенные автоматизацией, от ручных изменений.

## Практические сценарии

### Настройка выделенного пользователя через Playbook

Вместо использования отдельных ad-hoc команд, весь процесс настройки выделенного пользователя (`ansible_user`) следует инкапсулировать в идемпотентный Playbook. Это обеспечивает воспроизводимость и соответствует декларативному подходу Ansible.

**Пример Playbook `bootstrap_user.yml`:**

```yaml
---
- name: Bootstrap dedicated Ansible user
  hosts: all
  become: true # Все задачи требуют повышения привилегий
  vars:
    ansible_user_name: ansible_user
    # Имя sudo-группы в зависимости от семейства ОС
    sudo_group: "{{ 'wheel' if ansible_facts['os_family'] == 'RedHat' else 'sudo' }}"

  tasks:
    - name: Ensure sudo group exists
      ansible.builtin.group:
        name: "{{ sudo_group }}"
        state: present

    - name: Create the ansible user
      ansible.builtin.user:
        name: "{{ ansible_user_name }}"
        shell: /bin/bash
        state: present
        groups: "{{ sudo_group }}"
        append: true

    - name: Set up authorized keys for the ansible user
      ansible.posix.authorized_key:
        user: "{{ ansible_user_name }}"
        state: present
        key: "{{ lookup('file', '~/.ssh/id_rsa.pub') }}"

    - name: Set up passwordless sudo for the ansible user
      ansible.builtin.copy:
        dest: "/etc/sudoers.d/90-{{ ansible_user_name }}"
        content: "{{ ansible_user_name }} ALL=(ALL) NOPASSWD: ALL"
        mode: '0440'
        validate: /usr/sbin/visudo -csf %s
```

Запуск Playbook:

```bash
ansible-playbook bootstrap_user.yml -u root
# → PLAY [Bootstrap dedicated Ansible user] ... ok=4 changed=4 unreachable=0 failed=0
```

> После выполнения можно переключиться на использование `ansible_user`, как описано в [документации по установке](ansible_setup_and_config.md).

## Дополнительная информация

### Смотрите также

- [Основы Ansible Vault](Vault/basics.md)
- [Лучшие практики Ansible Vault](Vault/best_practices.md)
- [Настройка и конфигурация Ansible](ansible_setup_and_config.md)
- [Отладка миграции на выделенного пользователя](examples/user_migration_debugging.md)
- [Semaphore — веб-интерфейс для Ansible](ansible_semaphore.md)
