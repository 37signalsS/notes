# Ansible: Рекомендации по безопасности

## Определения

- **Безопасность Ansible** — комплексная стратегия защиты автоматизации, охватывающая узел управления (Control Node), каналы связи (SSH/WinRM), механизмы повышения прав (Become) и жизненный цикл секретов. Основана на принципах Zero Trust и эшелонированной защиты.
- **Zero Trust в автоматизации** — принцип «никогда не доверяй, всегда проверяй», при котором каждое действие плейбука должно быть явно авторизовано, а доступ к секретам предоставляется на основе проверяемой идентичности (Workload Identity), а не статических ключей.
- **Эшелонированная защита (Defense in Depth)** — многоуровневый подход к безопасности, где компрометация одного элемента (например, утечка пароля Vault) не приводит к полному захвату инфраструктуры благодаря дополнительным барьерам (RBAC, сетевая сегментация, аудит).
- **Execution Environments (EE)** — стандартизированные контейнерные среды исполнения Ansible (**[подробнее](./ansible-execution-environments.md)**), обеспечивающие изоляцию зависимостей и гарантирующие, что автоматизация выполняется в доверенном и неизменяемом окружении.
- **FIPS 140-2/3 (Federal Information Processing Standards)** — стандарты криптографической безопасности, обязательные для государственных и финансовых организаций в США. Определяют требования к модулям шифрования, хэширования и аутентификации. В контексте Ansible требуют использования сертифицированных криптографических модулей на ОС узла управления.
- **EncryptedString (Core 2.19+)** — внутренний тип данных в Ansible, автоматически помечающий секреты для предотвращения их случайного вывода в логи, консоль или отчеты. При использовании переменные с этим типом не отображаются в `--diff` и `--verbose` без явного запроса.
- **Ansible Vault** — встроенный механизм шифрования переменных и файлов с использованием AES-256. Поддерживает несколько ключей шифрования (Vault ID) для разделения секретов по средам (dev/staging/prod).
- **HashiCorp Vault** — внешний менеджер секретов с динамической выдачей учетных данных, поддержкой OIDC/AppRole аутентификации и автоматической ротацией. Интегрируется с Ansible через коллекцию `community.hashi_vault`.
- **AppRole** — метод аутентификации в HashiCorp Vault для машин и скриптов, использующий пару `RoleID` и `SecretID`. Подходит для CI/CD-пайплайнов, где OIDC недоступен.
- **SOPS (Secrets OPerationS)** — инструмент для шифрования только значений в YAML/JSON файлах, поддерживающий PGP и внешние KMS. Отличается от Ansible Vault тем, что сохраняет читаемость ключей YAML.
- **Supply Chain Security** — практики защиты цепочки поставок ПО: проверка подписей, контроль версий зависимостей, аудит использованных компонентов. В контексте Ansible — проверка GPG-подписей коллекций и ролей.

## Основные концепции

### Предварительные требования

Для implementation рекомендаций из данного руководства необходимы следующие компоненты:

| Компонент | Минимальная версия | Назначение |
| :--- | :--- | :--- |
| **ansible-core** | 2.21+ | Ядро Ansible (рекомендуется 2.21+) |
| **ansible-lint** | 26.x+ | Статический анализ и профиль `security` |
| **Python** | 3.9+ | Совместимость с ansible-core (3.12+ рекомендуется) |
| **GPG** | 2.2+ | Шифрование файлов паролей (опционально) |
| **gitleaks** | 8.x+ | Обнаружение секретов в Git-истории |
| **pre-commit** | 3.0+ | Автоматическая проверка перед коммитом |
| **SOPS** | 3.7+ | Шифрование значений в YAML (опционально) |

**Проверка окружения:**
```bash
ansible --version | head -1
# → ansible [core 2.21.x]

ansible-lint --version
# → ansible-lint 26.x.x

gitleaks version
# → v8.18.x

pre-commit --version
# → pre-commit 3.x.x
```

### Защита узла управления (Control Node)

Узел управления — это «мозг» инфраструктуры. Его защита является критическим приоритетом.

