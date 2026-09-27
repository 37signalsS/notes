# Ansible Vault: Управление паролями

## Определения

- **Источник пароля (Password Source)**: Метод, с помощью которого Ansible получает ключ для расшифровки данных. Выбор метода зависит от требований к автоматизации и уровня безопасности.
- **Идентификатор хранилища (Vault ID)**: Метка (например, `dev`, `prod`), позволяющая связать зашифрованный файл с конкретным паролем или источником при использовании нескольких хранилищ (Multi-Vault).
- **Клиентский скрипт (Client Script)**: Исполняемый файл (Python, Bash), который Ansible запускает для динамического получения пароля из внешних систем управления секретами (HashiCorp Vault, KeePassXC, `pass`).
- **GPG-шифрование (GNU Privacy Guard)**: Протокол шифрования, используемый для защиты самих файлов паролей Vault. Позволяет хранить пароли в репозитории в зашифрованном виде, расшифровывая их «на лету» через скрипт.
- **pass (Password Store)**: Unix-утилита для хранения паролей в зашифрованном виде в файловой системе с использованием GPG.
- **KeePassXC**: Менеджер паролей с CLI-интерфейсом (`keepassxc-cli`), позволяющий извлекать секреты программно.
- **STDOUT (Standard Output)**: Стандартный поток вывода, куда клиентский скрипт должен выводить пароль для его считывания инструментом Ansible.

## Основные концепции

### Предварительные требования

Перед работой с источниками паролей Vault убедитесь в наличии следующих компонентов:

- **Ansible (ansible-core)**: версия 2.4+ (для поддержки Vault ID), рекомендуется 2.20+.
- **Права доступа**: файлы паролей должны быть доступны только владельцу:
  ```bash
  chmod 600 .vault_pass
  ls -la .vault_pass
  # → -rw------- 1 user user ... .vault_pass
  ```
- **Отсутствие прав OTHERS**: файлы с правами `644` или `777` вызовут ошибку `InsecureWorldReadablePermissions`.
- **Python**: 3.8+ (совместимость с ansible-core 2.20+).
- **PYTHONPATH**: для работы скриптов убедитесь, что Python доступен в PATH и установлены необходимые модули (`requests` для интеграции с внешними API, `jq` для обработки JSON).

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
| **Клиентский скрипт** | Среднее | Высокая | Стандарт для автоматизации. Интеграция с on-prem SSoT (HashiCorp Vault, KeePassXC). |
| **GPG-скрипт** | Среднее | Высокая | Для командной работы без внешних менеджеров секретов. |
| **pass** | Среднее | Высокая | Для индивидуальной работы с секретами в Git-репозитории. |

**Важное ограничение:** Ansible **не поддерживает** прямую передачу пароля через переменную окружения (например, `export ANSIBLE_VAULT_PASSWORD=...`) из соображений безопасности. Это предотвращает утечку пароля через список процессов (`ps aux`) или логи окружения CI. Переменная может указывать только на путь к источнику.

### Контракт STDOUT для скриптов

Клиентский скрипт должен удовлетворять строгим требованиям к выводу:

- **Только пароль**: скрипт выводит в STDOUT ровно одну строку — пароль, без пробелов, кавычек, логов или приглашений.
- **Нет интерактива**: скрипт не должен запрашивать ввод пользователя; используйте заранее настроенные переменные окружения или параметры.
- **Выходной код**: при ошибке скрипт возвращает ненулевой код (`exit 1`), чтобы Ansible прервал выполнение.
- **Аргументы**: при использовании `--vault-id <label>` Ansible передает идентификатор как аргумент скрипту.

```bash
#!/bin/bash
# Пример минимального скрипта-источника
set -euo pipefail
echo "${VAULT_PASS:?Переменная VAULT_PASS не задана}"
```

**Для Sysadmin:** Проверяйте вывод скрипта перед использованием: `./vault-pass.sh | cat -A` — лишние символы (например, `^M` или пробелы) сломают расшифровку.

## Практические сценарии

