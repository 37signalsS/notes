# Ansible: Модули управления пользователями и безопасностью

## Определения

**Модули управления пользователями и безопасностью** — это группа специализированных декларативных инструментов Ansible (преимущественно `ansible.builtin` и `ansible.posix`), предназначенных для управления жизненным циклом учетных записей, правами доступа и механизмами аутентификации на управляемых хостах.

Использование этих модулей гарантирует идентичность настроек безопасности на всем парке серверов, исключая человеческий фактор при настройке привилегий и SSH-доступа. Это ключевой элемент реализации концепции «Безопасность как код» (Security as Code).

**FQCN (Fully Qualified Collection Name)** — полное имя модуля (например, `ansible.builtin.user`). Использование FQCN является обязательным стандартом для предотвращения конфликтов имен и обеспечения предсказуемости выполнения во всех современных версиях Ansible.

## Требования к версиям

| Компонент | Минимальная версия | Примечание |
| :--- | :--- | :--- |
| **ansible-core** | 2.16+ | Рекомендуется 2.21+ (GA: май 2026). Содержит `ansible.builtin.user`, `ansible.builtin.group`, `ansible.builtin.getent`, `ansible.builtin.known_hosts`, `ansible.builtin.copy`, `ansible.builtin.template`, `ansible.builtin.lineinfile`, `ansible.builtin.blockinfile`, `ansible.builtin.file`, `ansible.builtin.stat`, `ansible.builtin.rpm_key`, `ansible.builtin.deb822_repository`, `ansible.builtin.password` |
| **ansible.posix** | 2.2+ | Требует ansible-core 2.16+. Содержит `ansible.posix.authorized_key`, `ansible.posix.acl`, `ansible.posix.selinux`. Установка: `ansible-galaxy collection install ansible.posix` |
| **Python (Control Node)** | 3.12 – 3.14 | Для ansible-core 2.21+ |
| **Python (Target)** | 3.9 – 3.14 | Минимальная версия Python на управляемых хостах для модулей, требующих интерпретатора |

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
    *   `ansible.builtin.rpm_key`: Управление GPG-ключами в формате RPM (RHEL/CentOS/Fedora). Актуальный подход.
    *   `ansible.builtin.apt_key`: Управление GPG-ключами APT. **Модуль объявлен устаревшим и будет удалён в ansible-core 2.25** — используйте `ansible.builtin.get_url` (загрузка ключа в `/etc/apt/keyrings/*.asc`) совместно с `ansible.builtin.deb822_repository` либо `ansible.builtin.apt_repository` с параметром `signed-by`.
    *   `ansible.builtin.password`: Генерация случайных паролей на контрольном узле.
    *   `no_log: true`: Параметр задачи (не модуль), критически важный для предотвращения утечки секретов в логи и вывод консоли.
4.  **Сетевая безопасность и брандмауэры:**
     *   `ansible.posix.seboolean`: Управление логическими переключателями SELinux (boolean). Позволяет включать/отключать отдельные политики без изменения глобального режима enforcing/permissive.
     *   `community.general.sealert`: Анализ сообщений SELinux и получение рекомендаций по устранению нарушений. Используется для диагностики и Compliance-отчетов.
     *   `community.general.sestatus`: Получение текущего статуса SELinux ( enforcing/permissive/disabled ), списка активных boolean'ов и политики. Полезен для аудита.
     *   `ansible.posix.firewalld`: Управление файрволом firewalld (RHEL/CentOS/Fedora/SUSE). Поддерживает зоны, сервисы, порты, богатые правила.
     *   `community.general.ufw`: Управление Uncomplicated Firewall (Debian/Ubuntu). Простой интерфейс для iptables/nftables.
     *   `ansible.builtin.nftables`: Управление nftables (современная замена iptables). Поддерживает families (inet, ip, ip6, arp, netdev), таблицы, chains, rules, sets.
     *   `community.general.iptables`: Управление iptables-legacy (для систем, не перешедших на nftables). Управление chains, rules, policies.
     *   `community.general.apparmor`: Управление профилями AppArmor (Debian/Ubuntu/SUSE). Поддерживает режимы enforce/complain/disable.
