# Ansible: Модули управления секретами

## Определения

**Ansible Vault** — встроенная система шифрования файлов переменных и секретов на уровне репозитория. Использует AES-256-CTR с PBKDF2-HMAC-SHA256 (10 000 итераций) и требует мастер-пароль для дешифрования. Поддерживает форматы заголовков 1.1 (без метки) и 1.2 (с Vault ID).

**HashiCorp Vault** — on-prem система централизованного управления секретами с поддержкой динамической выдачи, ротации, контроля доступа и аудита. Поддерживает различные бэкенды: KV, PKI, Database, Transit, SSH.

**Модули управления секретами** — группа инструментов Ansible для интеграции с внешними системами хранения секретов (HashiCorp Vault, Ansible Vault), позволяющая получать, создавать и ротировать секреты непосредственно в плейбуках без жесткого прописывания их в коде или переменных.

**Lookup-плагин `community.hashi_vault.hashi_vault`** — механизм получения секретов из HashiCorp Vault на контрольном узле во время выполнения плейбука. Секреты не сохраняются в переменных Ansible и не передаются на управляемые узлы.

**Vault ID** — текстовая метка (например, `dev`, `prod`), связывающая зашифрованный файл с конкретным паролем или источником пароля. Поддерживается с ansible-core 2.4+.

**EncryptedString (ansible-core 2.19+)** — внутренний тип данных Ansible для автоматического отслеживания зашифрованных значений и предотвращения их случайного вывода в логи (Data Tagging).

**Community.hashi_vault** — коллекция Ansible, предоставляющая модули для интеграции с HashiCorp Vault: `hashi_vault` (получение секретов), `hashi_vault_login` (аутентификация), `hashi_vault_secret` (запись секретов).

## Версионирование и требования

| Компонент | Минимальная версия | Рекомендуемая версия |
| :--- | :--- | :--- |
| **ansible-core** | 2.15+ | 2.21.3 |
| **community.hashi_vault** | 2.0+ | Актуальная |
| **HashiCorp Vault** | 1.15+ | Актуальная LTS |
| **Python** (control node) | 3.9+ | 3.12+ |
| **hvac** | 1.0+ | Актуальная |

**Установка коллекции:**
```bash
ansible-galaxy collection install community.hashi_vault
```

**Установка зависимостей на контрольном узле:**
```bash
pip install hvac
```

**Проверка окружения:**
```bash
export VAULT_ADDR=https://vault.example.com:8200
export VAULT_TOKEN=$(vault login -method=userpass username=admin password=pass)
ansible-doc community.hashi_vault.hashi_vault
# → community.hashi_vault.hashi_vault – retrieve secrets from HashiCorp Vault
```

## Основные концепции

### Архитектура и принципы работы

Управление секретами в Ansible строится на двух уровнях:

1. **Ansible Vault** — шифрование файлов на уровне репозитория. Подходит для статических секретов, которые редко меняются. Секреты хранятся зашифрованными в Git, расшифровка происходит на контрольном узле во время выполнения плейбука.

2. **HashiCorp Vault** — динамическое получение секретов во время выполнения. Подходит для production сред, где требуется ротация, аудит и контроль доступа. Секреты хранятся в централизованном хранилище, Ansible получает их через модули `community.hashi_vault`.

**Жизненный цикл секрета:**
```
Создание → Шифрование/Хранение → Получение во время выполнения → Использование → Ротация
   ↑                                                                              |
   └──────────────────────────────────────────────────────────────────────────────┘
```

**Для DevOps:** Используйте Ansible Vault для статических секретов в Git (пароли БД, API-ключи), а HashiCorp Vault — для динамических секретов (учетные данные БД, сертификаты), которые требуют ротации.

**Для SRE:** Централизуйте все production-секреты в HashiCorp Vault. Ansible Vault используйте только для шифрования конфигурации при хранении в Git.

**Для Sysadmin:** На shared Control Node используйте `umask 0077` для автоматического ограничения прав на файлы паролей. Контролируйте `$TMPDIR` — временные файлы при работе с Vault создаются именно там.

### Модули HashiCorp Vault

Коллекция `community.hashi_vault` предоставляет три основных модуля:

1. **`community.hashi_vault.hashi_vault`**: Получение секретов из HashiCorp Vault через KV-бэкенд. Поддерживает `secret` (путь к секрету), `field` (поле в секрете), `url`, `auth_method` (token, userpass, ldap, kubernetes, approle), `token`, `username`, `password`, `role_id`, `secret_id`.