- **Изоляция среды:** Используйте Execution Environments (контейнеры) для запуска Ansible. Это предотвращает загрязнение хостовой ОС и позволяет ограничить права процесса автоматизации через возможности OCI-рантаймов.
- **FIPS Compliance:** В государственных или финансовых организациях включайте поддержку FIPS 140-2/3 на уровне ОС узла управления для использования только сертифицированных криптографических модулей.
- **Защита конфигурации:** Убедитесь, что файл `ansible.cfg` защищен от записи (права `0644` или `0600`), чтобы предотвратить подмену путей к библиотекам или вредоносные callback-плагины.
- **Защита SSH-ключей:** Используйте парольные фразы (passphrases) и SSH-агенты. Рассмотрите использование аппаратных токенов (FIDO2/YubiKey) для доступа администраторов к Control Node.
- **Минимизация прав:** Control Node не должен иметь прямого доступа к production-системам. Используйте jump-hosts и промежуточные узлы для доступа к целевым серверам.

### Стратегия повышения привилегий (Become)

Ansible требует прав суперпользователя для большинства задач (установка пакетов, конфигурация сервисов).

- **Принцип наименьших привилегий (PoLP):** Используйте директиву `become: true` только для конкретных задач или блоков, а не для всего плейбука.
- **Понижение привилегий (`become_user`):** Всегда переключайтесь на специализированных пользователей (например, `postgres`, `www-data`) вместо `root`, если задача это позволяет.
- **Безопасный Sudoers:** Избегайте использования `NOPASSWD: ALL` для всех пользователей. Если возможно, ограничивайте `sudo` только необходимым пользователем автоматизации и блокируйте ему прямой вход по паролю.
- **Мягкое повышение прав:** Для сложных окружений используйте `become_flags` для передачи специфических параметров (например, сохранение переменных окружения через `-H` или `-E`).
- **Become на сетевом оборудовании:** Для сетевых устройств (Cisco, Juniper) используйте `become_method: enable` вместо `sudo` и храните пароль `enable` в Vault.

**Пример конфигурации Become:**
```yaml
# Безопасная конфигурация become для production
- name: Установка пакетов
  ansible.builtin.apt:
    name: nginx
    state: present
  become: true
  become_user: root
  become_method: sudo
  become_flags: '-H -S'
  # -H: установить HOME из целевого пользователя
  # -S: читать пароль из stdin (без отображения в логах)
```

**Пример для сетевого оборудования:**
```yaml
- name: Конфигурация Cisco IOS
  hosts: cisco_routers
  gather_facts: false
  vars:
    ansible_network_os: cisco.ios.ios
    ansible_become: true
    ansible_become_method: enable
    ansible_become_password: "{{ vault_enable_password }}"  # Хранить в Vault
  tasks:
    - name: Проверка версии IOS
      cisco.ios.ios_command:
        commands:
          - show version
```

### Безопасность SSH и соединений

- **Отключение парольной аутентификации:** Используйте только SSH-ключи.
- **SSH Hardening:** Настройте `sshd_config` на управляемых узлах (запрет `RootLogin`, ограничение `AllowUsers`).
- **Host Key Checking:** Не отключайте проверку ключей хоста (`host_key_checking = False` в `ansible.cfg`) в production-средах, чтобы избежать атак Man-in-the-Middle.
- **SSH Agent Forwarding:** Избегайте `ForwardAgent yes` на Control Node. Если необходимо пересылать агент, используйте ProxyJump через jump-host.
- **Algorithms:** Используйте современные алгоритмы: `ed25519` для ключей, `aes256-gcm@openssh.com` или `chacha20-poly1305@openssh.com` для шифрования. Отключите устаревшие `diffie-hellman-group1-sha1`, `ssh-rsa`.

**Пример hardening SSH в ansible.cfg:**
```ini
[ssh_connection]
# Использование современных алгоритмов
ssh_args = -o ControlMaster=auto -o ControlPersist=60s -o ServerAliveInterval=30
# При подключении к новым хостам — проверка ключей
# host_key_checking = True  # Не отключайте в production!
```

### Управление секретами и защита логов

Никогда не храните пароли, токены или ключи API в открытом виде.

