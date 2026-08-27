# Ansible Vault: Управление паролями

## Определения

- **Источник пароля (Password Source)**: Метод, с помощью которого Ansible получает ключ для расшифровки данных. Выбор метода зависит от требований к автоматизации и уровня безопасности.
- **Идентификатор хранилища (Vault ID)**: Метка (например, `dev`, `prod`), позволяющая связать зашифрованный файл с конкретным паролем или источником при использовании нескольких хранилищ (Multi-Vault).
- **Клиентский скрипт (Client Script)**: Исполняемый файл (Python, Bash), который Ansible запускает для динамического получения пароля из внешних систем управления секретами (HashiCorp Vault, AWS Secrets Manager, KeepassXC).
- **GPG-шифрование (GNU Privacy Guard)**: Протокол шифрования, используемый для защиты самих файлов паролей Vault. Позволяет хранить пароли в репозитории в зашифрованном виде, расшифровывая их «на лету» через скрипт.
- **OIDC (OpenID Connect)**: Современный стандарт аутентификации, позволяющий CI/CD-пайплайнам получать временные токены доступа к менеджерам секретов без использования статических паролей.
- **STDOUT (Standard Output)**: Стандартный поток вывода, куда клиентский скрипт должен выводить пароль для его считывания инструментом Ansible.

## Предварительные требования

Перед работой с источниками паролей Vault убедитесь в наличии следующих компонентов:

- **Ansible**: версия 2.4+ (для поддержки Vault ID), рекомендуется 2.12+ (ansible-core).
- **Права доступа**: файлы паролей должны быть доступны только владельцу:
  ```bash
  chmod 600 .vault_pass
  ls -la .vault_pass
  # → -rw------- 1 user user ... .vault_pass
  ```
- **Отсутствие прав OTHERS**: файлы с правами `644` или `777` вызовут ошибку `InsecureWorldReadablePermissions`.
- **PYTHONPATH**: для работы скриптов убедитесь, что Python доступен в PATH и установлены необходимые модули (`requests` для интеграции с внешними API).

## Основные концепции

### Иерархия и приоритеты поиска

Ansible ищет пароль в определенном порядке. Первый найденный источник считается приоритетным:

1. **Аргументы командной строки (CLI — Command Line Interface)**: Флаги `--vault-id`, `--vault-password-file` или `--ask-vault-pass`.
2. **Переменная окружения**: `ANSIBLE_VAULT_PASSWORD_FILE`. Указывает путь к файлу или скрипту.
3. **Конфигурационный файл**: Параметр `vault_password_file` или `vault_identity_list` в секции `[defaults]` файла `ansible.cfg`.

### Анализ безопасности источников

| Метод | Удобство | Безопасность | Рекомендация |
| :--- | :--- | :--- | :--- |
| **Интерактивный ввод** (`--ask-vault-pass`) | Низкое | Максимальная | Для ручного запуска на критических узлах. Секрет живет только в RAM. |
| **Локальный файл** (`.vault_pass`) | Высокое | Низкая | Только для локальной разработки. Риск случайного коммита в Git. |
| **Клиентский скрипт** | Среднее | Высокая | **Standard 2024+**. Интеграция с внешними SSoT (HashiCorp, AWS). |
| **GPG-скрипт** | Среднее | Высокая | Для командной работы без внешних менеджеров секретов. |

**Важное ограничение:** Ansible **не поддерживает** прямую передачу пароля через переменную окружения (например, `export ANSIBLE_VAULT_PASSWORD=...`) из соображений безопасности. Это предотвращает утечку пароля через список процессов (`ps aux`) или логи окружения CI. Переменная может указывать только на путь к источнику.

## Практические сценарии

### Сценарий 1: Интерактивный ввод и Vault ID

Самый безопасный способ для ручного запуска, так как секрет существует только в оперативной памяти (RAM — Random Access Memory).

```bash
# Запрос пароля для конкретной метки (Vault ID)
ansible-playbook site.yml --vault-id prod@prompt
# → Vault password (prod): (ввод пароля)
```

