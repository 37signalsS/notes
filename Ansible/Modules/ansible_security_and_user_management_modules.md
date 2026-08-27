# Ansible: Модули управления пользователями и безопасностью

## Определения

**Модули управления пользователями и безопасностью** — это группа специализированных декларативных инструментов Ansible (преимущественно `ansible.builtin` и `ansible.posix`), предназначенных для управления жизненным циклом учетных записей, правами доступа и механизмами аутентификации на управляемых хостах.

Использование этих модулей гарантирует идентичность настроек безопасности на всем парке серверов, исключая человеческий фактор при настройке привилегий и SSH-доступа. Это ключевой элемент реализации концепции «Безопасность как код» (Security as Code).

**FQCN (Fully Qualified Collection Name)** — полное имя модуля (например, `ansible.builtin.user`). Использование FQCN является обязательным стандартом для предотвращения конфликтов имен и обеспечения предсказуемости выполнения во всех современных версиях Ansible.

## Основные концепции

### Группы модулей по назначению

1.  **Управление учетными записями и группами:**
    *   `ansible.builtin.user`: Создание, модификация, блокировка и удаление пользователей. Управление домашними директориями, оболочками (shell), хешированными паролями, сроками их действия и автоматической генерацией SSH-ключей.
    *   `ansible.builtin.group`: Управление системными группами и их GID.
    *   `ansible.builtin.getent`: Сбор информации из системных баз данных (passwd, group, shadow) в переменную `ansible_facts.getent_*` для последующего аудита.
2.  **Управление доступом и SSH:**
    *   `ansible.posix.authorized_key`: Управление публичными ключами в файлах `authorized_keys`. Поддерживает очистку неавторизованных ключей.
    *   `ansible.builtin.known_hosts`: Управление ключами хостов для предотвращения MITM-атак и интерактивных запросов подтверждения.
    *   `ansible.posix.acl`: Тонкая настройка списков контроля доступа (ACL) для объектов файловой системы.
3.  **Безопасность репозиториев и секреты:**
    *   `ansible.builtin.rpm_key` / `ansible.builtin.apt_key`: Управление GPG-ключами для проверки подлинности устанавливаемых пакетов ПО.
    *   `ansible.builtin.password`: Генерация случайных паролей на контрольном узле.
    *   `no_log: true`: Параметр задачи (не модуль), критически важный для предотвращения утечки секретов в логи и вывод консоли.
4.  **Управление файлами и конфигурацией:**
    *   `ansible.builtin.copy`: Копирование файлов на управляемые хосты.
    *   `ansible.builtin.template`: Генерация файлов из шаблонов Jinja2.
    *   `ansible.builtin.lineinfile`: Гарантированное внесение изменений в отдельные строки файлов.
    *   `ansible.builtin.blockinfile`: Вставка/обновление блоков текста в файлах.
    *   `ansible.builtin.file`: Управление свойствами файлов и директорий (owner, group, mode).
    *   `ansible.builtin.stat`: Сбор информации о файлах и директориях.

### Возвращаемые данные (Return Values)

Модули управления безопасностью возвращают стандартный набор данных:

| Параметр | Тип | Описание |
|----------|-----|----------|
| `name` | string | Имя управляемого ресурса |
| `state` | string | Текущее состояние ресурса |
| `changed` | boolean | Были ли произведены изменения |
| `uid` | integer | UID созданного/измененного пользователя |
| `gid` | integer | GID группы пользователя |
| `groups` | list | Список групп пользователя |
| `ssh_public_keys` | list | Список публичных SSH-ключей |

### Критически важные детали реализации

#### Модуль `ansible.builtin.user` и пароли
*   **Хеширование**: Параметр `password` ожидает **хеш**, а не открытый текст. Передача открытого текста сделает вход невозможным.
*   **Рекомендация**: Используйте фильтр `password_hash` с алгоритмом `sha512` и солью: `password: "{{ 'mysecret' | password_hash('sha512') }}"`.
*   **`update_password`**:
    *   `on_create`: Пароль устанавливается только при создании.
    *   `always`: Сверяет текущий хеш и обновляет его при расхождении (стандарт для комплаенса).