- **Ansible Vault:** Простой и эффективный способ для GitOps. Используйте **Vault ID** для разделения ключей разных сред (dev/prod). Подробнее — в **[Ansible Vault: Лучшие практики](./Vault/best_practices.md)**.
- **Директива `no_log: true` (Критично!):** Всегда добавляйте `no_log: true` к задачам, передающим секреты. **Внимание:** Режим `ansible-playbook --diff` может вывести содержимое секретов, если они записываются в файлы. Используйте `diff: false` в таких задачах.
- **EncryptedString (Core 2.19+):** Используйте этот тип для автоматической маскировки секретов в логах и отчетах. Переменные с этим типом не отображаются в `--diff` без явного запроса.
- **Динамические секреты (2026 Best Practice):** Интегрируйтесь с внешними менеджерами секретов (HashiCorp Vault) через OIDC-токены или AppRole. Это исключает необходимость хранения мастер-паролей на Control Node.
- **Lookup-плагины:** Используйте `community.hashi_vault.vault_kv2_get` для получения секретов «на лету» без их сохранения на диске.
- **SOPS:** Для проектов, где nécessaireен pitsчтение YAML-диффов, используйте SOPS вместо Ansible Vault — он шифрует только значения, сохраняя читаемость ключей.

**Пример EncryptedString:**
```yaml
---
- name: Демонстрация EncryptedString
  hosts: localhost
  gather_facts: false
  vars:
    db_password: !vault |
      $ANSIBLE_VAULT;1.1;AES256
      61626364656667686970...
    api_key: !vault |
      $ANSIBLE_VAULT;1.1;AES256
      61626364656667686970...
  tasks:
    - name: Создание конфигурации
      ansible.builtin.template:
        src: config.j2
        dest: /etc/app/config.yml
        mode: '0400'
      no_log: true  # Необходимо даже с EncryptedString при записи в файл
```

### Безопасность цепочки поставок (Supply Chain Security)

Автоматизация часто зависит от внешних ролей и коллекций.

- **Проверка подписей:** Начиная с Ansible 2.13+, используйте `ansible-galaxy collection verify` для проверки GPG-подписей установленных коллекций.
- **Локальное зеркалирование:** В критических инфраструктурах используйте частный **Ansible Automation Hub** или зеркало Galaxy для изоляции от внешних изменений.
- **Pinning версий:** Всегда фиксируйте версии коллекций и ролей в `requirements.yml`. Использование `version: latest` — высокий риск безопасности.
- **Линтинг:** Обязательно используйте `ansible-lint` с включенными профилями безопасности (`security`).
- **pre-commit хуки:** Настройте автоматическую проверку перед каждым коммитом для блокировки секретов и ошибок.

**Пример requirements.yml с фиксацией версий:**
```yaml
---
collections:
  - name: ansible.posix
    version: ">=1.5.0,<2.0.0"  # Диапазон версий (не latest!)
  - name: community.general
    version: ">=8.0.0"
  - name: community.hashi_vault
    version: ">=4.0.0"
  - name: devsec.hardening
    version: ">=8.0.0"

roles:
  - name: geerlingguy.docker
    version: ">=8.0.0"  # Актуальная версия!
```

**Пример .pre-commit-config.yaml:**
```yaml
repos:
  - repo: https://github.com/gitleaks/gitleaks
    rev: v8.18.0
    hooks:
      - id: gitleaks
  - repo: https://github.com/ansible/ansible-lint
    rev: v24.2.0
    hooks:
      - id: ansible-lint
        args: ['--profile', 'security']
```

### Аудит и логирование

- **Централизованный аудит:** Используйте callback-плагины (`community.general.splunk`, `community.general.logstash`) для отправки данных о выполнении плейбуков в SIEM/ELK.
- **Аудит конфигураций:** Периодически запускайте плейбуки в режиме `check_mode` для обнаружения несанкционированных изменений (Drift Detection).
- **Защита логов на Control Node:** Ограничивайте права доступа к `ansible.log` (права `0600`).
- **Версионирование:** Храните все плейбуки в Git. Каждое изменение должно проходить через Pull Request с ревью.
- **Интеграция с SIEM:** Настройте пересылку логов Ansible в централизованную систему мониторинга для корреляции событий.

**Пример callback-плагина для Splunk:**
```ini
# ansible.cfg
[defaults]
callback_whitelist = splunk
callbacks_enabled = ansible.builtin.timer, ansible.builtin.profile_tasks

# Конфигурация Splunk
[callback_splunk]
url = https://splunk.example.com:8088
token = "{{ vault_splunk_token }}"
```

## Практические сценарии

### 1. Настройка выделенного пользователя (Bootstrap)

Для безопасного управления создается пользователь (например, `ansible-deployer`), который будет использоваться только автоматизацией.

