# Ansible: Модули управления пользователями и безопасностью

## Определения

**Модули управления пользователями и безопасностью** — это группа специализированных инструментов Ansible (`ansible.builtin` и `ansible.posix`), предназначенных для декларативного управления учетными записями, правами доступа и механизмами аутентификации на управляемых хостах.

Использование этих модулей гарантирует идентичность настроек безопасности на всем парке серверов, исключая человеческий фактор при настройке привилегий и SSH-доступа.

**FQCN (Fully Qualified Collection Name)** — полное имя модуля (например, `ansible.builtin.user`), использование которого обязательно для предотвращения конфликтов и обеспечения предсказуемости выполнения.

## Основные концепции

### Группы модулей по назначению

1.  **Управление учетными записями и группами:**
    *   `ansible.builtin.user`: Создание, модификация и удаление пользователей. Управление домашними директориями, оболочками (shell), хешированными паролями и автоматической генерацией SSH-ключей.
    *   `ansible.builtin.group`: Управление системными группами и их GID.
    *   `ansible.builtin.getent`: Сбор информации из системных баз данных (passwd, group, shadow) в переменную `ansible_facts.getent_*`.
2.  **Управление доступом и SSH:**
    *   `ansible.posix.authorized_key`: Управление публичными ключами в файлах `authorized_keys`.
    *   `ansible.builtin.known_hosts`: Добавление или удаление ключей хостов в `known_hosts` для предотвращения MITM-атак и интерактивных запросов подтверждения.
    *   `ansible.posix.acl`: Тонкая настройка списков контроля доступа (Access Control Lists) для объектов файловой системы. Требует поддержки ACL ядром и опций монтирования ФС.
3.  **Безопасность и секреты:**
    *   `ansible.builtin.password`: Генерация случайных паролей на контрольном узле.
    *   `no_log: true`: Параметр задачи (не модуль), критически важный для предотвращения утечки секретов в логи и вывод консоли.

### Критически важные детали реализации

#### Модуль `ansible.builtin.user` и пароли
*   **Хеширование**: Параметр `password` ожидает **хеш**, а не открытый текст. Если передать строку `12345`, она будет записана в `/etc/shadow` как есть, и пользователь не сможет войти.
*   **Рекомендация**: Используйте фильтр `password_hash` с солью (salt): `password: "{{ 'mysecret' | password_hash('sha512', 'mysalt') }}"`.
*   **`update_password`**:
    *   `on_create`: Пароль устанавливается только при создании. Если пароль на хосте изменен вручную, Ansible его не «вернет» обратно.
    *   `always`: Сверяет текущий хеш и обновляет его при расхождении (стандарт для комплаенса).
*   **SSH Key Gen**: Параметры `ssh_key_generate: yes` и `ssh_key_file` позволяют автоматически создать пару ключей для пользователя прямо при его создании.

#### Модуль `ansible.posix.authorized_key`
*   **`exclusive: yes`**: Критически важный параметр для безопасности. Удаляет из `authorized_keys` все ключи, которые не указаны в задаче. Позволяет гарантировать, что доступ имеют только авторизованные в Ansible ключи.
*   **`path`**: Позволяет указать нестандартное местоположение файла ключей (например, если используется `AuthorizedKeysFile /etc/ssh/authorized_keys/%u` в `sshd_config`).

#### Модуль `ansible.builtin.known_hosts`
*   **`key`**: Ожидает строку в формате, выдаваемом `ssh-keyscan`.
*   **`hash_host: yes`**: Скрывает IP/имя хоста в файле `known_hosts`, что является лучшей практикой безопасности.

## Практические сценарии

### Создание системного пользователя с SSH-ключом
Использование `system: yes` создает техническую учетную запись с UID в системном диапазоне.

```yaml
- name: "Создание пользователя для бэкапов"
  ansible.builtin.user:
    name: backup_mgr
    shell: /bin/bash
    system: yes
    create_home: yes
    ssh_key_generate: yes
    ssh_key_bits: 4096
    ssh_key_type: rsa
    ssh_key_comment: "ansible-managed-backup-key"
```

### Строгое управление SSH-доступом (`exclusive`)
Гарантия того, что только текущие ключи администраторов имеют доступ.

```yaml
- name: "Синхронизация ключей администраторов"
  ansible.posix.authorized_key:
    user: root
    key: "{{ lookup('file', 'keys/admin_group.pub') }}"
    exclusive: yes
    state: present
```

### Тонкая настройка прав через ACL
Предоставление доступа конкретному пользователю к директории без изменения `owner/group`.

```yaml
- name: "Разрешение чтения логов для пользователя мониторинга"
  ansible.posix.acl:
    path: /var/log/nginx
    entity: prometheus
    etype: user
    permissions: rx
    state: present
    recursive: yes
```

### Проверка безопасности через getent
Использование данных из `/etc/shadow` для аудита (требует `become: true`).

```yaml
- name: "Сбор информации о пользователях"
  ansible.builtin.getent:
    database: shadow
    key: "{{ item }}"
  loop: "{{ users_to_audit }}"
  register: shadow_info

- name: "Проверка даты истечения пароля"
  ansible.builtin.debug:
    msg: "Пароль пользователя {{ item.item }} истекает через {{ item.ansible_facts.getent_shadow[item.item][6] }} дней"
  loop: "{{ shadow_info.results }}"
```

### Безопасная инициализация с no_log
Скрытие секретов при установке паролей.

```yaml
- name: "Установка пароля администратора"
  ansible.builtin.user:
    name: admin
    password: "{{ admin_password | password_hash('sha512') }}"
    update_password: always
  no_log: true
```

## Дополнительная информация

- **[Ansible Vault: управление секретами](../Vault/basics.md)** — хранение хешей и ключей.
- **[Рекомендации по безопасности Ansible](../ansible_security_best_practices.md)** — архитектурные паттерны защиты.
- **[Управление привилегиями: sudo и sudoers](../../Linux/SystemAdministration/privilege_management.md)** — делегирование прав.
- **[Определения пользователей и групп в Linux](../../Linux/SystemAdministration/Users/users_definitions.md)** — теоретическая база.