2. **`community.hashi_vault.hashi_vault_login`**: Аутентификация в Vault и получение токена. Поддерживает `url`, `auth_method`, `token`, `username`, `password`, `role` (для Kubernetes, JWT), `jwt`, `role_id`, `secret_id`.

3. **`community.hashi_vault.hashi_vault_secret`**: Запись секретов в Vault. Поддерживает `secret`, `data` (словарь данных), `url`, `auth_method`, `token`.

### Интеграция Ansible Vault и HashiCorp Vault

**Два подхода к управлению секретами:**
1. **Ansible Vault** — шифрование файлов на уровне репозитория. Подходит для статических секретов, которые редко меняются.
2. **HashiCorp Vault** — динамическое получение секретов во время выполнения. Подходит для production сред, где требуется ротация, аудит и контроль доступа.

**Гибридный подход (рекомендуется для production):**
- Ansible Vault для шифрования конфигурации в Git
- HashiCorp Vault для динамических секретов (учетные данные БД, сертификаты)
- Lookup-плагины для получения секретов из Vault во время выполнения

### Безопасные паттерны

- **Никогда не храните секреты в плейбуках или inventory** — используйте lookup-плагины или Ansible Vault.
- **Используйте `no_log: true`** для задач, обрабатывающих секреты.
- **Разделяйте уровни доступа** — разные сервисы получают разные секреты через политики Vault.
- **Ротируйте секреты регулярно** — используйте `hashi_vault_secret` для обновления без изменения плейбуков.
- **Используйте Vault ID с метками** — формат 1.2 заголовка позволяет мгновенно выбирать нужный пароль.
- **Храните файлы паролей с правами 600** — `chmod 600 .vault_pass*`.

## Практические сценарии

### Предварительные требования

- **Ansible (ansible-core)**: версия 2.15+ (рекомендуется 2.21.3). Проверка: `ansible --version | head -1`
- **Python** (control node): 3.12+ для ansible-core 2.20+
- **HashiCorp Vault**: 1.15+ LTS, доступный по сети с контрольного узла
- **Коллекция community.hashi_vault**: `ansible-galaxy collection install community.hashi_vault`
- **Права доступа**: файлы паролей должны иметь права `chmod 600`

### Сценарий 1: Шифрование переменных через Ansible Vault

```bash
# Создание зашифрованной строки с указанием Vault ID
ansible-vault encrypt_string 'SuperSecret123!' --name 'vault_db_password' --vault-id prod@.vault_pass_prod
```

```yaml
# group_vars/prod/vault.yml (зашифровано)
vault_db_password: !vault |
  $ANSIBLE_VAULT;1.2;AES256;prod
  386232666439356134303461343834366132366134...
```

```yaml
# Использование в плейбуке
- name: "Деплой приложения"
  hosts: app_servers
  vars_files:
    - group_vars/prod/vault.yml
  tasks:
    - name: "Настройка БД"
      ansible.builtin.template:
        src: app.config.j2
        dest: /etc/app/config.yml
        mode: "0600"
      no_log: yes
```

**Для Sysadmin:** Используйте `ansible-vault view` вместо `decrypt` для чтения секретов — `decrypt` оставляет открытый текст на диске.

### Сценарий 2: Получение секрета из HashiCorp Vault (token auth)

```yaml
- name: "Получение пароля БД из Vault"
  ansible.builtin.set_fact:
    db_password: "{{ lookup('community.hashi_vault.hashi_vault', 'secret=secret/data/db:password') }}"
  no_log: yes

- name: "Деплой конфигурации с секретом"
  ansible.builtin.template:
    src: app.config.j2
    dest: /etc/app/config.yml
    mode: "0600"
  no_log: yes
```

**Для SRE:** Используйте `no_log: true` для всех задач, работающих с секретами. Настройте алерт на появление секретов в логах Ansible.

### Сценарий 3: Аутентификация через AppRole

```yaml
- name: "Аутентификация в Vault через AppRole"
  community.hashi_vault.hashi_vault_login:
    url: "https://vault.example.com:8200"
    auth_method: approle
    role_id: "{{ vault_approle_role_id }}"
    secret_id: "{{ vault_approle_secret_id }}"
  register: vault_login

- name: "Получение секрета с использованием токена"
  community.hashi_vault.hashi_vault:
    url: "https://vault.example.com:8200"
    secret: "secret/data/app/config"
    field: "api_key"
    token: "{{ vault_login.token }}"
  no_log: yes
```