```yaml
---
- name: Настройка выделенного пользователя Ansible
  hosts: all
  become: true
  vars:
    ansible_worker_name: ansible-deployer
    sudo_group: "{{ 'wheel' if ansible_facts['os_family'] == 'RedHat' else 'sudo' }}"

  tasks:
    - name: Создать системную группу
      ansible.builtin.group:
        name: "{{ sudo_group }}"
        state: present

    - name: Создать пользователя для автоматизации
      ansible.builtin.user:
        name: "{{ ansible_worker_name }}"
        shell: /bin/bash
        groups: "{{ sudo_group }}"
        append: true
        state: present

    - name: Установить SSH-ключ (публичный)
      ansible.posix.authorized_key:
        user: "{{ ansible_worker_name }}"
        state: present
        key: "{{ lookup('file', '~/.ssh/id_rsa.pub') }}"

    - name: Настроить беспарольный sudo (виртуальный файл)
      ansible.builtin.copy:
        dest: "/etc/sudoers.d/90-ansible-worker"
        content: "{{ ansible_worker_name }} ALL=(ALL) NOPASSWD: ALL"
        mode: '0440'
        # %s заменяется на временный файл. visudo гарантирует, что файл не сломает sudo
        validate: /usr/sbin/visudo -csf %s

    - name: Ограничение SSH для пользователя
      ansible.builtin.lineinfile:
        path: /etc/ssh/sshd_config
        line: "AllowUsers {{ ansible_worker_name }}"
        state: present
      notify: restart sshd

  handlers:
    - name: restart sshd
      ansible.builtin.service:
        name: sshd
        state: restarted
# → target_host | CHANGED => { "changed": true, "dest": "/etc/sudoers.d/90-ansible-worker" }
```

### 2. Использование Vault для защиты переменных

Шифрование файла с паролями баз данных:
```bash
# Шифрование существующего файла
ansible-vault encrypt group_vars/db_servers/vault.yml
# → Encryption successful

# Создание зашифрованного файла с нуля
ansible-vault create group_vars/prod/secrets.yml
# → Откроется редактор для ввода содержимого

# Просмотр зашифрованного файла
ansible-vault view group_vars/prod/secrets.yml

# Ротация ключа шифрования
ansible-vault rekey group_vars/prod/secrets.yml
# → Vault password: (текущий пароль)
# → New Vault password: (новый пароль)
# → Rekey successful

# Дешифрование (при необходимости)
ansible-vault decrypt group_vars/prod/secrets.yml
```

**Использование Vault ID для разделения сред:**
```bash
# Создание файлов для разных сред
ansible-vault create --vault-id dev@prompt group_vars/dev/secrets.yml
ansible-vault create --vault-id prod@.vault_pass_prod group_vars/prod/secrets.yml

# Запуск с разными Vault ID
ansible-playbook site.yml \
  --vault-id dev@prompt \
  --vault-id prod@.vault_pass_prod
```

Внутри плейбука переменные используются прозрачно, если при запуске указан пароль:
```bash
ansible-playbook site.yml --ask-vault-pass
# → Vault password: (запрос пароля)

# Альтернатива: файл с паролем
ansible-playbook site.yml --vault-password-file .vault_pass
```

### 3. Включение логирования в файл

Настройка `ansible.cfg` для локального аудита:
```ini
[defaults]
log_path = /var/log/ansible.log
callbacks_enabled = ansible.builtin.timer, ansible.builtin.profile_tasks

# Защита логов
# chmod 600 /var/log/ansible.log
```

### 4. Динамическое получение секретов из HashiCorp Vault

Использование lookup-плагина для исключения хранения статических секретов в коде.

```yaml
---
- name: Деплой приложения с динамическими секретами
  hosts: app_servers
  vars:
    # Адрес Vault берется из переменной окружения VAULT_ADDR
    # path указывается относительно engine_mount_point, без сегмента /data/
    db_password: "{{ lookup('community.hashi_vault.vault_kv2_get', 'db/prod').secret.password }}"

  tasks:
    - name: Конфигурация приложения
      ansible.builtin.template:
        src: config.j2
        dest: /etc/app/config.json
        mode: '0400'
      no_log: true # Предотвращает утечку db_password при рендеринге в логи
```