### Сценарий 2: Использование клиентских скриптов (Best Practice 2024-2025)

Это стандарт для профессиональной автоматизации. Скрипт может интегрироваться с любым менеджером секретов (HashiCorp Vault, AWS Secrets Manager, 1Password).

**Требования к скрипту:**
- Права на выполнение: `chmod +x script.sh`.
- Вывод в STDOUT: Только чистый пароль без лишних пробелов и логов.
- Обработка аргументов: При использовании `--vault-id`, Ansible передает этот идентификатор в скрипт как аргумент.

**Пример скрипта на Bash для AWS Secrets Manager (`vault-client.sh`):**
```bash
#!/bin/bash
# Ansible вызывает: script.sh --vault-id <label>
VAULT_ID=$2

if [ "$VAULT_ID" == "prod" ]; then
    # Получение из AWS с использованием IAM (Identity and Access Management) роли
    aws secretsmanager get-secret-value --secret-id "ansible/prod-pass" --query "SecretString" --output text
elif [ "$VAULT_ID" == "dev" ]; then
    echo "local_development_password"
fi
```

### Сценарий 3: Настройка в ansible.cfg для нескольких окружений

Вы можете задать список идентификаторов и соответствующих им источников (файлов или скриптов) глобально.

```ini
# ansible.cfg
[defaults]
# Формат: метка@путь_к_источнику
vault_identity_list = dev@.vault_pass_dev, prod@scripts/vault-client.sh
```

### Сценарий 4: Интеграция в CI/CD (GitLab/GitHub)

В автоматизированных пайплайнах (CI/CD — Continuous Integration / Continuous Delivery) пароль передается через временный файл или скрипт-прослойку, использующий защищенные переменные.

**Рекомендуемый метод (Variable Type: File):**
1. В GitLab CI создайте переменную `VAULT_PASS_FILE` типа **File**.
2. Используйте путь к ней напрямую:
```yaml
deploy:
  script:
    - chmod 600 "$VAULT_PASS_FILE"
    - ansible-playbook deploy.yml --vault-password-file "$VAULT_PASS_FILE"
```

### Сценарий 5: Интеграция с HashiCorp Vault через AppRole

AppRole — это основной метод аутентификации для машин и скриптов в HashiCorp Vault. Он позволяет безопасно получать пароли без использования личных токенов.

1. **Скрипт-обертка (`fetch_vault_pass.py`)**:
    ```python
    #!/usr/bin/env python3
    import os
    import requests
    import sys

    # Данные для аутентификации передаются через переменные окружения
    ROLE_ID = os.getenv("VAULT_ROLE_ID")
    SECRET_ID = os.getenv("VAULT_SECRET_ID")
    VAULT_ADDR = os.getenv("VAULT_ADDR", "https://vault.example.com:8200")

    def get_token():
        url = f"{VAULT_ADDR}/v1/auth/approle/login"
        payload = {"role_id": ROLE_ID, "secret_id": SECRET_ID}
        response = requests.post(url, json=payload)
        response.raise_for_status()
        return response.json()["auth"]["client_token"]

    def get_ansible_password(token, vault_id):
        # Путь к секрету зависит от метки (Vault ID)
        url = f"{VAULT_ADDR}/v1/secret/data/ansible/{vault_id}"
        headers = {"X-Vault-Token": token}
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        return response.json()["data"]["data"]["password"]

    if __name__ == "__main__":
        try:
            vault_id = sys.argv[2] if len(sys.argv) > 2 else "default"
            token = get_token()
            print(get_ansible_password(token, vault_id))
        except Exception as e:
            sys.exit(f"Error fetching password: {e}")
    ```

2. **Запуск в CI**:
    ```bash
    export VAULT_ROLE_ID="my-app-role-id"
    export VAULT_SECRET_ID="my-app-secret-id"
    ansible-playbook site.yml --vault-password-file ./fetch_vault_pass.py --vault-id prod
    ```

### Сценарий 6: Беспарольный доступ через OIDC (GitLab CI 17.0+)

