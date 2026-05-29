# Ansible: Модули управления пользователями и безопасностью

## Определения

**Модули управления пользователями и безопасностью** — это инструменты Ansible для управления учетными записями, правами доступа и секретами на управляемых хостах. Они позволяют декларативно описывать состав групп, пользователей и их SSH-ключи, гарантируя идентичность настроек безопасности на всем парке серверов.

## Основные концепции

### Группы модулей

1. **Управление учетными записями:**
    * `user`: Создание, модификация и удаление пользователей, управление их домашними директориями, оболочками (shell) и паролями.
    * `group`: Создание и удаление системных групп, управление GID.
2. **Управление SSH-доступом:**
    * `authorized_key`: Добавление или удаление публичных ключей в файл `authorized_keys` пользователя.
    * `known_hosts`: Управление записями в файле `known_hosts` для предотвращения ошибок проверки ключей хоста при SSH-соединениях.
3. **Безопасность и секреты:**
    * `password`: Генерация случайных паролей или хешей для использования в задачах.
    * `no_log`: Параметр задачи (а не модуль), скрывающий чувствительные данные (пароли, токены) из логов выполнения.

### Идемпотентность и безопасность

Все перечисленные модули являются идемпотентными. При управлении паролями крайне важно использовать хешированные значения, так как Ansible не должен передавать или хранить пароли в открытом виде. Рекомендуется использовать [Ansible Vault](../Vault/basics.md) для защиты всех секретов.

## Практические сценарии

### Управление пользователями (`ansible.builtin.user`)

Модуль позволяет гибко настраивать параметры учетной записи.

```yaml
- name: Создание пользователя Peter Parker
  ansible.builtin.user:
    name: peter_parker
    comment: "Peter Parker, Web Developer"
    shell: /bin/bash
    groups: sudo,docker # Добавление в группы
    append: yes # Важно: не удалять из групп, не указанных в списке
    state: present
```

**Установка хешированного пароля:**

```yaml
- name: Установка пароля для пользователя
  ansible.builtin.user:
    name: peter_parker
    password: "$6$rounds=656000$..." # Хеш SHA-512 (используйте Vault)
    update_password: on_create # Обновлять только при создании (или always)
  no_log: true
```

### Управление группами (`ansible.builtin.group`)

```yaml
- name: Создание группы разработчиков с конкретным GID
  ansible.builtin.group:
    name: developers
    gid: 2000
    state: present
```

### Управление SSH-ключами (`ansible.posix.authorized_key`)

Позволяет безопасно распространять публичные ключи для доступа по SSH.

```yaml
- name: Добавление публичного ключа администратора
  ansible.posix.authorized_key:
    user: ansible_user
    state: present
    key: "{{ lookup('file', '/path/to/id_rsa.pub') }}"
```

### Управление доверенными хостами (`ansible.builtin.known_hosts`)

Помогает избежать интерактивных запросов "Are you sure you want to continue connecting?" при автоматизации SSH-соединений между хостами.

```yaml
- name: Добавление GitHub в known_hosts
  ansible.builtin.known_hosts:
    name: github.com
    key: "github.com ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl"
    state: present
```

### Генерация паролей (`ansible.builtin.password`)

Используется для создания уникальных секретов "на лету" и их сохранения на контрольном узле.

```yaml
- name: Генерация случайного пароля для базы данных
  ansible.builtin.password:
    length: 24
    chars: ascii_letters,digits
    path: "/tmp/db_pass_{{ inventory_hostname }}"
  register: generated_pass

- name: Использование сгенерированного пароля
  ansible.builtin.debug:
    msg: "Сгенерирован пароль: {{ generated_pass.password }}"
  no_log: true
```

## Дополнительная информация

* [Официальная документация по модулю user](https://docs.ansible.com/ansible/latest/collections/ansible/builtin/user_module.html)
* [Рекомендации по безопасности Ansible](../ansible_security_best_practices.md)
* [Работа с Ansible Vault](../Vault/basics.md)
* [Обзор часто используемых модулей](ansible_modules_overview.md)