### Сценарий 1: Интерактивный ввод и Vault ID

Самый безопасный способ для ручного запуска, так как секрет существует только в оперативной памяти (RAM — Random Access Memory).

```bash
# Запрос пароля для конкретной метки (Vault ID)
ansible-playbook site.yml --vault-id prod@prompt
# → Vault password (prod): (ввод пароля)
```

**Для Sysadmin:** Используйте `--vault-id prod@prompt` вместо `--ask-vault-pass`, чтобы явно указать метку. Это предотвращает случайное использование неправильного пароля при наличии нескольких Vault ID.

### Сценарий 2: Локальный файл пароля

Самый простой способ для локальной разработки.

1. **Создание файла**:
    ```bash
    echo "MySecureVaultPass2024!" > .vault_pass
    chmod 600 .vault_pass
    ```

2. **Добавление в `.gitignore`**:
    ```bash
    echo ".vault_pass*" >> .gitignore
    ```

3. **Запуск**:
    ```bash
    ansible-playbook site.yml --vault-password-file .vault_pass
    ```

**Для DevOps:** Никогда не коммитьте `.vault_pass`. Добавьте проверку в pre-commit hook: `git diff --cached --name-only | grep -E '\.vault_pass' && exit 1`.

### Сценарий 3: Универсальный клиентский скрипт

Это стандарт для профессиональной автоматизации. Скрипт может получать пароль из любой on-prem системы (HashiCorp Vault, KeePassXC, сетевой хранилище).

**Требования к скрипту:**
- Права на выполнение: `chmod +x script.sh`.
- Вывод в STDOUT: только чистый пароль.
- Обработка аргументов: при использовании `--vault-id` Ansible передает идентификатор как аргумент.

**Пример скрипта для HashiCorp Vault (`fetch_vault_pass.py`)**:
```python
#!/usr/bin/env python3
import os, sys, requests

ROLE_ID = os.getenv("VAULT_ROLE_ID")
SECRET_ID = os.getenv("VAULT_SECRET_ID")
VAULT_ADDR = os.getenv("VAULT_ADDR", "https://vault.example.com:8200")

def get_token():
    r = requests.post(f"{VAULT_ADDR}/v1/auth/approle/login",
                      json={"role_id": ROLE_ID, "secret_id": SECRET_ID})
    r.raise_for_status()
    return r.json()["auth"]["client_token"]

def get_password(token, vault_id):
    r = requests.get(f"{VAULT_ADDR}/v1/secret/data/ansible/{vault_id}",
                     headers={"X-Vault-Token": token})
    r.raise_for_status()
    return r.json()["data"]["data"]["password"]

if __name__ == "__main__":
    vault_id = sys.argv[2] if len(sys.argv) > 2 else "default"
    print(get_password(get_token(), vault_id))
```

**Запуск**:
```bash
chmod +x fetch_vault_pass.py
ansible-playbook site.yml --vault-password-file ./fetch_vault_pass.py --vault-id prod
```

**Для SRE:** Храните `ROLE_ID` и `SECRET_ID` в защищенном хранилище Control Node (например, в зашифрованном файле, доступном только root). Используйте AppRole с минимально необходимыми правами (`read` только к путям Ansible).

### Сценарий 4: GPG-шифрование файла пароля

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

3. **Скрипт расшифровки (`fetch_vault_pass.sh`)**:
    ```bash
    #!/bin/bash
    gpg --quiet --decrypt .vault_pass.txt.gpg 2>/dev/null
    ```

4. **Использование**:
    ```bash
    chmod +x fetch_vault_pass.sh
    ansible-playbook site.yml --vault-password-file ./fetch_vault_pass.sh
    ```

**Для Sysadmin:** `.vault_pass.txt.gpg` безопасно для коммита в Git. Расшифровывается только на машинах с приватным GPG-ключом. Документируйте fingerprint ключа для recovery.

### Сценарий 5: pass (Password Store)

Использование Unix-утилиты `pass` как источника паролей.

1. **Установка**:
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