Использование **ID Tokens** исключает хранение статических `ROLE_ID` и `SECRET_ID`. Раннер аутентифицируется в Vault по JWT-токену, выданному GitLab.

1. **Конфигурация `.gitlab-ci.yml`**:
    ```yaml
    deploy:
      id_tokens:
        VAULT_ID_TOKEN:
          aud: https://vault.example.com
      variables:
        VAULT_ADDR: "https://vault.example.com:8200"
      script:
        # Скрипт использует VAULT_ID_TOKEN для логина в Vault через jwt-метод
        - export ANSIBLE_VAULT_PASSWORD=$(./scripts/get_pass_via_oidc.sh)
        - ansible-playbook site.yml --vault-password-file <(echo "$ANSIBLE_VAULT_PASSWORD")
    ```

### Сценарий 7: Ротация секретов в Enterprise-средах

Для соблюдения политик комплаенса пароли мастер-ключей должны меняться регулярно.

1. **Автоматизированная перешифровка**:
    При смене пароля в HashiCorp Vault необходимо обновить все зашифрованные файлы в репозитории.
    ```bash
    # Смена пароля с использованием старого и нового ключа из разных источников
    ansible-vault rekey --vault-id prod@old_script.py --new-vault-id prod@new_script.py group_vars/prod/vault.yml
    ```

### Сценарий 8: Интеграция с GitHub Actions (OIDC)

Беспарольная аутентификация через OIDC (OpenID Connect) — рекомендуемый метод для GitHub Actions.

1. **Настройка Vault**:
    ```bash
    # Включение JWT-метода
    vault auth enable jwt

    # Настройка GitHub OIDC
    vault write auth/jwt/config \
      oidc_discovery_url="https://token.actions.githubusercontent.com" \
      bound_issuer="https://github.com/your-org"

    # Создание роли для GitHub Actions
    vault write auth/jwt/role/github-actions \
      role_providers="github" \
      bound_audiences="https://vault.example.com" \
      bound_subject="repo:your-org/your-repo:ref:refs/heads/main" \
      token_policies="ansible-read"
    ```

2. **Конфигурация `.github/workflows/deploy.yml`**:
    ```yaml
    jobs:
      deploy:
        permissions:
          id-token: write   # Для OIDC
          contents: read
        steps:
          - uses: actions/checkout@v4
          - name: Get Vault token via OIDC
            run: |
              OIDC_TOKEN=$(curl -H "Authorization: bearer $ACTIONS_ID_TOKEN_REQUEST_TOKEN" \
                "$ACTIONS_ID_TOKEN_REQUEST_URL&audience=https://vault.example.com" | jq -r '.value')
              VAULT_TOKEN=$(curl -s -X POST \
                -H "X-Vault-JWT-Signature: $OIDC_TOKEN" \
                "$VAULT_ADDR/v1/auth/jwt/login" | jq -r '.auth.client_token')
              echo "VAULT_TOKEN=$VAULT_TOKEN" >> $GITHUB_ENV
          - name: Run Playbook
            run: |
              ansible-playbook site.yml --vault-password-file <(echo "$VAULT_TOKEN")
    ```

### Сценарий 9: GPG-шифрование файла пароля

Позволяет хранить зашифрованный файл пароля в Git, расшифровывая его «на лету».

1. **Создание GPG-ключа** (если нет):
    ```bash
    gpg --full-generate-key    # RSA 4096, без пароля
    ```

2. **Шифрование файла пароля**:
    ```bash
    echo "MySecureVaultPass" > .vault_pass.txt
    gpg --encrypt --recipient your@email.com .vault_pass.txt
    # → .vault_pass.txt.gpg
    rm .vault_pass.txt  # Удалите открытый файл!
    ```

3. **Скрипт расшифровки (`vault-pass.sh`)**:
    ```bash
    #!/bin/bash
    gpg --quiet --decrypt .vault_pass.txt.gpg 2>/dev/null
    ```