*   **Блокировка и срок действия**:
    *   `password_lock: yes`: Позволяет заблокировать учетную запись без её удаления.
    *   `expires`: Установка даты истечения срока действия учетной записи (в формате Unix epoch).
*   **SSH Key Gen**: Параметры `ssh_key_generate: yes` и `ssh_key_file` позволяют автоматически создать пару ключей для пользователя прямо при его создании.

#### Модуль `ansible.posix.authorized_key`
*   **`exclusive: yes`**: Критически важный параметр для безопасности. Удаляет из `authorized_keys` все ключи, которые не указаны в задаче. Позволяет гарантировать, что доступ имеют только авторизованные в Ansible ключи.
*   **`path`**: Позволяет указать нестандартное местоположение файла ключей (например, если используется централизованное хранение ключей в `/etc/ssh/`).

#### Модуль `ansible.builtin.known_hosts`
*   **`key`**: Ожидает строку в формате, выдаваемом `ssh-keyscan`.
*   **`hash_host: yes`**: Скрывает IP/имя хоста в файле `known_hosts` через хеширование, что затрудняет разведку для злоумышленника.

#### Управление sudoers через шаблоны
Хотя прямого модуля для `sudoers` в `builtin` нет, правильный подход — использование модуля `template` с обязательной валидацией:
`validate: '/usr/sbin/visudo -cf %s'`. Это предотвращает ошибки, которые могут заблокировать доступ администраторам.

### Оптимизация производительности

**Параметры для ускорения работы:**
- Используйте `ansible.builtin.user` вместо команд `useradd`/`usermod` для декларативного управления
- Кэшируйте факты с помощью `ansible.builtin.set_fact` для повторного использования
- Ограничивайте сбор фактов через `gather_facts: no` и `ansible.builtin.setup` only when needed
- Используйте `ansible.builtin.assert` для проверки условий перед выполнением

### Обработка ошибок

**Типичные ошибки и их решение:**

| Ошибка | Причина | Решение |
|--------|---------|---------|
| `User already exists` | Пользователь уже создан | Используйте `state: present` для идемпотентности |
| `Group not found` | Группа не существует | Создайте группу перед добавлением пользователя |
| `Permission denied` | Нет прав на изменение | Используйте `become: yes` |
| `No such file or directory` | Отсутствует домашняя директория | Создайте директорию или используйте `create_home: yes` |
| `Invalid password hash` | Неправильный формат хеша | Используйте `password_hash('sha512')` |
| `SSH key not found` | Отсутствует файл ключа | Проверьте путь к файлу ключа |
| `Invalid shell` | Указана несуществующая оболочка | Проверьте доступные оболочки в `/etc/shells` |
| `Account locked` | Попытка входа заблокированного пользователя | Используйте `password_lock: no` для разблокировки |

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

### Блокировка доступа уволенных сотрудников
Безопасное прекращение доступа без немедленного удаления данных.

```yaml
- name: "Блокировка учетной записи"
  ansible.builtin.user:
    name: ex_employee
    password_lock: yes
    shell: /sbin/nologin
    state: present

- name: "Отзыв SSH-доступа"
  ansible.posix.authorized_key:
    user: ex_employee
    key: ""
    exclusive: yes
    state: absent
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

### Аудит безопасности через getent
Использование данных из `/etc/shadow` для поиска пользователей с устаревшими паролями.

```yaml
- name: "Сбор информации о пользователях"
  ansible.builtin.getent:
    database: shadow
  register: shadow_info

- name: "Проверка даты истечения пароля"
  ansible.builtin.debug:
    msg: "Пароль пользователя {{ item.key }} требует смены"
  loop: "{{ ansible_facts.getent_shadow | dict2items }}"
  when: item.value[2] | int < (ansible_date_time.epoch | int / 86400 - 90)
```

### Безопасная инициализация с no_log
Скрытие секретов при установке паролей администраторов.

```yaml
- name: "Установка пароля администратора"
  ansible.builtin.user:
    name: admin
    password: "{{ admin_password | password_hash('sha512') }}"
    update_password: always
  no_log: true