5.  **Управление файлами и конфигурацией:**
     *   `ansible.builtin.copy`: Копирование файлов на управляемые хосты.
     *   `ansible.builtin.template`: Генерация файлов из шаблонов Jinja2.
     *   `ansible.builtin.lineinfile`: Гарантированное внесение изменений в отдельные строки файлов.
     *   `ansible.builtin.blockinfile`: Вставка/обновление блоков текста в файлах.
     *   `ansible.builtin.file`: Управление свойствами файлов и директорий (owner, group, mode).
     *   `ansible.builtin.stat`: Сбор информации о файлах и директориях.

### Привилегированный доступ (Become)

Все модули управления пользователями, группами, sudoers, ACL, SELinux и ключами требуют привилегий суперпользователя. Отсутствие `become` приводит к `Permission denied` даже при корректном синтаксисе задачи.

| Параметр | Значение | Описание |
| :--- | :--- | :--- |
| `become` | `true` / `yes` | Включение привилегированного режима для задачи или плейбука |
| `become_user` | `root` / `postgres` / `www-data` | Пользователь, от имени которого выполняется задача |
| `become_method` | `sudo` / `su` / `pbrun` / `pfexec` | Метод повышения привилегий |
| `become_flags` | `-H -S` | Дополнительные флаги (например, `-H` для установки HOME, `-S` для чтения пароля из stdin) |

**Важные замечания:**
- Используйте `become: true` на уровне задачи, а не глобально для всего плейбука, если это возможно (принцип наименьших привилегий).
- Для `ansible.builtin.user` и `ansible.builtin.group` требуется `become: true`, так как они записывают в `/etc/passwd`, `/etc/shadow`, `/etc/group`.
- Для `ansible.posix.authorized_key` требуется `become: true` при работе с домашними директориями других пользователей (запись в `~/.ssh/authorized_keys`).
- Для `ansible.builtin.template` с `dest: /etc/sudoers.d/*` требуется `become: true` и `validate: '/usr/sbin/visudo -cf %s'` для предотвращения блокировки sudo.
- На целевых хостах должен быть настроен passwordless sudo для пользователя автоматизации, либо предоставлен `ansible_become_password`.

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

#### Политика паролей и `/etc/shadow`
Файл `/etc/shadow` содержит 9 полей, разделенных двоеточиями:
`username:hash:last_chg:min:max:warn:inactive:expire:reserved`

| Поле | Назначение | Управление через Ansible |
| :--- | :--- | :--- |
| `last_chg` | Дата последней смены пароля (epoch) | Поле обновляется автоматически при смене пароля |
| `min` | Минимальный срок жизни пароля (дни) | Настраивается через `/etc/login.defs` (`PASS_MIN_DAYS`) |
| `max` | Максимальный срок жизни пароля (дни) | Настраивается через `/etc/login.defs` (`PASS_MAX_DAYS`) |
| `warn` | Предупреждение перед истечением (дни) | Настраивается через `/etc/login.defs` (`PASS_WARN_AGE`) |
| `inactive` | Блокировка после неактивности (дни) | Настраивается через `useradd -f` или `usermod -f` |
| `expire` | Дата истечения срока действия учетной записи (epoch) | Параметр `expires` модуля `ansible.builtin.user` |

**Рекомендация:** Для аудита используйте модуль `ansible.builtin.getent` с `database: shadow` и сравнивайте значения `max` с текущей датой.

#### PAM (Pluggable Authentication Modules)
PAM-стек управляет аутентификацией, авторизацией и учетом сессий. Ansible не имеет нативного модуля PAM, поэтому конфигурация осуществляется через `ansible.builtin.lineinfile` или `ansible.builtin.template`:

```yaml
- name: "Ограничение времени входа через pam_time"
  ansible.builtin.lineinfile:
    path: /etc/pam.d/login
    line: "account required pam_time.so"
    state: present
  notify: restart sshd
```

**Важные PAM-модули для безопасности:**
- `pam_faillock.so` — блокировка учетной записи после N неудачных попыток входа
- `pam_tally2.so` — учет неудачных попыток (устарел, используйте `faillock`)
- `pam_access.so` — контроль доступа на основе `/etc/security/access.conf`
- `pam_limits.so` — применение лимитов из `/etc/security/limits.conf`

#### SELinux и пользовательские контексты
Для корректной работы SELinux с домашними директориями пользователей необходимо устанавливать правильные контексты:

