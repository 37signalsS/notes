# Ansible: Модули управления пользователями и безопасностью

## Определения

**Модули управления пользователями и безопасностью** — это инструменты Ansible для управления учетными записями, правами доступа и секретами на управляемых хостах. Они позволяют декларативно описывать состав групп, пользователей, их SSH-ключи и [права доступа (ACL)](../../Linux/Security/Concepts/File_Permissions/overview_definitions.md), гарантируя идентичность настроек безопасности на всем парке серверов.

Базовые концепции администрирования в Linux (UID, GID, типы учетных записей) описаны в разделе [Определения пользователей и групп](../../Linux/SystemAdministration/Users/users_definitions.md).

## Основные концепции

### Группы модулей

1. **Управление учетными записями и группами:**
    * **`ansible.builtin.user`**: Создание, модификация и удаление пользователей. Управление домашними директориями, оболочками (shell) и хешированными паролями.
    * **`ansible.builtin.group`**: Управление системными группами и их GID.
    * **`ansible.builtin.getent`**: Сбор информации из системных баз данных (passwd, group, shadow) в переменную `ansible_facts.getent_*`.

2. **Управление доступом и SSH:**
    * **`ansible.posix.authorized_key`**: Управление публичными ключами в `authorized_keys`.
    * **`ansible.builtin.known_hosts`**: Управление записями в `known_hosts` для предотвращения ошибок проверки ключей хоста.
    * **`ansible.posix.acl`**: Управление списками контроля доступа (Access Control Lists) для тонкой настройки прав на файлы и директории.

3. **Безопасность и секреты:**
    * **`ansible.builtin.password`**: Генерация случайных паролей или хешей на контрольном узле.
    * **`no_log`**: Параметр задачи (не модуль), скрывающий чувствительные данные из вывода и логов выполнения.

### Идемпотентность и безопасность

Все модули являются идемпотентными. При управлении пользователями крайне важно:
- Использовать хешированные пароли (SHA-512).
- Защищать секреты через [Ansible Vault](../Vault/basics.md).
- Делегировать права гранулярно через [sudoers](../../Linux/SystemAdministration/privilege_management.md#конфигурация-sudoers).

## Практические сценарии

### Управление пользователями (`ansible.builtin.user`)

```yaml
- name: Создание системного пользователя для приложения
  ansible.builtin.user:
    name: app_user
    comment: "Application Service Account"
    shell: /sbin/nologin
    system: yes
    groups: developers
    append: yes
    state: present
# → result: создан системный пользователь app_user без возможности входа
```

**Установка хешированного пароля:**

```yaml
- name: Установка пароля для пользователя
  ansible.builtin.user:
    name: admin_user
    password: "{{ user_password_hash }}" # Использование хеша из Vault
    update_password: on_create
  no_log: true
# → result: установлен пароль, данные скрыты в логах (no_log)
```

### Управление списками доступа (`ansible.posix.acl`)

Тонкая настройка прав доступа для конкретного пользователя без смены владельца файла.

```yaml
- name: Предоставление пользователю app_user прав на чтение логов
  ansible.posix.acl:
    path: /var/log/myapp.log
    entity: app_user
    etype: user
    permissions: r
    state: present
# → result: app_user получил право 'r' через механизм ACL
```

### Проверка наличия пользователя в системе (`ansible.builtin.getent`)

```yaml
- name: Получение информации о пользователе root
  ansible.builtin.getent:
    database: passwd
    key: root

- name: Вывод домашней директории root
  ansible.builtin.debug:
    msg: "Home: {{ ansible_facts.getent_passwd['root'][4] }}"
# → result: в ansible_facts доступны данные из /etc/passwd
```

### Делегирование прав через sudoers

Безопасное добавление прав sudo с валидацией синтаксиса.

```yaml
- name: Разрешение перезапуска Nginx без пароля
  ansible.builtin.template:
    src: sudoers_nginx.j2
    dest: /etc/sudoers.d/nginx
    mode: '0440'
    validate: '/usr/sbin/visudo -cf %s'
# → result: файл создан только если visudo подтвердил корректность синтаксиса
```

### Управление SSH-ключами (`ansible.posix.authorized_key`)

```yaml
- name: Добавление публичного ключа администратора
  ansible.posix.authorized_key:
    user: admin_user
    state: present
    key: "{{ lookup('file', 'keys/admin.pub') }}"
# → result: ключ добавлен в /home/admin_user/.ssh/authorized_keys
```

## Дополнительная информация

- [Определения пользователей и групп в Linux](../../Linux/SystemAdministration/Users/users_definitions.md) — базовые концепции ОС.
- [Управление привилегиями: sudo и sudoers](../../Linux/SystemAdministration/privilege_management.md) — делегирование прав.
- [Права доступа к файлам и ACL](../../Linux/Security/Concepts/File_Permissions/overview_definitions.md) — тонкая настройка доступа.
- [Ansible Vault: управление секретами](../Vault/basics.md) — защита паролей и ключей.
- [Рекомендации по безопасности Ansible](../ansible_security_best_practices.md) — общие принципы.
- [Обзор часто используемых модулей](ansible_modules_overview.md) — контекст применения.
- [Официальная документация: builtin модули](https://docs.ansible.com/ansible/latest/collections/ansible/builtin/index.html)