4. **Использование**:
    ```bash
    chmod +x vault-pass.sh
    ansible-playbook site.yml --vault-password-file ./vault-pass.sh
    ```

5. **Преимущества**:
    - Открытый файл пароля никогда не хранится на диске.
    - `.vault_pass.txt.gpg` безопасен для коммита в Git.
    - Пароль доступен только пользователям, имеющим GPG-ключ.

### Сценарий 10: Интеграция с Docker Compose

Безопасная передача паролей Vault в контейнеризированные среды.

1. **Dockerfile** (для образа с Ansible):
    ```dockerfile
    FROM python:3.11-slim
    RUN pip install ansible-core requests
    WORKDIR /app
    COPY . /app
    CMD ["ansible-playbook", "site.yml"]
    ```

2. **docker-compose.yml** (с монтированием пароля через tmpfs):
    ```yaml
    services:
      ansible:
        build: .
        cap_add:
          - IPC_LOCK  # Предотвращает сброс в swap
        volumes:
          - type: tmpfs
            target: /run/secrets
            tmpfs:
              size: 1M
              noexec: true
        environment:
          ANSIBLE_VAULT_PASSWORD_FILE: /run/secrets/vault_pass
        secrets:
          - vault_pass

    secrets:
      vault_pass:
        file: ./.vault_pass  # Только для разработки!
    ```

3. **В Production**: используйте Docker Secrets или HashiCorp Vault напрямую, а не файлы.

### Сценарий 11: Встроенный lookup `pass` (Password Store)