```yaml
- name: "Установка контекста SELinux для домашней директории"
  ansible.builtin.command:
    cmd: "chcon -R -t user_home_t /home/{{ username }}"
    warn: false
  changed_when: false
  when: ansible_selinux.status == "enforced"

- name: "Восстановление контекста по политике (permanent)"
  ansible.builtin.command:
    cmd: "restorecon -Rv /home/{{ username }}"
  changed_when: false
  when: ansible_selinux.status == "enforced"
```

**Ключевые контексты:**
- `user_home_t` — стандартный контекст домашней директории
- `ssh_home_t` — директория `.ssh` (устанавливается автоматически при создании пользователя)
- `user_home_dir_t` — сама директория `/home/username`

#### ACL и наследование
Параметр `recursive: yes` применяет ACL рекурсивно к существующим файлам, но не создает наследуемые ACL (default ACL) для новых файлов. Для этого используется `default:user` и `default:group`:

```yaml
- name: "Настройка ACL с наследованием для новых файлов"
  ansible.posix.acl:
    path: /shared/projects
    entity: developers
    etype: group
    permissions: rwx
    state: present
    default: yes
  register: acl_result
# → changed: true
```

### Оптимизация производительности

**Параметры для ускорения работы:**
- Используйте `ansible.builtin.user` вместо команд `useradd`/`usermod` для декларативного управления
- Кэшируйте факты с помощью `ansible.builtin.set_fact` для повторного использования
- Ограничивайте сбор фактов через `gather_facts: no` и `ansible.builtin.setup` только при необходимости
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
# → changed: [target] => {"changed": true, "uid": 998, "gid": 998, "home": "/home/backup_mgr"}

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
# → changed: [target] => {"changed": true, "ssh_public_keys": ["ssh-ed25519 AAAA..."]}

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
# → changed: [target] => {"changed": true, "user": "ex_employee", "state": "locked"}

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

**RPM-системы (RHEL/CentOS/Fedora)** — `ansible.builtin.rpm_key`:

```yaml
- name: "Импорт GPG-ключа репозитория (RPM)"
  ansible.builtin.rpm_key:
    key: https://repo.example.com/keys/gpg.key
    state: present
```
# → changed: [target] => {"changed": true}

**Debian/Ubuntu (актуальный подход)** — `ansible.builtin.apt_key` объявлен устаревшим и удаляется в ansible-core 2.25. Ключ скачивается в отдельный каталог `/etc/apt/keyrings/`, а репозиторий описывается в формате deb822:

```yaml
- name: "Загрузка GPG-ключа в /etc/apt/keyrings"
  ansible.builtin.get_url:
    url: https://repo.example.com/keys/gpg.asc
    dest: /etc/apt/keyrings/repo.example.com.asc
    mode: "0644"
  # → changed: [target] => {"changed": true}

- name: "Добавление репозитория в формате deb822"
  ansible.builtin.deb822_repository:
    name: repo_example
    url: "https://repo.example.com/debian"
    distribution: "{{ ansible_facts.distribution_release }}"
    components: [main]
    signed_by: /etc/apt/keyrings/repo.example.com.asc
    state: present
  register: repo_result
  # → changed: [target] => {"changed": true}

- name: "Обновление индекса пакетов"
  ansible.builtin.apt:
    update_cache: true
  when: repo_result is changed
```

Альтернатива для старого формата — `ansible.builtin.apt_repository` с явным `signed-by`:

```yaml
- name: "Репозиторий в формате apt_repository с ключом"
  ansible.builtin.apt_repository:
    repo: "deb [arch=amd64 signed-by=/etc/apt/keyrings/repo.example.com.asc] https://repo.example.com/debian {{ ansible_facts.distribution_release }} main"
    filename: /etc/apt/sources.list.d/repo_example.list
    state: present
  # → changed: [target] => {"changed": true}
```