**Для SRE:** `pass` хранит секреты в зашифрованном виде в Git-репозитории. Используйте `pass git push` для синхронизации между Control Node. Настройте `GPG_TTY` и `GPG_AGENT_INFO` для безпарольной работы в CI.

### Сценарий 6: KeePassXC

Автоматическое извлечение пароля из локального хранилища KeePassXC.

1. **Требования**:
    - KeePassXC установлен и содержит запись с паролем Vault.
    - CLI `keepassxc-cli` доступен в PATH (входит в KeePassXC 2.7+).

2. **Скрипт (`vault-pass-keepass.sh`)**:
    ```bash
    #!/bin/bash
    KEEPASS_DB="${KEEPASS_DB:-~/Keys.kdbx}"
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
    # С паролем через переменную окружения
    KEEPASS_PASS="master" ansible-playbook site.yml --vault-password-file ./vault-pass-keepass.sh
    # Интерактивно
    ansible-playbook site.yml --vault-password-file ./vault-pass-keepass.sh
    ```

**Для Sysadmin:** Храните `.kdbx` файл в зашифрованном домашнем каталоге. Резервное копирование KeePassXC-базы — часть disaster recovery. Никогда не передавайте мастер-пароль KeePassXC через CI-переменные.

### Сценарий 7: Process substitution (без следа на диске)

Передача пароля через дескриптор файлов для отсутствия открытого файла на диске.

```bash
# Вместо:
ansible-playbook site.yml --vault-password-file .vault_pass

# Безопасный вариант (пароль не попадает в fs):
ansible-playbook site.yml --vault-password-file <(echo "$VAULT_PASSWORD")
```

**Примечание:** Пароль виден в `/proc/*/fd/` на время выполнения. Для максимальной безопасности на shared серверах используйте скрипты с правами `700`.

**Для Sysadmin:** На shared Control Node контролируйте права доступа к `/proc`. Убедитесь, что только authorized пользователи имеют доступ к процессам Ansible.

## Операции и команды

### Основные команды

| Команда | Описание | Пример |
| :--- | :--- | :--- |
| `ansible-vault create <file>` | Создание нового зашифрованного файла | `ansible-vault create group_vars/all/vault.yml` |
| `ansible-vault create --vault-id <label>@<source> <file>` | Создание с указанием Vault ID | `ansible-vault create --vault-id prod@.vault_pass group_vars/prod/vault.yml` |
| `ansible-vault edit <file>` | Редактирование зашифрованного файла | `ansible-vault edit group_vars/all/vault.yml` |
| `ansible-vault encrypt <file>` | Шифрование существующего файла | `ansible-vault encrypt group_vars/all/vault.yml` |
| `ansible-vault decrypt <file>` | Расшифровка файла (внимание: открытый текст на диске) | `ansible-vault decrypt group_vars/all/vault.yml` |
| `ansible-vault view <file>` | Просмотр содержимого без редактирования | `ansible-vault view group_vars/all/vault.yml --vault-password-file .vault_pass` |
| `ansible-vault rekey <file>` | Смена пароля файла | `ansible-vault rekey group_vars/all/vault.yml` |
| `ansible-vault rekey --vault-id <old>@<old_src> --new-vault-id <new>@<new_src> <file>` | Смена пароля или Vault ID | `ansible-vault rekey --vault-id prod@old.sh --new-vault-id prod@new.sh secrets.yml` |
| `ansible-vault encrypt_string '<value>' --name '<var>'` | Шифрование строки для инлайнового использования | `ansible-vault encrypt_string 'MySecret' --name 'db_password'` |

### Переменные окружения

| Переменная | Описание | Пример |
| :--- | :--- | :--- |
| `ANSIBLE_VAULT_PASSWORD_FILE` | Путь к файлу или скрипту с паролем | `export ANSIBLE_VAULT_PASSWORD_FILE=~/.vault_pass` |
| `ANSIBLE_VAULT_IDENTITY_LIST` | Список Vault ID через запятую | `export ANSIBLE_VAULT_IDENTITY_LIST="dev@~/.vault_dev,prod@~/.vault_prod"` |
| `EDITOR` | Системный редактор для `ansible-vault edit` | `export EDITOR=nano` |
| `TMPDIR` | Директория для временных файлов | `TMPDIR=~/.tmp` |