**Для DevOps:** AppRole — предпочтительный метод аутентификации для автоматизации. Храните `role_id` в открытом виде, а `secret_id` — в защищенном хранилище CI/CD.

### Сценарий 4: Запись секрета в Vault

```yaml
- name: "Запись нового пароля в Vault"
  community.hashi_vault.hashi_vault_secret:
    url: "https://vault.example.com:8200"
    secret: "secret/data/db"
    data:
      password: "{{ vault_new_db_password }}"
      username: "db_admin"
    auth_method: token
    token: "{{ vault_token }}"
  no_log: yes
```

### Сценарий 5: Аутентификация через Kubernetes Service Account

```yaml
- name: "Аутентификация в Vault через Kubernetes"
  community.hashi_vault.hashi_vault_login:
    url: "https://vault.example.com:8200"
    auth_method: kubernetes
    role: "app-role"
    jwt: "{{ lookup('file', '/var/run/secrets/kubernetes.io/serviceaccount/token') }}"
  register: vault_login

- name: "Получение секрета с использованием токена"
  community.hashi_vault.hashi_vault:
    url: "https://vault.example.com:8200"
    secret: "secret/data/app/config"
    field: "api_key"
    token: "{{ vault_login.token }}"
  no_log: yes
```

### Сценарий 6: Гибридный подход (Ansible Vault + HashiCorp Vault)

```yaml
- name: "Получение секрета из HashiCorp Vault"
  ansible.builtin.set_fact:
    db_password: "{{ lookup('community.hashi_vault.hashi_vault', 'secret=secret/data/db:password') }}"
  no_log: yes

- name: "Шифрование пароля для хранения в Git"
  ansible.builtin.command: ansible-vault encrypt_string "{{ db_password }}" --name 'vault_db_password' --vault-id prod@.vault_pass_prod
  changed_when: false
  no_log: yes
```

## Операции и команды

### Модули community.hashi_vault

| Модуль | Назначение | Ключевые параметры |
| :--- | :--- | :--- |
| `community.hashi_vault.hashi_vault` | Получение секретов из HashiCorp Vault | `secret`, `field`, `url`, `auth_method`, `token`, `username`, `password`, `role_id`, `secret_id` |
| `community.hashi_vault.hashi_vault_login` | Аутентификация в Vault и получение токена | `url`, `auth_method`, `token`, `username`, `password`, `role`, `jwt`, `role_id`, `secret_id` |
| `community.hashi_vault.hashi_vault_secret` | Запись секретов в Vault | `secret`, `data`, `url`, `auth_method`, `token` |

### Lookup-плагин

```yaml
# Получение секрета через lookup
db_password: "{{ lookup('community.hashi_vault.hashi_vault', 'secret=secret/data/db:password') }}"
```

### Ansible Vault CLI

Базовые команды для работы с Ansible Vault:

| Команда | Назначение |
| :--- | :--- |
| `ansible-vault create <file>` | Создание нового зашифрованного файла |
| `ansible-vault encrypt <file>` | Шифрование существующего файла |
| `ansible-vault decrypt <file>` | Расшифровка файла |
| `ansible-vault edit <file>` | Редактирование зашифрованного файла |
| `ansible-vault view <file>` | Просмотр содержимого без расшифровки на диск |
| `ansible-vault rekey <file>` | Смена пароля или метки Vault ID |
| `ansible-vault encrypt_string` | Шифрование отдельной строки |