Почему порядок важен: ключ должен существовать на диске **до** обращения APT к репозиторию, иначе `apt update` завершится ошибкой проверки подписи. Параметр `checksum` в `get_url` гарантирует, что подставлен не подменённый файл ключа.

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
# → changed: [target] => {"changed": true, "results": [{"name": "dev_alice", "uid": 1001}, ...]}

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
# → changed: [target] => {"changed": true, "updates": ["PASS_MAX_DAYS", "PASS_MIN_DAYS"]}

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
# → changed: [target] => {"changed": true, "results": [{"user": "admin1"}, {"user": "admin2"}]}

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
# → changed: [target] => {"changed": true, "dest": "/etc/sudoers.d/developers"}

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
# → ok: [target] => {"changed": false, "stat": {"exists": true, "mode": "0600"}}

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
# → changed: [target] => {"changed": true, "results": [{"name": "server1.example.com"}, {"name": "server2.example.com"}]}

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
# → changed: [target] => {"changed": true, "results": [{"name": "deploy", "uid": 1001}, ...]}

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
# → changed: [target] => {"changed": true, "results": [{"user": "deploy1"}, {"user": "deploy2"}]}

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
# → changed: [target] => {"changed": true, "dest": "/etc/sudoers.d/deploy"}

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
# → changed: [target] => {"changed": true, "results": [{"user": "admin"}, {"user": "deploy"}, {"user": "monitoring"}]}

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
# → changed: [target] => {"changed": true, "results": [{"path": "/shared/projects"}, ...]}

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
# → changed: [target] => {"changed": true, "results": [{"name": "db-master.internal"}, ...]}

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
# → changed: [target] => {"changed": true, "user": "monitoring", "uid": 998}

### Развертывание в air-gapped среде

В изолированных сегментах сети (без доступа к интернет) используются локальные зеркала коллекций и pre-staged ключей. SSH-ключи передаются через внутренний Nexus/Artifactory или включены в образControl Node.

```yaml
- name: "Установка ansible.posix из локального зеркала"
  ansible.builtin.apt:
    deb: "file:///mirror/ansible-posix-2.2.2.tar.gz"
  become: true

- name: "Развертывание SSH-ключей из локального хранилища"
  ansible.posix.authorized_key:
    user: "{{ item.user }}"
    key: "{{ lookup('file', '/keys/' + item.user + '.pub') }}"
    exclusive: yes
    state: present
  loop:
    - { user: "deploy" }
    - { user: "monitoring" }
# → changed: [{"user": "deploy"}, {"user": "monitoring"}]
```

### Массовое развертывание с контролем параллелизма

При работе с тысячами хостов используется `serial` для ограничения числа одновременных подключений и `throttle` для защиты LDAP/SSSD от перегрузки.

```yaml
- name: "Массовое создание пользователей с throttling"
  hosts: all
  serial:
    - 10
    - 25%
    - 100%
  throttle: 5
  become: true
  vars:
    new_users:
      - name: svc_app
        groups: appgroup
        shell: /bin/false
      - name: svc_backup
        groups: backup
        shell: /bin/bash
  tasks:
    - name: "Создание пользователей батчами"
      ansible.builtin.user:
        name: "{{ item.name }}"
        groups: "{{ item.groups }}"
        append: yes
        shell: "{{ item.shell }}"
        state: present
      loop: "{{ new_users }}"
# → PLAY RECAP: ok=12  changed=8  skipped=0  unresolvable=0  failed=0
```

### Compliance-аудит пользователей и доступов

Регулярная проверка соответствия политикам безопасности: учетные записи без сроков действия, дублирующиеся UID 0, ключи с устаревшими алгоритмами.

```yaml
- name: "Аудит учетных записей с UID 0"
  ansible.builtin.getent:
    database: passwd
  register: passwd_info
  changed_when: false

- name: "Проверка дублирования UID 0"
  ansible.builtin.assert:
    that:
      - passwd_info.ansible_facts.getent_passwd | dict2items
        | selectattr('value.uid', 'equalto', 0)
        | list
        | length == 1
    fail_msg: "Обнаружено несколько пользователей с UID 0"
    success_msg: "Только root имеет UID 0"
# → ok: [target] => {"changed": false, "msg": "Только root имеет UID 0"}

- name: "Проверка алгоритмов SSH-ключей"
  ansible.builtin.find:
    paths: /home
    patterns: "id_rsa"
    file_type: file
  register: weak_keys
  changed_when: false

- name: "Алерт при обнаружении устаревших ключей"
  ansible.builtin.debug:
    msg: "Обнаружены устаревшие RSA-ключи: {{ weak_keys.files | map(attribute='path') | list }}"
  when: weak_keys.matched > 0
```

### Blue-green cutover при массовой смене SSH-ключей

Ротация ключей без риска блокировки: новые ключи добавляются параллельно, старые удаляются только после подтверждения работоспособности.