```

### Управление GPG-ключами репозиториев
Гарантия подлинности ПО при установке через пакетные менеджеры.

```yaml
- name: "Добавление GPG ключа Docker"
  ansible.builtin.apt_key:
    url: https://download.docker.com/linux/ubuntu/gpg
    state: present
```

### Массовое создание пользователей

```yaml
- name: "Создание группы разработчиков"
  ansible.builtin.group:
    name: developers
    state: present

- name: "Создание пользователей разработчиков"
  ansible.builtin.user:
    name: "{{ item.name }}"
    groups: developers
    append: yes
    shell: /bin/bash
    create_home: yes
    state: present
  loop:
    - { name: "dev_alice" }
    - { name: "dev_bob" }
    - { name: "dev_charlie" }
```

### Настройка парольной политики

```yaml
- name: "Установка политики паролей"
  ansible.builtin.lineinfile:
    path: /etc/login.defs
    regexp: "{{ item.regexp }}"
    line: "{{ item.line }}"
  loop:
    - { regexp: '^PASS_MAX_DAYS', line: 'PASS_MAX_DAYS   90' }
    - { regexp: '^PASS_MIN_DAYS', line: 'PASS_MIN_DAYS   7' }
    - { regexp: '^PASS_MIN_LEN', line: 'PASS_MIN_LEN    12' }
    - { regexp: '^PASS_WARN_AGE', line: 'PASS_WARN_AGE   14' }
```

### Централизованное управление SSH-ключами

```yaml
- name: "Распределение SSH-ключей администраторов"
  ansible.posix.authorized_key:
    user: "{{ item.user }}"
    key: "{{ lookup('file', item.key_file) }}"
    exclusive: yes
    state: present
  loop:
    - { user: "admin1", key_file: "keys/admin1.pub" }
    - { user: "admin2", key_file: "keys/admin2.pub" }
```

### Управление sudoers через шаблон

```yaml
- name: "Настройка sudoers для группы разработчиков"
  ansible.builtin.template:
    src: templates/sudoers_developers.j2
    dest: /etc/sudoers.d/developers
    owner: root
    group: root
    mode: '0440'
    validate: '/usr/sbin/visudo -cf %s'
```

### Проверка и восстановление SSH-доступа

```yaml
- name: "Проверка наличия SSH-ключа"
  ansible.builtin.stat:
    path: "/home/{{ username }}/.ssh/authorized_keys"
  register: ssh_key_stat

- name: "Восстановление SSH-доступа при отсутствии ключа"
  ansible.posix.authorized_key:
    user: "{{ username }}"
    key: "{{ backup_ssh_key }}"
    state: present
  when: not ssh_key_stat.stat.exists
```

### Аудит изменений пользователей

```yaml
- name: "Сбор информации о пользователях"
  ansible.builtin.getent:
    database: passwd
  register: passwd_info

- name: "Логирование изменений"
  ansible.builtin.copy:
    content: |
      Аудит пользователей: {{ ansible_date_time.iso8601 }}
      Пользователи: {{ passwd_info.ansible_facts.getent_passwd | list }}
    dest: "/var/log/user_audit_{{ ansible_date_time.epoch }}.log"
    mode: '0640'
```

### Управление ключами known_hosts

```yaml
- name: "Добавление ключей хостов"
  ansible.builtin.known_hosts:
    name: "{{ item.name }}"
    key: "{{ lookup('pipe', 'ssh-keyscan ' + item.name) }}"
    hash_host: yes
    state: present
  loop:
    - { name: "server1.example.com" }
    - { name: "server2.example.com" }
```

### Синхронизация пользователей между серверами

```yaml
- name: "Получение списка пользователей с эталонного сервера"
  ansible.builtin.getent:
    database: passwd
  delegate_to: "{{ reference_server }}"
  register: reference_users