**Интеграция с AppRole (для CI/CD):**
```yaml
---
- name: Получение секретов через AppRole
  hosts: localhost
  gather_facts: false
  vars:
    vault_addr: "https://vault.example.com:8200"
    role_id: "{{ vault_role_id }}"
    secret_id: "{{ vault_secret_id }}"
  tasks:
    - name: Аутентификация через AppRole
      community.hashi_vault.vault_login:
        method: approle
        role_id: "{{ role_id }}"
        secret_id: "{{ secret_id }}"
        url: "{{ vault_addr }}"
      register: vault_login
      no_log: true

    - name: Получение секрета
      community.hashi_vault.vault_kv2_get:
        path: db/prod
        engine_mount_point: secret
        url: "{{ vault_addr }}"
        auth_method_token: "{{ vault_login.token }}"
      register: db_secret
      no_log: true

    - name: Использование секрета
      ansible.builtin.debug:
        msg: "DB Host: {{ db_secret.secret.data.host }}"
      # Пароль НЕ выводится благодаря no_log в предыдущей задаче
```

### 5. Безопасное управление сетевым оборудованием

```yaml
---
- name: Безопасная конфигурация Cisco IOS
  hosts: cisco_switches
  gather_facts: false
  vars:
    ansible_network_os: cisco.ios.ios
    ansible_become: true
    ansible_become_method: enable
    ansible_become_password: "{{ vault_enable_password }}"
    ansible_connection: local  # Или paramiko

  tasks:
    - name: Backup текущей конфигурации
      cisco.ios.ios_config:
        backup: true
        backup_options:
          dir_path: /backups/cisco
          filename: "{{ inventory_hostname }}_{{ ansible_date_time.iso8601_basic_short }}.cfg"
      register: backup_result
      no_log: true  # Включает sensitive данные в выводе

    - name: Применение ACL
      cisco.ios.ios_acls:
        config:
          - afi: ipv4
            acls:
              - name: RESTRICT_MANAGEMENT
                aces:
                  - sequence: 10
                    grant: deny
                    protocol_options:
                      tcp:
                        syn: true
                    source:
                      host: 10.0.0.0/8
                    destination:
                      host: 192.168.1.0/24
                      port_protocol:
                        eq: 22
                  - sequence: 20
                    grant: permit
                    protocol_options:
                      tcp:
                        syn: true
                    source:
                      host: 172.16.0.0/16
                    destination:
                      host: 192.168.1.0/24
        state: merged
      register: acl_result

    - name: Верификация конфигурации
      cisco.ios.ios_command:
        commands:
          - show access-lists RESTRICT_MANAGEMENT
      register: acl_verify

    - name: Проверка примененных правил
      ansible.builtin.assert:
        that:
          - "'permit' in acl_verify.stdout[0]"
          - "'deny' in acl_verify.stdout[0]"
        fail_msg: "ACL не применена корректно"
        success_msg: "ACL применена успешно"
```

### 6. Безопасное управление пользователями Linux

```yaml
---
- name: Централизованное управление пользователями
  hosts: all
  become: true
  vars:
    # Список пользователей из зашифрованного файла
    users: "{{ vault_system_users }}"

  tasks:
    - name: Создание пользователей из Vault
      ansible.builtin.user:
        name: "{{ item.name }}"
        groups: "{{ item.groups | default(omit) }}"
        shell: "{{ item.shell | default('/bin/bash') }}"
        password: "{{ item.password_hash }}"
        state: present
      loop: "{{ users }}"
      no_log: true  # КРИТИЧНО: хэши паролей не должны попадать в логи

    - name: Настройка SSH-ключей
      ansible.posix.authorized_key:
        user: "{{ item.name }}"
        key: "{{ item.ssh_key }}"
        state: present
      loop: "{{ users }}"
      no_log: true

    - name: Блокировка неиспользуемых аккаунтов
      ansible.builtin.user:
        name: "{{ item }}"
        password_lock: true
      loop:
        - guest
        - test
        - admin
      when: item not in users | map(attribute='name') | list
```

### 7. Интеграция с CI/CD: GitHub Actions

```yaml
# .github/workflows/ansible-lint.yml
name: Ansible Security Lint
on:
  push:
    branches: [main, develop]
  pull_request:
    branches: [main]

jobs:
  ansible-lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install dependencies
        run: |
          pip install ansible-lint ansible-core gitleaks

      - name: Gitleaks scan
        run: gitleaks detect --source . --verbose

      - name: Ansible Lint
        run: |
          ansible-lint playbooks/ roles/ --profile security
        env:
          ANSIBLE_FORCE_COLOR: '1'

      - name: Ansible Syntax Check
        run: |
          for pb in playbooks/*.yml; do
            ansible-playbook "$pb" --syntax-check
          done
```