```yaml
- name: "Этап 1: Добавление новых SSH-ключей (неуникальные)"
  ansible.posix.authorized_key:
    user: "{{ item }}"
    key: "{{ lookup('file', 'keys/new_admin.pub') }}"
    exclusive: no
    state: present
  loop: "{{ admin_users }}"
# → changed: [admin1, admin2, admin3]

- name: "Этап 2: Верификация доступа по новым ключам"
  ansible.builtin.shell: |
    ssh -o BatchMode=yes -o ConnectTimeout=5 \
        -i /keys/new_admin \
        admin@{{ inventory_hostname }} hostname
  delegate_to: localhost
  register: ssh_verify
  changed_when: false
  loop: "{{ admin_users }}"
  until: ssh_verify is succeeded
  retries: 3
  delay: 10

- name: "Этап 3: Удаление старых ключей (exclusive)"
  ansible.posix.authorized_key:
    user: "{{ item }}"
    key: "{{ lookup('file', 'keys/old_admin.pub') }}"
    exclusive: yes
    state: absent
  loop: "{{ admin_users }}"
  when: ssh_verify is succeeded
# → changed: [admin1, admin2, admin3]
```

### Аудит sudoers и выявления избыточных прав

```yaml
- name: "Сбор всех файлов sudoers.d"
  ansible.builtin.find:
    paths: /etc/sudoers.d
    patterns: "*"
    file_type: file
  register: sudoers_files
  changed_when: false

- name: "Проверка синтаксиса каждого файла"
  ansible.builtin.command: "/usr/sbin/visudo -cf {{ item.path }}"
  register: sudoers_validate
  changed_when: false
  loop: "{{ sudoers_files.files }}"
  failed_when: sudoers_validate.rc != 0

- name: "Отчет о невалидных файлах"
  ansible.builtin.debug:
    msg: "Ошибка в {{ item.item.path }}: {{ item.stdout }}"
  when: item.rc != 0
  loop: "{{ sudoers_validate.results }}"
# → ok: [target] => {"changed": false, "msg": "Все файлы sudoers валидны"}
```

## Операции и команды

### Управление пользователями (`ansible.builtin.user`)

| Параметр | Значение | Описание |
| :--- | :--- | :--- |
| `name` | строка | Имя пользователя |
| `state` | `present` / `absent` | Создать или удалить пользователя |
| `uid` | integer | UID пользователя |
| `group` | строка | Основная группа |
| `groups` | список | Дополнительные группы |
| `append` | `yes` / `no` | Добавить к существующим группам вместо замены |
| `shell` | путь | Оболочка входа |
| `home` | путь | Домашняя директория |
| `create_home` | `yes` / `no` | Создавать домашнюю директорию |
| `system` | `yes` / `no` | Системный пользователь (UID < 1000) |
| `comment` | строка | Комментарий (поле GECOS) |
| `password` | хеш | Хеш пароля (SHA-512) |
| `update_password` | `on_create` / `always` | Обновлять пароль при каждом запуске |
| `password_lock` | `yes` / `no` | Блокировка учетной записи |
| `expires` | epoch | Дата истечения срока действия |
| `force` | `yes` / `no` | Принудительно удалить домашнюю директорию при `absent` |
| `remove` | `yes` / `no` | Удалить домашнюю директорию при `absent` |
| `ssh_key_generate` | `yes` / `no` | Автогенерация SSH-ключа |
| `ssh_key_bits` | integer | Длина ключа |
| `ssh_key_type` | `rsa` / `ecdsa` / `ed25519` | Тип ключа |
| `ssh_key_file` | путь | Путь для сохранения приватного ключа |
| `ssh_key_comment` | строка | Комментарий к ключу |

### Управление группами (`ansible.builtin.group`)

| Параметр | Значение | Описание |
|----------|----------|----------|
| `name` | строка | Имя группы |
| `state` | `present` / `absent` | Создать или удалить группу |
| `gid` | integer | GID группы |
| `system` | `yes` / `no` | Системная группа |

### Управление SSH-ключами (`ansible.posix.authorized_key`)