- name: "Создание отсутствующих пользователей"
  ansible.builtin.user:
    name: "{{ item.key }}"
    shell: "{{ item.value.shell }}"
    home: "{{ item.value.dir }}"
    state: present
  loop: "{{ reference_users.ansible_facts.getent_passwd | dict2items }}"
  when: item.key not in ['root', 'nobody', 'daemon']
```

### Настройка PAM для ограничения доступа

```yaml
- name: "Настройка PAM для ограничения входа"
  ansible.builtin.lineinfile:
    path: /etc/pam.d/login
    line: "auth required pam_access.so"
    state: present
```

### Управление учетными записями с истекшим сроком

```yaml
- name: "Поиск учетных записей с истекшим сроком"
  ansible.builtin.shell: "awk -F: '$7 != \"\" && $7 < $(date +%s) {print $1}' /etc/shadow"
  register: expired_accounts
  changed_when: false

- name: "Блокировка учетных записей с истекшим сроком"
  ansible.builtin.user:
    name: "{{ item }}"
    password_lock: yes
    state: present
  loop: "{{ expired_accounts.stdout_lines }}"
```

### Настройка SELinux для пользователей

```yaml
- name: "Установка SELinux контекста для домашних директорий"
  ansible.builtin.command:
    cmd: "chcon -R -t user_home_t /home/{{ username }}"
  changed_when: false
  when: ansible_selinux.status == "enabled"
```

### Управление группами и членством

```yaml
- name: "Создание системных групп"
  ansible.builtin.group:
    name: "{{ item.name }}"
    gid: "{{ item.gid }}"
    system: yes
    state: present
  loop:
    - { name: "appgroup", gid: 2000 }
    - { name: "deploy", gid: 2001 }

- name: "Добавление пользователей в группы"
  ansible.builtin.user:
    name: "{{ item.user }}"
    groups: "{{ item.groups }}"
    append: yes
  loop:
    - { user: "deploy1", groups: "deploy,appgroup" }
    - { user: "deploy2", groups: "deploy" }
```

### Удаление неактивных пользователей

```yaml
- name: "Поиск неактивных пользователей (не входили > 90 дней)"
  ansible.builtin.shell: "lastlog -b 90 | grep -v Username | awk '{print $1}'"
  register: inactive_users
  changed_when: false

- name: "Удаление неактивных пользователей"
  ansible.builtin.user:
    name: "{{ item }}"
    state: absent
    remove: yes
  loop: "{{ inactive_users.stdout_lines }}"
  when: item not in ['root', 'nobody', 'daemon', 'bin', 'sys', 'sync', 'games', 'man', 'lp', 'mail', 'news', 'uucp', 'proxy', 'www-data', 'backup', 'list', 'irc', 'gnats', 'systemd-network', 'systemd-resolve', 'systemd-timesync', 'messagebus', 'syslog', '_apt', 'tss', 'polkitd', 'snapd', 'chrony', 'sshd', 'tcpdump', 'ansible']
```

### Безопасное управление паролями через Vault

```yaml
- name: "Установка пароля из Vault"
  ansible.builtin.user:
    name: "{{ username }}"
    password: "{{ vault_user_password | password_hash('sha512') }}"
    update_password: always
  no_log: true
  vars:
    ansible_become_password: "{{ vault_become_password }}"
```

### Проверка целостности SSH-ключей

```yaml
- name: "Проверка наличия SSH-ключей"
  ansible.builtin.stat:
    path: "/home/{{ item }}/.ssh/id_rsa.pub"
  register: ssh_keys
  loop: "{{ users_list }}"

- name: "Генерация отсутствующих ключей"
  ansible.builtin.user:
    name: "{{ item.item }}"
    ssh_key_generate: yes
    ssh_key_bits: 4096
    ssh_key_type: rsa
  loop: "{{ ssh_keys.results }}"
  when: not item.stat.exists
```

### Управление доступом к sudo

```yaml
- name: "Настройка passwordless sudo"
  ansible.builtin.lineinfile:
    path: /etc/sudoers.d/{{ username }}
    line: "{{ username }} ALL=(ALL) NOPASSWD: ALL"
    create: yes
    mode: '0440'
    validate: '/usr/sbin/visudo -cf %s'
  when: enable_passwordless_sudo | default(false)