### 8. Полная настройка security-профиля ansible-lint

```bash
# Создание .ansible-lint с security-профилем
cat > .ansible-lint << 'EOF'
---
profile: security

# Дополнительные правила безопасности
enable_list:
  - yaml[line-length]
  - name[template]

# Игнорирование (только для тестов!)
skip_list:
  - yaml[truthy]

# Максимальная длина строки
yaml:
  line-length:
    max: 120
    allow-non-breakable-words: true

# Правила для vault
rules:
  no-log-password:
    # Автоматически находит задачи с password/secret/token без no_log
    active: true
EOF

# Запуск проверки
ansible-lint playbooks/ roles/
# → 0 issues found (или список нарушений)
```

## Устранение типичных ошибок

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `[no-log-password]` | Задача с переменной `password`/`secret`/`token` без `no_log: true` | Добавьте `no_log: true` к задаче |
| `Vault password not set` | Не указан пароль Vault при запуске | `--ask-vault-pass` или `--vault-password-file` |
| `ERROR! A vault password is required` | В `ansible.cfg` не настроен `vault_password_file` | Укажите путь к файлу с паролем или используйте `--ask-vault-pass` |
| `Host key verification failed` | Отключена проверка ключей хоста | Не используйте `host_key_checking = False` в production |
| `Permission denied (publickey)` | Неверный SSH-ключ или права на файл | Проверьте `~/.ssh/authorized_key` и права `0600` |
| `sudo: a password is required` | `become_pass` не указан или Vault не расшифрован | Укажите `become_password` в vault-файле |
| `ansible-lint: no-log-password` | Нет `no_log` в задачах с секретами | Используйте `--profile security` для автоматического поиска |
| `gitleaks: detected secret` | Секрет зашифрован или найден в истории Git | Используйте `git filter-branch` или `BFG Repo-Cleaner` |
| `Collection signature verification failed` | Коллекция повреждена или подменена | Переустановите: `ansible-galaxy collection install --force` |
| `FIPS mode: algorithm not supported` | Используется не-FIPS алгоритм | Включите FIPS mode на ОС или смените алгоритм |

**Диагностика:**
```bash
# Проверка наличия секретов в Git-истории
gitleaks detect --source . --verbose

# Проверка ansible-lint с security-профилем
ansible-lint --profile security playbooks/

# Проверка зашифрованных файлов
ansible-vault view group_vars/prod/secrets.yml

# Проверка SSH-подключения
ansible all -m ping -vvv

# Проверка прав на файлы
ls -la ~/.ssh/
ls -la /var/log/ansible.log
```

## Контрольный список: лучшие практики

- [ ] **Control Node:** Изолирована среда (EE), защищен `ansible.cfg` (0600), SSH-ключи с passphrase
- [ ] **Become:** Используется `become: true` только для конкретных задач, `become_user` для понижения привилегий
- [ ] **SSH:** Отключена парольная аутентификация, включена проверка ключей хоста, современные алгоритмы
- [ ] **Vault:** Секреты зашифрованы, Vault ID для разделения сред, `vault_password_file` настроен
- [ ] **no_log:** Все задачи с секретами имеют `no_log: true`, `diff: false` для файловых операций
- [ ] **EncryptedString:** Используется для переменных с секретами (Core 2.19+)
- [ ] **Supply Chain:** Версии коллекций зафиксированы в `requirements.yml`, GPG-подписи проверены
- [ ] **Linting:** `ansible-lint --profile security` проходит без ошибок
- [ ] **pre-commit:** Настроены хуки gitleaks и ansible-lint
- [ ] **Аудит:** Логи защищены (0600), callback-плагины настроены, Git-хранилище для плейбуков
- [ ] **Ротация:** Периодическая ротация ключей Vault, паролей SSH, API-токенов
- [ ] **Тестирование:** Плейбуки проверяются через `--check --diff` перед продакшеном

## Дополнительная информация

### Смотрите также

- **[Ansible: OS Hardening и комплаенс](./ansible-os-hardening.md)** — использование OpenSCAP, DevSec и CIS ролей для защиты целевых систем.
- **[Ansible Vault: Лучшие практики](./Vault/best_practices.md)** — глубокое погружение в управление секретами и шифрование.
- **[Антипаттерны Ansible](./ansible_bad_practices.md)** — архитектурные ошибки, ведущие к снижению безопасности (например, глобальный `become`).