| Параметр | Значение | Описание |
| :--- | :--- | :--- |
| `user` | строка | Имя пользователя |
| `key` | строка | Публичный ключ или путь к файлу |
| `state` | `present` / `absent` | Добавить или удалить ключ |
| `exclusive` | `yes` / `no` | Удалить все остальные ключи |
| `path` | путь | Нестандартный путь к `authorized_keys` |
| `comment` | строка | Комментарий к ключу (игнорируется при `exclusive`) |
| `type` | строка | Тип ключа (`ssh-rsa`, `ssh-ed25519`, `ecdsa-sha2-nistp256`) |
| `validate_certs` | `yes` / `no` | Проверять SSL-сертификаты при загрузке ключа по URL |

### Управление известными хостами (`ansible.builtin.known_hosts`)

| Параметр | Значение | Описание |
| :--- | :--- | :--- |
| `name` | строка | Имя хоста или IP |
| `key` | строка | Ключ в формате `ssh-keyscan` |
| `state` | `present` / `absent` | Добавить или удалить запись |
| `hash_host` | `yes` / `no` | Хешировать имя хоста |
| `port` | integer | Порт SSH (для нестандартных портов) |

### Управление доступом (ACL) (`ansible.posix.acl`)

| Параметр | Значение | Описание |
| :--- | :--- | :--- |
| `path` | путь | Путь к файлу или директории |
| `entity` | строка | Пользователь или группа |
| `etype` | `user` / `group` | Тип сущности |
| `permissions` | строка | Права доступа (rwx) |
| `state` | `present` / `absent` | Добавить или удалить ACL |
| `recursive` | `yes` / `no` | Рекурсивное применение |
| `default` | `yes` / `no` | Создать default ACL для наследования новыми файлами |
| `follow` | `yes` / `no` | Следовать по символическим ссылкам |

### Управление GPG-ключами (`ansible.builtin.rpm_key`, `ansible.builtin.deb822_repository`)

| Модуль | Параметр | Значение | Описание |
| :--- | :--- | :--- | :--- |
| `ansible.builtin.rpm_key` | `key` | URL или путь | URL/файл GPG-ключа для RPM-систем |
| `ansible.builtin.rpm_key` | `state` | `present` / `absent` | Добавить или удалить ключ |
| `ansible.builtin.get_url` | `url` | URL | URL ключа для Debian/Ubuntu |
| `ansible.builtin.get_url` | `dest` | путь | Путь в `/etc/apt/keyrings/` |
| `ansible.builtin.get_url` | `checksum` | `sha256:...` | Контрольная сумма для защиты от подмены ключа |
| `ansible.builtin.deb822_repository` | `name` | строка | Имя репозитория |
| `ansible.builtin.deb822_repository` | `signed_by` | путь | Ссылка на файл ключа |
| `ansible.builtin.deb822_repository` | `state` | `present` / `absent` | Добавить или удалить репозиторий |

`ansible.builtin.apt_key` оставлен в списке устаревших и будет удалён в ansible-core 2.25.

### Аудит пользователей и групп (`ansible.builtin.getent`)

| Параметр | Значение | Описание |
| :--- | :--- | :--- |
| `database` | `passwd` / `group` / `shadow` / `hosts` / `services` | База данных для запроса |

### Ad-hoc команды

```bash
# Создание пользователя
ansible all -m ansible.builtin.user -a "name=deploy state=present" --become
# → target | CHANGED => {"changed": true, "uid": 1001}

# Добавление SSH-ключа
ansible all -m ansible.posix.authorized_key -a "user=deploy key=<SECRET_f9345705> create_home=yes" --become
# → target | CHANGED => {"changed": true, "ssh_public_keys": ["ssh-ed25519 AAAA..."]}

# Создание группы
ansible all -m ansible.builtin.group -a "name=developers state=present" --become
# → target | CHANGED => {"changed": true, "gid": 2000}

# Проверка фактов о пользователях
ansible all -m ansible.builtin.getent -a "database=passwd"
# → target | SUCCESS => {"ansible_facts": {"getent_passwd": {"root": ["root", "x", "0", ...]}}}

# Блокировка пользователя
ansible all -m ansible.builtin.user -a "name=ex_employee password_lock=yes" --become
# → target | CHANGED => {"changed": true, "user": "ex_employee", "state": "locked"}

# Добавление ACL
ansible all -m ansible.posix.acl -a "path=/var/log/nginx entity=prometheus etype=user permissions=rx state=present recursive=yes" --become
# → target | CHANGED => {"changed": true}

# Добавление known_hosts
ansible all -m ansible.builtin.known_hosts -a "name=server1.example.com key=$(ssh-keyscan server1.example.com) hash_host=yes state=present" --become
# → target | CHANGED => {"changed": true}
```