```

### Аудит и мониторинг

```yaml
- name: "Мониторинг изменений в /etc/passwd"
  ansible.builtin.stat:
    path: /etc/passwd
  register: passwd_stat

- name: "Отправка алерта при изменении"
  ansible.builtin.uri:
    url: "{{ webhook_url }}"
    method: POST
    body_format: json
    body:
      text: "Обнаружено изменение /etc/passwd: {{ passwd_stat.stat.checksum }}"
    status_code: 200
  when: passwd_stat.stat.checksum != previous_checksum | default('')
```

### Управление ключами доступа к серверам

```yaml
- name: "Централизованное управление SSH-ключами"
  ansible.posix.authorized_key:
    user: "{{ item.user }}"
    key: "{{ lookup('file', item.key_path) }}"
    exclusive: "{{ item.exclusive | default('yes') }}"
    state: present
  loop:
    - { user: "admin", key_path: "/etc/ansible/keys/admin.pub", exclusive: "yes" }
    - { user: "deploy", key_path: "/etc/ansible/keys/deploy.pub", exclusive: "yes" }
    - { user: "monitoring", key_path: "/etc/ansible/keys/monitoring.pub", exclusive: "no" }
```

### Управление пользователями LDAP

```yaml
- name: "Настройка LDAP аутентификации"
  ansible.builtin.template:
    src: templates/nsswitch.conf.j2
    dest: /etc/nsswitch.conf
    owner: root
    group: root
    mode: '0644'

- name: "Настройка PAM для LDAP"
  ansible.builtin.template:
    src: templates/pam_ldap.conf.j2
    dest: /etc/pam_ldap.conf
    owner: root
    group: root
    mode: '0644'
```

### Восстановление учетных записей

```yaml
- name: "Бэкап учетных записей"
  ansible.builtin.shell: "getent passwd > /backup/passwd_{{ ansible_date_time.epoch }}.bak"
  changed_when: false

- name: "Восстановление учетных записей из бэкапа"
  ansible.builtin.shell: "cat /backup/passwd_latest.bak | while read line; do echo $line >> /etc/passwd; done"
  when: restore_accounts | default(false)
```

### Управление доступом через ACL

```yaml
- name: "Настройка ACL для общих директорий"
  ansible.posix.acl:
    path: "{{ item.path }}"
    entity: "{{ item.entity }}"
    etype: "{{ item.etype }}"
    permissions: "{{ item.permissions }}"
    state: present
    recursive: yes
  loop:
    - { path: "/shared/projects", entity: "developers", etype: "group", permissions: "rwx" }
    - { path: "/shared/logs", entity: "monitoring", etype: "user", permissions: "r" }
    - { path: "/shared/backup", entity: "backup", etype: "group", permissions: "rx" }
```

### Управление SSH-ключами хостов

```yaml
- name: "Добавление ключей хостов для предотвращения MITM"
  ansible.builtin.known_hosts:
    name: "{{ item.name }}"
    key: "{{ lookup('pipe', 'ssh-keyscan -t rsa,ecdsa,ed25519 ' + item.name) }}"
    hash_host: yes
    state: present
  loop:
    - { name: "db-master.internal" }
    - { name: "db-replica.internal" }
    - { name: "app-server.internal" }
```

### Управление PAM модулями

```yaml
- name: "Настройка PAM для ограничения по времени"
  ansible.builtin.lineinfile:
    path: /etc/pam.d/common-auth
    line: "auth required pam_time.so"
    state: present
```

### Управление SELinux пользователями

```yaml
- name: "Настройка SELinux пользователей"
  ansible.posix.selinux:
    policy: targeted
    state: enforcing
  when: ansible_distribution in ["CentOS", "RedHat"]

- name: "Установка SELinux контекста для файлов"
  ansible.builtin.command:
    cmd: "chcon -R -t httpd_sys_content_t /var/www/html"
  changed_when: false