Использование Unix-утилиты `pass` (https://www.passwordstore.org/) как источника паролей.

1. **Установка pass**:
    ```bash
    # macOS
    brew install pass

    # Debian/Ubuntu
    sudo apt install pass
    ```

2. **Инициализация и добавление пароля**:
    ```bash
    pass init <GPG_KEY_ID>
    pass insert ansible/vault/prod
    # → Enter password for ansible/vault/prod: (ввод пароля)
    ```

3. **Скрипт получения пароля (`vault-pass.sh`)**:
    ```bash
    #!/bin/bash
    pass ansible/vault/prod
    ```

4. **Использование**:
    ```bash
    chmod +x vault-pass.sh
    ansible-playbook site.yml --vault-password-file ./vault-pass.sh
    ```

### Сценарий 12: Интеграция с HashiCorp Vault через AppRole

Для Enterprise-сред с централизованным управлением секретами.

1. **Настройка Vault (однократно)**:
    ```bash
    vault auth enable approle
    vault write auth/approle/role/ansible \
      token_policies="ansible-read" \
      token_ttl=3600 \
      token_max_ttl=86400

    vault read auth/approle/role/ansible/role-id
    vault write -f auth/approle/role/ansible/secret-id
    ```

2. **Скрипт-обертка (`vault-pass.sh`)**:
    ```bash
    #!/bin/bash
    ROLE_ID="${VAULT_ROLE_ID:?VAULT_ROLE_ID not set}"
    SECRET_ID="${VAULT_SECRET_ID:?VAULT_SECRET_ID not set}"
    VAULT_ADDR="${VAULT_ADDR:-https://vault.example.com:8200}"

    TOKEN=$(curl -s -X POST "$VAULT_ADDR/v1/auth/approle/login" \
      -d "{\"role_id\":\"$ROLE_ID\",\"secret_id\":\"$SECRET_ID\"}" | jq -r '.auth.client_token')

    curl -s -H "X-Vault-Token: $TOKEN" \
      "$VAULT_ADDR/v1/secret/data/ansible/vault-password" | jq -r '.data.data.password'
    ```

3. **Использование**:
    ```bash
    export VAULT_ROLE_ID="your-role-id"
    export VAULT_SECRET_ID="your-secret-id"
    ansible-playbook site.yml --vault-password-file ./vault-pass.sh
    ```

### Сценарий 13: Скрипт для KeePassXC

Автоматическое извлечение пароля из локального хранилища KeePassXC.

1. **Требования**:
    - KeePassXC установлен и содержит запись с паролем Vault.
    - CLI `keepassxc-cli` доступен в PATH (входит в KeePassXC 2.7+).

2. **Скрипт (`vault-pass-keepass.sh`)**:
    ```bash
    #!/bin/bash
    KEEPASS_DB="${KEEPASS_DB:-~/ Keeys.kdbx}"
    KEEPASS_ENTRY="${KEEPASS_ENTRY:-Ansible/Vault/Prod}"
    KEEPASS_PASS="${KEEPASS_PASS:-}"

    if [ -z "$KEEPASS_PASS" ]; then
        read -sp "KeePassXC Master Password: " KEEPASS_PASS
        echo
    fi

    echo "$KEEPASS_PASS" | keepassxc-cli show -sa Password "$KEEPASS_DB" "$KEEPASS_ENTRY" 2>/dev/null
    ```

3. **Использование**:
    ```bash
    chmod +x vault-pass-keepass.sh
    # Спаролем
    KEEPASS_PASS="master" ansible-playbook site.yml --vault-password-file ./vault-pass-keepass.sh
    # Интерактивно
    ansible-playbook site.yml --vault-password-file ./vault-pass-keepass.sh
    ```

### Сценарий 14: Переменная окружения с дочерним процессом

Передача пароля через process substitution для отсутствия на диске.

```bash
# Вместо:
ansible-playbook site.yml --vault-password-file .vault_pass

# Безопасный вариант (пароль не попадает в fs):
ansible-playbook site.yml --vault-password-file <(echo "$VAULT_PASSWORD")
```

**Примечание**:尽管如此, пароль всё равно попадает в список процессов на время выполнения. Для максимальной безопасности используйте скрипты.

## Гигиена и безопасность в Production

- **Минимизация записи на диск**: В Production всегда предпочитайте передачу пароля через дескрипторы файлов (`<(echo $PASS)`) или клиентские скрипты, чтобы избежать появления расшифрованного пароля в файловой системе.
- **Маскирование в логах**: Убедитесь, что ваш CI-сервер маскирует переменные, которые используются для получения паролей Vault.
- **Принцип минимальных привилегий**: AppRole в HashiCorp Vault должен иметь доступ `read` только к тем путям, которые необходимы для конкретного плейбука.
- **Аудит**: Логируйте обращения к мастер-паролям в системе управления секретами для отслеживания несанкционированных запусков плейбуков.

## Устранение неполадок

### Ошибка: `InsecureWorldReadablePermissions`

**Причина**: файл пароля доступен для чтения группой или другими пользователями.

```bash
# Проверка прав
ls -la .vault_pass
# → -rw-r--r-- 1 user user ... .vault_pass  (НЕПРАВИЛЬНО)

# Исправление
chmod 600 .vault_pass
```

### Ошибка: `Vault password file not found`

**Причина**: файл пароля не существует по указанному пути или нет прав на чтение.

```bash
# Проверка существования файла
test -f .vault_pass && echo "OK" || echo "NOT FOUND"

# Проверка прав
test -r .vault_pass && echo "Readable" || echo "Not readable"
```

### Ошибка: `Decryption failed`

**Причина**: неверный пароль или Vault ID не совпадает с меткой в заголовке файла.

```bash
# Проверьте Vault ID в заголовке зашифрованного файла
head -1 group_vars/all/vault.yml
# → $ANSIBLE_VAULT;1.2;AES256;prod

# Убедитесь, что передаёте правильный Vault ID
ansible-playbook site.yml --vault-id prod@.vault_pass_prod
```

### Ошибка: `Vault password file 'script.sh' is not executable`

**Причина**: скрипт-прослойка не имеет права на выполнение.

```bash
chmod +x vault-pass.sh
```

### Ошибка: `No vault secret found for id 'dev'`

**Причина**: Vault ID `dev` не найден в `vault_identity_list`.

```bash
# Проверьте конфигурацию
grep vault_identity_list ansible.cfg

# Или передайте Vault ID явно
ansible-playbook site.yml --vault-id dev@.vault_pass_dev
```

### Ошибка: скрипт не возвращает пароль

**Причина**: скрипт выводит лишний текст (промпты, логи) в STDOUT.

```bash
# Проверка вывода скрипта
./vault-pass.sh
# → Должен вывести ТОЛЬКО пароль без лишних символов

# Отладка
bash -x ./vault-pass.sh  # Показать выполнение скрипта
```

### Ошибка: `Permission denied` при чтении GPG-файла

**Причина**: GPG-ключ не导入 в текущий keyring или нет доступа к агенту.

```bash
# Проверьте доступные ключи
gpg --list-keys

# Если ключ на смонтированном носителе
gpg --import /path/to/key.asc
```

## Граничные случаи и ограничения

- **Пароль не передаётся через ENV**: Ansible **не поддерживает** прямую передачу пароля через переменную окружения `ANSIBLE_VAULT_PASSWORD` — только через `ANSIBLE_VAULT_PASSWORD_FILE` (путь к источнику). Это предотвращает утечку через `ps aux`.
- **Кэширование фактов**: при использовании `cache_fact = True` расшифрованные значения могут попасть в кэш на диске.
- **Длина пароля**: рекомендуется минимум 16 символов; потолок зависит от алгоритма (AES-256).
- **Параллельные процессы**: при запуске нескольких плейбуков с общим скриптом убедитесь в потокобезопасности (lock файлы, уникальные ключи сессий).
- **Временные файлы**: при использовании process substitution `<()` пароль живёт в RAM и исчезает при завершении, но виден в `/proc/*/fd/`.

## Справочник переменных окружения

| Переменная | Описание | Пример |
|------------|----------|--------|
| `ANSIBLE_VAULT_PASSWORD_FILE` | Путь к файлу или скрипту с паролем | `export ANSIBLE_VAULT_PASSWORD_FILE=~/.vault_pass` |
| `ANSIBLE_VAULT_IDentities` | Список Vault ID через запятую | `export ANSIBLE_VAULT_IDentities="dev@~/.vault_dev,prod@~/.vault_prod"` |
| `VAULT_ADDR` | Адрес сервера HashiCorp Vault | `export VAULT_ADDR="https://vault.example.com:8200"` |
| `VAULT_TOKEN` | Токен аутентификации HashiCorp Vault | `export VAULT_TOKEN="s.xxxx"` |
| `VAULT_ROLE_ID` | Role ID для AppRole-аутентификации | `export VAULT_ROLE_ID="my-app-role"` |
| `VAULT_SECRET_ID` | Secret ID для AppRole-аутентификации | `export VAULT_SECRET_ID="my-secret-id"` |
| `VAULT_ID_TOKEN` | JWT-токен для OIDC-аутентификации | Автоматически в GitLab CI 17.0+ |

## Дополнительная информация

### Углубленные темы
- [Ansible Vault: Основы](./basics.md) — базовый синтаксис и версии заголовков.
- [Использование нескольких хранилищ (Multi-Vault)](./multi_vault.md) — детальная работа с Vault ID и метками.
- [Лучшие практики по безопасности](./best_practices.md) — директива `no_log`, OIDC и защита при выполнении.

### Технические детали
- [Практические примеры использования](./examples.md) — реальные сценарии применения в инфраструктуре.
- [Алгоритмы шифрования](./algorithms.md) — подробности AES-256 (Advanced Encryption Standard) и криптографических схем.

### Интеграция с HashiCorp Vault

**Что такое HashiCorp Vault:** Централизованное управление секретами с динамической выдачей, ротацией и контролем доступа. Поддерживает多种 бэкендов: KV, PKI, Database, AWS, Transit.

#### Два подхода к интеграции с Ansible

**Подход 1:** Получение секретов из Vault прямо в плейбуке через lookup-плагин.
**Подход 2:** Пароль vault-шифрования берётся из HashiCorp Vault ( vault_password_file → скрипт → Vault).

#### Lookup-плагин hashi_vault

Плагин `hashi_vault` позволяет получать секреты из Vault непосредственно в плейбуках.

**Установка:**
```bash
pip install hvac  # Python-клиент HashiCorp Vault
```

**Пример: vault lookup с AppRole auth:**
```yaml
---
- name: Получение секретов из HashiCorp Vault
  hosts: localhost
  connection: local
  gather_facts: false

  vars:
    vault_addr: "https://vault.example.com:8200"

  tasks:
    - name: Получение пароля БД через AppRole
      ansible.builtin.debug:
        msg: "Пароль: {{ lookup('hashi_vault', 'secret=secret/data/production/db:password auth_method=approle role_id={{ vault_role_id }} secret_id={{ vault_secret_id }}:{{ vault_addr }}') }}"

    - name: Получение API-токена
      ansible.builtin.debug:
        msg: "Токен: {{ lookup('hashi_vault', 'secret=secret/data/api:token auth_method=approle role_id={{ vault_role_id }} secret_id={{ vault_secret_id }}:{{ vault_addr }}') }}"
```

**Пример: vault lookup с Token auth:**
```yaml
    - name: Получение секрета через статический токен
      ansible.builtin.debug:
        msg: "{{ lookup('hashi_vault', 'secret=secret/data/ansible/vault_password token={{ vault_token }}:{{ vault_addr }}') }}"
```

**Пример: получение нескольких секретов:**
```yaml
    - name: Загрузка всех секретов для окружения
      ansible.builtin.set_fact:
        db_password: "{{ lookup('hashi_vault', 'secret=secret/data/prod/db:password token={{ vault_token }}:{{ vault_addr }}') }}"
        api_key: "{{ lookup('hashi_vault', 'secret=secret/data/prod/api:key token={{ vault_token }}:{{ vault_addr }}') }}"
        ssh_key: "{{ lookup('hashi_vault', 'secret=secret/data/prod/ssh:private_key token={{ vault_token }}:{{ vault_addr }}') }}"
```

#### Интеграция с CI/CD: получение vault-токена через OIDC/JWT

```yaml
# .gitlab-ci.yml
deploy:
  id_tokens:
    VAULT_ID_TOKEN:
      aud: https://vault.example.com
  script:
    - |
      OIDC_TOKEN=$(curl -H "Authorization: bearer $ACTIONS_ID_TOKEN_REQUEST_TOKEN" \
        "$ACTIONS_ID_TOKEN_REQUEST_URL&audience=https://vault.example.com" | jq -r '.value')
      VAULT_TOKEN=$(curl -s -X POST \
        -H "X-Vault-JWT-Signature: $OIDC_TOKEN" \
        "$VAULT_ADDR/v1/auth/jwt/login" | jq -r '.auth.client_token')
      echo "VAULT_TOKEN=$VAULT_TOKEN" >> $GITHUB_ENV
    - ansible-playbook site.yml --vault-password-file <(echo "$VAULT_TOKEN")
```

#### Безопасность

- **AppRole:** Рекомендуемый метод для машин. Ограничьте `token_policies` минимально необходимыми правами (`read` к конкретным путям).
- **TLS:** Всегда используйте HTTPS для подключения к Vault. Проверяйте сертификаты сервера.
- **Namespace isolation:** Используйте namespaces для изоляции секретов между командами/окружениями.
- **Audit logging:** Включите аудит Vault для отслеживания всех обращений к секретам.
- **Token TTL:** Устанавливайте короткий `token_ttl` (15-60 минут) и `token_max_ttl` для автоматической ротации.

**Пример ограничения policy:**
```hcl
# policy.hcl — только чтение секретов для Ansible
path "secret/data/ansible/*" {
  capabilities = ["read"]
}

path "auth/approle/login" {
  capabilities = ["update"]
}
```

### Интеграция с внешними системами
- [Интеграция Vault с Docker](../Vault/guides/vault_docker_integration.md) — контейнеризация и безопасность секретов.
- [HashiCorp Vault: Основы](../../Vault/overview.md) — архитектура и управление секретами.