## Устранение неполадок

### Типичные ошибки модулей

| Ошибка | Причина | Решение | Диагностика |
| :--- | :--- | :--- | :--- |
| `User already exists` | Пользователь уже создан | Используйте `state: present` для идемпотентности | `id username` |
| `Group not found` | Группа не существует | Создайте группу перед добавлением пользователя | `getent group developers` |
| `Permission denied` | Нет прав на изменение | Используйте `become: yes` | `ansible target -m ping -vvv` |
| `No such file or directory` | Отсутствует домашняя директория | Создайте директорию или используйте `create_home: yes` | `ls -la /home` |
| `Invalid password hash` | Неправильный формат хеша | Используйте `password_hash('sha512')` | `getent shadow username` |
| `SSH key not found` | Отсутствует файл ключа | Проверьте путь к файлу ключа | `ls -la keys/` |
| `Invalid shell` | Указана несуществующая оболочка | Проверьте доступные оболочки в `/etc/shells` | `grep username /etc/passwd` |
| `Account locked` | Попытка входа заблокированного пользователя | Используйте `password_lock: no` для разблокировки | `passwd -S username` |
| `authorized_key: unsafe_writing` | Файл `authorized_keys` имеет неверные права | Установите права `0600` на файл и `0700` на директорию `.ssh` | `stat -c "%a %n" ~/.ssh/authorized_keys` |
| `SELinux: Permission denied` | Неверный контекст SELinux | Примените `restorecon -Rv /home/username` или настройте модуль `selinux` | `ls -Z /home/username` |
| `ACL: Operation not supported` | Файловая система не поддерживает ACL | Используйте ext4/XFS с опцией `acl` в fstab | `tune2fs -l /dev/sda1 \| grep options` |
| `getent: database not found` | База данных не поддерживается системой | Проверьте доступные базы: `getent --help` | `getent passwd` |
| `visudo: syntax error` | Ошибка в синтаксисе sudoers | Проверьте файл через `visudo -cf /etc/sudoers.d/file` | `visudo -csf /etc/sudoers.d/*` |
| `lastlog: data integrity error` | Поврежденная база данных lastlog | Перестройте базу: `touch /var/log/lastlog` (осторожно!) | `lastlog -u username` |

### Диагностические команды

```bash
# Проверка статуса пользователя
id username
# → uid=1001(deploy) gid=1001(deploy) groups=1001(deploy),27(sudo)

# Проверка блокировки учетной записи
passwd -S username
# → username L 08/22/2025 0 99999 7 -1 (L = locked, P = password set, NP = no password)

# Проверка срока действия пароля
chage -l username
# → Last password change: 08/22/2025
# → Password expires: 11/20/2025
# → Password inactive: 02/16/2026
# → Account expires: never

# Проверка прав на .ssh
namei -l /home/deploy/.ssh/authorized_keys
# → drwxr-xr-x root root /
# → drwxr-xr-x root root home
# → drwx------ deploy deploy deploy
# → drwxr-xr-x deploy deploy .ssh
# → -rw------- deploy deploy authorized_keys

# Проверка SELinux контекста
ls -Z /home/deploy/.ssh
# → system_u:object_r:ssh_home_t:s0 authorized_keys

# Проверка фактов Ansible
ansible target -m ansible.builtin.user -a "name=deploy" -vvv
# → ok: [target] => {"ansible_facts": {"user_info": {...}}}
```

### Анализ ошибок выполнения