**Приоритет аргументов командной строки**: `--vault-password-file` > `ANSIBLE_VAULT_PASSWORD_FILE` > `vault_password_file` в `ansible.cfg`.

## Устранение неполадок

### Ошибка: скрипт не возвращает пароль

**Причина**: скрипт выводит лишний текст (промпты, логи) в STDOUT или возвращает неверный exit code.

```bash
# Проверка вывода скрипта
./vault-pass.sh
# → Должен вывести ТОЛЬКО пароль без лишних символов

# Отладка
bash -x ./vault-pass.sh  # Показать выполнение скрипта
```

**Решение**: Уберите `echo` с логами, `read -p` и интерактивные промпты из скрипта. Используйте переменные окружения для передачи конфиденциальных данных.

### Ошибка: `Permission denied` при чтении GPG-файла

**Причина**: GPG-ключ не импортирован в текущий keyring или нет доступа к агенту.

```bash
# Проверьте доступные ключи
gpg --list-keys

# Если ключ на смонтированном носителе
gpg --import /path/to/key.asc
```

### Ошибка: `keepassxc-cli` не найден

**Причина**: KeePassXC CLI не установлен или не в PATH.

```bash
# Проверка установки
keepassxc-cli --version

# macOS
brew install keepassxc

# Debian/Ubuntu
sudo apt install keepassxc
```

### Ошибка: `Vault password file not found`

**Причина**: файл пароля не существует по указанному пути или нет прав на чтение.

```bash
# Проверка существования файла
test -f .vault_pass && echo "OK" || echo "NOT FOUND"

# Проверка прав
test -r .vault_pass && echo "Readable" || echo "Not readable"
```

### Пароль виден в `/proc/*/fd/`

**Причина**: использование process substitution `<()` или передача пароля через pipe.

```bash
# Проверка
ls -la /proc/$$/fd/

# Решение: используйте файл с правами 600 вместо process substitution
```

**Для Sysadmin:** На shared серверах запретите доступ к `/proc/*/fd/` для непривилегированных пользователей через `mount -o remount,hidepid=2 /proc`.

## Лучшие практики

### Для DevOps

- **no_log**: Всегда используйте `no_log: true` в задачах, работающих с секретами (пароли, токены, ключи). Это исключает утечку значений в логи Ansible.
- **Автоматизация**: В CI/CD передавайте пароль через `--vault-password-file` или `ANSIBLE_VAULT_PASSWORD_FILE`. Избегайте `--ask-vault-pass` — он блокирует выполнение.
- **Гранулярность**: Шифруйте значения, а не целые файлы, когда это возможно. Это упрощает code review.
- **Pre-commit**: Настройте `ansible-lint` и `pre-commit` hook для проверки наличия `no_log` и отсутствия открытых секретов.
- **Гигиена Git**: Добавляйте `.vault_pass*`, `*.gpg` и файлы паролей в `.gitignore`. Никогда не коммитьте их в репозиторий.

### Для SRE

- **Политика ротации**: Настройте политику ротации мастер-паролей (раз в квартал) и следите за ней через `ansible-vault rekey`.
- **Аудит**: Включите логирование Ansible через `ANSIBLE_LOG_PATH`. Регулярно проверяйте историю Git на утечки.
- **Инцидент-респонс**: При компрометации пароля немедленно выполните массовую ротацию. Документируйте процедуру.
- **Динамические секреты**: В Production используйте HashiCorp Vault или аналогичные on-prem системы для динамической выдачи секретов. Это исключает хранение статических паролей на диске.
- **Строгий режим**: Включите `vault_id_match = True` в `ansible.cfg` для предотвращения случайного использования ключей не по назначению.

### Для Sysadmin