> Полный справочник флагов и примеров см. в [Ansible Vault: Основы](../Vault/basics.md#операции-и-команды).

## Устранение неполадок

### Ошибка: `Decryption failed`

**Причина**: неверный пароль или файл зашифрован другим Vault ID.

```bash
# Проверка Vault ID в заголовке файла
head -1 group_vars/prod/vault.yml
# → $ANSIBLE_VAULT;1.2;AES256;prod

# Попытка расшифровки с указанием правильного Vault ID
ansible-vault view --vault-id prod@.vault_pass_prod group_vars/prod/vault.yml
```

### Ошибка: `Vault password not found for identity`

**Причина**: Vault ID не найден в `vault_identity_list` или файл пароля не существует.

```bash
# Проверка vault_identity_list в ansible.cfg
grep vault_identity_list ansible.cfg

# Проверка существования файлов паролей
ls -la .vault_pass_*
```

### Ошибка: `Incorrect password when decrypting`

**Причина**: файл пароля содержит завершающий перевод строки.

```bash
# Перезапись без перевода строки
printf '%s' 'MySecretPassword' > .vault_pass_prod
chmod 600 .vault_pass_prod
```

### Ошибка: `Permission denied` при доступе к Vault

**Причина**: недостаточно прав у токена или политика Vault denies доступ к пути.

```bash
# Проверка политик Vault
vault policy read app-policy

# Проверка прав токена
vault token lookup
```

### Ошибка: `HMAC verification failed`

**Причина**: файл изменён после шифрования, передан неверный пароль или файл перешифрован другим Vault ID.

```bash
# Восстановление файла из Git
git checkout -- group_vars/prod/vault.yml
```

## Рекомендации и оптимизация

### Безопасность

- **Длина мастер-пароля**: используйте пароли длиной не менее 20-25 символов с высокой энтропией. 10 000 итераций PBKDF2 компенсируются длиной пароля.
- **no_log: true**: добавляйте директиву ко всем задачам, работающим с секретами.
- **Vault ID с метками**: используйте формат 1.2 заголовка для всех новых проектов.
- **Права доступа**: `chmod 600` для файлов паролей, `chmod 700` для директорий с секретами.
- **Аудит**: настройте `ANSIBLE_LOG_PATH` и регулярно проверяйте логи на наличие секретов.

**Для Sysadmin:** Настройте `umask 0077` для автоматического ограничения прав на создаваемые файлы паролей. Используйте `ansible-vault view` вместо `decrypt` для чтения секретов на production-хостах.

**Для SRE:** Внедрите политику ротации мастер-паролей (раз в квартал). Настройте алерты на появление ключевых слов (`password`, `secret`, `token`, `key`) в логах Ansible.

**Для DevOps:** Добавьте `ansible-lint` с правилом `no-log-password` в CI/CD пайплайн. Используйте `pre-commit` хуки для проверки.

### Производительность

- **Формат 1.2 с Vault ID**: используйте метки для мгновенного выбора пароля без перебора.
- **vault_id_match = True**: включает строгий режим, исключающий случайное использование ключей не по назначению.
- **Кэширование фактов**: не используйте `cacheable: true` для секретных переменных.

### Эксплуатация

- **Ротация**: регулярно меняйте мастер-пароли через `ansible-vault rekey`.
- **Резервное копирование**: храните резервные копии файлов паролей в защищенном хранилище в течение 7 дней после ротации.
- **Инвентаризация**: ведите журнал всех Vault ID, сроков ротации и ответственных лиц.

## См. также

- **[Ansible Vault: Основы](../Vault/basics.md)** — архитектура шифрования, формат заголовков, CLI-команды.
- **[Ansible Vault: Лучшие практики](../Vault/best_practices.md)** — векторы утечек, `no_log`, `encrypt_string`, `pre-commit`.
- **[Ansible Vault: Несколько хранилищ](../Vault/multi_vault.md)** — Vault ID, `ansible.cfg`, CI/CD, миграция.

## Дополнительная информация

### Ограничения безопасности

- **PBKDF2 10 000 итераций**: по современным меркам (OWASP 2025 — от 600 000 итераций) считается низким показателем. Компенсируйте длиной мастер-пароля (20+ символов).
- **Метаданные в открытом виде**: Vault ID в заголовке файла (формат 1.2) хранится в открытом виде. Избегайте чувствительной информации в названиях меток.
- **Файлы паролей в аргументах процесса**: `--vault-password-file` виден через `ps -ef`. Используйте lookup-плагины или скрипты-источники.

### Граничные случаи

- **Формат 1.0** (`$ANSIBLE_VAULT;1.0;AES256`) читается, но при перезаписи автоматически конвертируется в 1.1. Шифровать в 1.0 нельзя.
- **Пустой секрет** отклоняется с `AnsibleVaultPasswordError` — пустой файл пароля приведёт к ошибке, а не к «пустым» зашифрованным данным.
- **Кроссплатформенность**: Vault-файлы совместимы между Linux, macOS и Windows (с совместимыми версиями Python и ansible-core).