```bash
# Запуск с максимальной детализацией
ansible-playbook site.yml --verbose --diff
# → TASK [Create user] ****************************************************************
# → task path: /playbooks/users.yml:15
# => {"ansible_facts": {"discovered_interpreter_python": "/usr/bin/python3"}, "changed": false, "user": "deploy", "uid": 1001}

# Проверка идемпотентности
ansible-playbook site.yml --check
# → PLAY RECAP: ok=12  changed=0  skipped=5  unresolvable=0  failed=0

## Лучшие практики

### Идемпотентность и повторное выполнение
- Всегда указывайте `state: present` для создания ресурсов и `state: absent` для удаления
- Используйте модули `ansible.builtin.user` и `ansible.builtin.group` вместо `ansible.builtin.shell` с командами `useradd`/`usermod`/`groupadd`
- Для `authorized_key` используйте `exclusive: yes` для гарантии точного состояния ключей
- Избегайте `force: yes` и `create_home: yes` без необходимости — это нарушает декларативность
- Тестируйте изменения с `--check` и `--diff` перед применением в production

### Безопасность и секреты
- Используйте `no_log: true` для всех задач, работающих с паролями, ключами и секретами
- Храните секреты в [Ansible Vault](../Vault/basics.md), а не в плейбуках или переменных
- Для паролей всегда используйте хеширование `password_hash('sha512')`, никогда не передавайте открытый текст
- Ограничивайте срок действия паролей через параметр `expires` и политики `/etc/login.defs`
- Используйте `ansible.posix.acl` для тонкой настройки прав вместо глобальных изменений `chmod`
- Для `known_hosts` используйте `hash_host: yes` для защиты от разведки

### Привилегированный доступ
- Используйте `become: yes` только для задач, требующих привилегий; избегайте глобального `become: true`
- Настраивайте sudoers через шаблоны с обязательной валидацией `validate: '/usr/sbin/visudo -cf %s'`
- Применяйте принцип минимальных привилегий: создавайте сервисные учетные записи с `shell: /bin/false` и `system: yes`
- Используйте `password_lock: yes` для блокировки учетных записей вместо удаления — это сохраняет аудиторский след

### Аудит и мониторинг
- Регулярно используйте `ansible.builtin.getent` для сбора актуальных фактов о пользователях и группах
- Логируйте изменения через `ansible.builtin.copy` или внешние системы мониторинга
- Используйте `ansible.builtin.stat` для отслеживания изменений критических файлов (`/etc/passwd`, `/etc/shadow`, `/etc/sudoers`)
- Настраивайте алерты при изменении контрольных сумм критических файлов

### Управление конфигурацией
- Храните конфигурации в системе контроля версий (Git), включая плейбуки, шаблоны и переменные
- Используйте роли (roles) для группировки задач по пользователям, группам и sudoers
- Для массового управления используйте `loop` с данными из `vars` или внешних источников
- Применяйте теги (`tags`) для выборочного выполнения задач безопасности

### Кросс-платформенные особенности
- Учитывайте различия в путях к `visudo` (`/usr/sbin/visudo` vs `/sbin/visudo`)
- Для разных ОС используйте соответствующие модули: `ansible.builtin.get_url` + `ansible.builtin.deb822_repository` (Debian/Ubuntu), `ansible.builtin.rpm_key` (RHEL/CentOS). Модуль `ansible.builtin.apt_key` устарел и удаляется в ansible-core 2.25.
- Проверяйте доступные оболочки через `/etc/shells` перед назначением `shell` пользователю
- Для ACL учитывайте поддержку файловой системы (ext4, XFS, Btrfs)

### SRE-specific практики
- **Air-gapped среды:** Предварительно загружайте коллекции `ansible.posix` и ключи на Control Node. Используйте `lookup('file', '/keys/...')` вместо внешних URL.
- **Mass deployment:** Используйте `serial` и `throttle` для защиты каталогов LDAP/SSSD от перегрузки при массовом создании пользователей.
- **Compliance:** Настраивайте `PASS_MAX_DAYS`, `PASS_MIN_DAYS`, `PASS_WARN_AGE` в `/etc/login.defs` через `ansible.builtin.lineinfile` с `create: yes`. Регулярно аудируйте UID 0 и пустые пароли через `getent`.
- **Blue-green cutover:** При ротации SSH-ключей добавляйте новые ключи с `exclusive: no`, верифицируйте доступ, затем удаляйте старые с `exclusive: yes`.
- **Become security:** Никогда не передавайте `ansible_become_password` в открытом виде. Используйте `vault_become_password` и `no_log: true`.
- **Immutable infrastructure:** Предпочитайте пересоздание контейнеров/инстансов вместо изменения пользователей на долгоживущих хостах. Используйте Ansible только для инициализации.

## Дополнительная информация

- **[Ansible Vault: управление секретами](../Vault/basics.md)** — безопасное хранение хешей и ключей.
- **[Рекомендации по безопасности Ansible](../ansible_security_best_practices.md)** — архитектурные паттерны защиты инфраструктуры.
- **[Управление привилегиями: sudo и sudoers](../../Linux/SystemAdministration/privilege_management.md)** — глубокая настройка прав в Linux.