```

### Управление учетными записями сервисов

```yaml
- name: "Создание учетных записей для сервисов"
  ansible.builtin.user:
    name: "{{ item.name }}"
    system: yes
    shell: /bin/false
    home: "{{ item.home }}"
    create_home: no
    state: present
  loop:
    - { name: "nginx", home: "/var/www" }
    - { name: "mysql", home: "/var/lib/mysql" }
    - { name: "redis", home: "/var/lib/redis" }
```

### Управление SSH-ключами для сервисов

```yaml
- name: "Распределение SSH-ключей для сервисов"
  ansible.posix.authorized_key:
    user: "{{ item.user }}"
    key: "{{ lookup('file', item.key_path) }}"
    state: present
  loop:
    - { user: "nginx", key_path: "/etc/ansible/keys/nginx.pub" }
    - { user: "mysql", key_path: "/etc/ansible/keys/mysql.pub" }
```

### Управление доступом к системным ресурсам

```yaml
- name: "Настройка лимитов ресурсов для пользователей"
  ansible.builtin.lineinfile:
    path: /etc/security/limits.conf
    line: "{{ item.user }} {{ item.type }} {{ item.item }} {{ item.value }}"
    state: present
  loop:
    - { user: "nginx", type: "soft", item: "nofile", value: "65535" }
    - { user: "nginx", type: "hard", item: "nofile", value: "65535" }
    - { user: "mysql", type: "soft", item: "nofile", value: "65535" }
    - { user: "mysql", type: "hard", item: "nofile", value: "65535" }
```

### Управление учетными записями для мониторинга

```yaml
- name: "Создание учетной записи для мониторинга"
  ansible.builtin.user:
    name: monitoring
    system: yes
    shell: /bin/false
    home: /var/lib/monitoring
    create_home: yes
    state: present

- name: "Настройка доступа для мониторинга"
  ansible.posix.acl:
    path: /var/log
    entity: monitoring
    etype: user
    permissions: r
    state: present
    recursive: yes
```

## Устранение неполадок

- **"User already exists"**: Пользователь уже создан. Используйте `state: present` для идемпотентности.
- **"Group not found"**: Группа не существует. Создайте группу перед добавлением пользователя.
- **"Permission denied"**: Нет прав на изменение. Используйте `become: yes`.
- **"No such file or directory"**: Отсутствует домашняя директория. Создайте директорию или используйте `create_home: yes`.
- **"Invalid password hash"**: Неправильный формат хеша. Используйте `password_hash('sha512')`.
- **"SSH key not found"**: Отсутствует файл ключа. Проверьте путь к файлу ключа.
- **"Invalid shell"**: Указана несуществующая оболочка. Проверьте доступные оболочки в `/etc/shells`.
- **"Account locked"**: Попытка входа заблокированного пользователя. Используйте `password_lock: no` для разблокировки.

## Дополнительная информация

- **[Ansible Vault: управление секретами](../Vault/basics.md)** — безопасное хранение хешей и ключей.
- **[Рекомендации по безопасности Ansible](../ansible_security_best_practices.md)** — архитектурные паттерны защиты инфраструктуры.
- **[Управление привилегиями: sudo и sudoers](../../Linux/SystemAdministration/privilege_management.md)** — глубокая настройка прав в Linux.
- **[Определения пользователей и групп в Linux](../../Linux/SystemAdministration/Users/users_definitions.md)** — теоретическая база и стандарты UID/GID.
- **[Основные концепции Ansible](../ansible_core_concepts.md)** — архитектура и идемпотентность.
- **[Модули управления службами](ansible_service_and_system_config_modules.md)** — управление сервисами и конфигурацией системы.
- **[Модули управления файлами](ansible_file_management_modules.md)** — копирование, шаблонизация и управление файлами.
- **[Модули управления пакетами](ansible_package_management_modules.md)** — установка и управление программным обеспечением.
- **[Тестирование с Molecule](../ansible_testing_with_molecule.md)** — проверка кода автоматизации.
- **[Платформо-независимые концепции](../CrossPlatform/concepts.md)** — кроссплатформенные подходы.
- **[Плохие практики](../ansible_bad_practices.md)** — распространенные ошибки и их решение.