- **Права доступа**: Устанавливайте `chmod 600` на все файлы паролей. Это ограничивает доступ только владельцу.
- **Временные файлы**: На shared Control Node контролируйте `$TMPDIR` и права доступа. Установите `umask 0077`.
- **Редакторы**: Некоторые редакторы (VS Code, JetBrains) создают резервные файлы. При использовании `ansible-vault edit` убедитесь, что резервные файлы не попадают в Git.
- **no_log и debug**: `no_log: true` скрывает вывод задачи, но не скрывает переменные, используемые в `register` или `debug` без `no_log`.
- **Просмотр секретов**: Используйте `ansible-vault view` вместо `decrypt` для чтения секретов на production-хостах.
- **Конфигурация**: Используйте `ansible-config dump --defaults | grep vault` для аукта текущей конфигурации Vault.
- **GPG ключи**: Храните резервные копии приватных GPG-ключей в защищенном хранилище. Без ключа расшифровать `.gpg` файл невозможно.

## См. также

- [Ansible Vault: Основы](./basics.md) — базовый синтаксис, создание и редактирование файлов.
- [Ansible Vault: Практические примеры](./examples.md) — сценарии использования Vault в CI/CD, ролях и мультиокружениях.
- [Лучшие практики по безопасности](./best_practices.md) — рекомендации по защите секретов в Git и логах.
- [Использование нескольких хранилищ (Multi-Vault)](./multi_vault.md) — детальная работа с Vault ID и метками.

## Дополнительная информация

### Граничные случаи

- **Смешанные файлы**: файл может содержать как обычные, так и зашифрованные переменные.
- **Кэширование фактов**: обычный `set_fact` **не** попадает в кэш — Ansible сохраняет только факты, помеченные `cacheable: true`. Если секрет задан через `set_fact` с `cacheable: true`, его открытое значение попадёт в кэш на диске (JSON, pickle, redis) вместе со всем остальным. Секреты из vault не должны быть `cacheable`.
- **Память**: секреты расшифровываются в память Control Node. Убедитесь, что у системы достаточно оперативной памяти для крупных инвентарей.
- **Редакторы**: Некоторые редакторы создают резервные файлы в том же каталоге. При использовании `ansible-vault edit` убедитесь, что резервные файлы не попадают в Git.
- **no_log и debug**: `no_log: true` скрывает вывод задачи, но не скрывает переменные, используемые в `register` или `debug` без `no_log`.

### Интеграция с HashiCorp Vault

HashiCorp Vault — on-prem система централизованного управления секретами с динамической выдачей, ротацией и контролем доступа. Поддерживает различные бэкенды: KV, PKI, Database, Transit.

**Два подхода к интеграции с Ansible:**
1. **Получение секретов из Vault в плейбуке** через lookup-плагин `community.hashi_vault.vault_kv2_get`.
2. **Пароль vault-шифрования из Vault**: скрипт-источник получает пароль из Vault и передает его Ansible через STDOUT.

Детальную настройку AppRole, policies и CI/CD-интеграцию см. в [Лучшие практики по безопасности](./best_practices.md#интеграция-с-внешними-менеджерами-секретов-hashicorp-vault).

### Справочник переменных окружения

| Переменная | Описание | Пример |
| :--- | :--- | :--- |
| `ANSIBLE_VAULT_PASSWORD_FILE` | Путь к файлу пароля по умолчанию | `export ANSIBLE_VAULT_PASSWORD_FILE=~/.vault_pass` |
| `ANSIBLE_VAULT_IDENTITY_LIST` | Список Vault ID через запятую | `export ANSIBLE_VAULT_IDENTITY_LIST="dev@~/.vault_dev,prod@~/.vault_prod"` |
| `VAULT_ADDR` | Адрес сервера HashiCorp Vault | `export VAULT_ADDR="https://vault.example.com:8200"` |
| `VAULT_ROLE_ID` | Role ID для AppRole-аутентификации | `export VAULT_ROLE_ID="my-app-role"` |
| `VAULT_SECRET_ID` | Secret ID для AppRole-аутентификации | `export VAULT_SECRET_ID="my-secret-id"` |
