# Ansible Vault: Практические примеры

## Определения

- **Инлайновое шифрование (Inline Encryption)**: Метод шифрования отдельных значений переменных непосредственно в YAML-файле, что сохраняет читаемость структуры для систем контроля версий.
- **Vault Password Script**: Исполняемый файл (Python, Bash), который Ansible вызывает для получения пароля расшифровки. Скрипт возвращает только строку пароля в STDOUT.
- **Vault ID**: Текстовая метка (например, `dev`, `prod`), связывающая зашифрованный файл с конкретным паролем или источником пароля. Поддерживается с ansible-core 2.4+.
- **EncryptedString (ansible-core 2.19+)**: Внутренний тип данных Ansible для автоматического отслеживания зашифрованных значений и предотвращения их случайного вывода в логи (Data Tagging).
- **no_log**: Директива задачи, которая скрывает весь вывод задачи в логах Ansible. Обязательна для всех операций с секретами.
- **Смешанный файл (Mixed File)**: YAML-файл, содержащий как обычные открытые переменные, так и зашифрованные значения `!vault`.

## Основные концепции

### Уровни изоляции секретов

При выборе объекта шифрования следует придерживаться принципа гранулярности:

- **Шифрование значений (Рекомендуется)**: Используйте `ansible-vault encrypt_string`. Это сохраняет читаемость Git-диффов и упрощает разрешение конфликтов при слиянии веток.
- **Шифрование файлов**: Подходит для больших блоков данных (SSL-сертификаты, приватные SSH-ключи).
- **Vault ID**: Позволяют разграничивать доступ к секретам разных команд или окружений в рамках одного репозитория.

### Архитектура хранения секретов

```
project/
├── ansible.cfg                  # vault_password_file, vault_identity_list
├── .vault_pass                  # Пароль (в .gitignore)
├── .vault_pass_dev              # Пароль dev-окружения
├── .vault_pass_prod             # Пароль prod-окружения
├── .gitignore                   # Содержит .vault_pass*
├── group_vars/
│   ├── all/
│   │   ├── vars.yml             # Обычные переменные
│   │   └── vault.yml            # Зашифрованные секреты
│   ├── dev/
│   │   └── vault.yml            # Секреты dev (метка: dev)
│   └── prod/
│       └── vault.yml            # Секреты prod (метка: prod)
├── roles/
│   └── app/
│       └── vars/
│           └── main.yml         # Зашифрованные переменные роли
└── site.yml
```

**Для Sysadmin:** На shared Control Node контролируйте `$TMPDIR` и права доступа к временным файлам. Устанавливайте `umask 0077` для автоматического ограничения прав на создаваемые файлы паролей.

### Производительность

При расшифровке большого количества Vault-файлов (>100) может наблюдаться задержка из-за вычислений PBKDF2 (~50-100 мс на файл для современного CPU). Для оптимизации используйте формат 1.2 с Vault ID и `vault_id_match = True`.

## Практические сценарии

### Сценарий 1: Защита переменных окружения (Inventory Variables)

Типичный подход для хранения паролей баз данных и ключей доступа.

1. **Создание зашифрованного файла**:
    ```bash
    # Создание файла для группы хостов 'webservers'
    ansible-vault create group_vars/webservers/vault.yml
    ```

2. **Содержимое файла**:
    ```yaml
    # Внутри редактора задаются секреты
    vault_db_password: "MySuperSecretPassword"
    vault_api_token: "abc-123-def-456"
    ```

3. **Запуск с ручным вводом пароля**:
    ```bash
    ansible-playbook site.yml --ask-vault-pass
    ```

**Для DevOps:** Добавьте `group_vars/**/vault.yml` в `.gitignore` на уровне репозитория. Никогда не коммитьте файлы паролей.

### Сценарий 2: Инлайновое шифрование в инвентаре

Применяется, когда параметры подключения специфичны для конкретного хоста.

1. **Генерация зашифрованной строки**:
    ```bash
    ansible-vault encrypt_string 'TargetHostPassword' --name 'ansible_ssh_pass'
    # → ansible_ssh_pass: !vault |
    #     $ANSIBLE_VAULT;1.2;AES256;prod
    #     6633363365313835663738643633393165333066373238313437346132333036...
    ```

2. **Вставка в инвентарь (`hosts.yml`)**:
    ```yaml
    all:
      hosts:
        db-node-01:
          ansible_host: 192.168.1.50
          ansible_user: deploy
          ansible_ssh_pass: !vault |
            $ANSIBLE_VAULT;1.2;AES256;prod
            6633363365313835663738643633393165333066373238313437346132333036
    ```

**Для DevOps:** Используйте `--vault-id prod@.vault_pass_prod` для явного указания источника пароля. Это предотвращает случайное использование неправильного пароля.

### Сценарий 3: Мультиокруженый деплой с Vault IDs

Безопасное управление секретами для dev/staging/prod в одном пайплайне.

1. **Создание зашифрованных файлов**:
    ```bash
    # Dev
    ansible-vault create --vault-id dev@.vault_pass_dev group_vars/dev/vault.yml

    # Staging
    ansible-vault create --vault-id staging@.vault_pass_staging group_vars/staging/vault.yml

    # Prod
    ansible-vault create --vault-id prod@.vault_pass_prod group_vars/prod/vault.yml
    ```

2. **Запуск для конкретного окружения**:
    ```bash
    # Только dev
    ansible-playbook site.yml --limit dev --vault-id dev@.vault_pass_dev

    # Все окружения
    ansible-playbook site.yml \
      --vault-id dev@.vault_pass_dev \
      --vault-id staging@.vault_pass_staging \
      --vault-id prod@.vault_pass_prod
    ```

**Для SRE:** Используйте `vault_id_match = True` в `ansible.cfg` для предотвращения случайного использования ключей не по назначению. При компрометации пароля немедленно выполните массовую ротацию: `find group_vars -name "*.yml" | xargs ansible-vault rekey --vault-id old@source --new-vault-id new@source`.

### Сценарий 4: Централизованная конфигурация

Настройка Vault без передачи флагов в каждой команде.

1. **Файл `ansible.cfg`**:
    ```ini
    [defaults]
    vault_password_file = ./.vault_pass
    vault_identity_list = dev@.vault_pass_dev, prod@.vault_pass_prod
    vault_id_match = True

    [privilege_escalation]
    become = True
    become_method = sudo
    become_user = root
    ```

2. **Использование**:
    ```bash
    # Автоматически подставит пароли из конфига
    ansible-playbook site.yml

    # Переопределение через флаги
    ansible-playbook site.yml --vault-id custom@.vault_pass_custom
    ```

**Для Sysadmin:** Используйте `ansible-config dump --defaults | grep vault` для аукта текущей конфигурации Vault на Control Node.

### Сценарий 5: Vault Password Script

Использование скрипта для динамического получения пароля.

1. **Скрипт `get_vault_pass.sh`**:
    ```bash
    #!/bin/bash
    # Возвращает пароль из защищенного хранилища
    echo "$(pass show ansible/vault)"  # Использует pass (GPG)
    ```

2. **Настройка прав**:
    ```bash
    chmod 700 get_vault_pass.sh
    ```

3. **Запуск**:
    ```bash
    ansible-playbook site.yml --vault-password-file ./get_vault_pass.sh
    ```

**Для Sysadmin:** Скрипт должен возвращать только пароль в STDOUT. Любой дополнительный вывод приведет к ошибке расшифровки. Храните скрипт с правами `700` и добавьте в `.gitignore`.

### Сценарий 6: Массовые операции

#### Шифрование целых каталогов

```bash
# Шифрование всех vault-файлов
find group_vars host_vars -name "*.vault.yml" -exec ansible-vault encrypt {} \;

# Проверка зашифрования
for f in $(find group_vars host_vars -name "*.vault.yml"); do
  echo "=== $f ==="
  head -1 "$f"
done
```

#### Перешифровка после смены пароля

```bash
# Поиск всех vault-файлов и смена пароля
find group_vars host_vars -name "*.vault.yml" | \
xargs ansible-vault rekey --vault-id old@.old_pass --new-vault-id new@.new_pass
```

**Для SRE:** Периодически проверяйте возможность расшифровки всех Vault-файлов новым паролем. Тестируйте процедуру восстановления как часть disaster recovery plan.

### Сценарий 7: Использование Vault в ролях

Безопасная интеграция секретов в Ansible-роли.

1. **Структура роли**:
    ```
    roles/
    └── database/
        ├── defaults/
        │   └── main.yml       # Обычные переменные (открыто)
        ├── vars/
        │   └── main.yml       # Vault-переменные (зашифровано)
        └── tasks/
            └── main.yml       # Задачи с no_log
    ```

2. **`roles/database/vars/main.yml`**:
    ```yaml
    db_root_password: !vault |
      $ANSIBLE_VAULT;1.2;AES256;prod
      6633363365313835663738643633393165333066373238313437346132333036
    ```

3. **`roles/database/tasks/main.yml`**:
    ```yaml
    - name: Создание БД
      community.postgresql.postgresql_db:
        name: "{{ db_name }}"
      become: true
      become_user: postgres

    - name: Установка пароля root
      community.postgresql.postgresql_user:
        name: "{{ db_admin_user }}"
        password: "{{ db_root_password }}"
      become: true
      become_user: postgres
      no_log: true  # Обязательно для секретов
    ```

4. **Запуск**:
    ```bash
    ansible-playbook site.yml --vault-password-file .vault_pass
    ```

### Сценарий 8: CI/CD пайплайн (self-hosted runners)

Использование переменной типа **File** — стандарт безопасности, исключающий утечку пароля через логи.

1. **Настройка в GitLab UI**:
    - `Settings -> CI/CD -> Variables`.
    - Добавьте `VAULT_PASS_FILE`, тип **File**.
    - Включите **Protect** и **Mask**.

2. **Конфигурация `.gitlab-ci.yml`**:
    ```yaml
    deploy:
      stage: deploy
      image: alpine:latest
      before_script:
        - apk add ansible
        - chmod 600 "$VAULT_PASS_FILE"
      script:
        - ansible-playbook deploy.yml --vault-password-file "$VAULT_PASS_FILE"
      environment: production
    ```

**Для DevOps:** На self-hosted раннере контролируйте права доступа к директории с секретами. Удаляйте временные файлы в `post` шагах. Никогда не передавайте пароль через `echo` в логи.

### Сценарий 9: Валидация гигиены секретов

Использование статического анализа для предотвращения случайного коммита открытых секретов.

1. **Настройка правила**:
    `ansible-lint` автоматически проверяет наличие директивы `no_log: true` в задачах, использующих переменные с именами `password`, `secret`, `token`.

2. **Пример защищенной задачи**:
    ```yaml
    - name: Получение секрета через lookup-плагин
      ansible.builtin.set_fact:
        db_password: "{{ lookup('community.hashi_vault.vault_kv2_get', 'db', token=vault_token).secret.password }}"
      no_log: true

    - name: Использование секрета
      ansible.builtin.debug:
        msg: "Длина пароля: {{ db_password | length }}"
    ```

**Для SRE:** Включите `ansible-lint` в pre-commit hook. Настройте правило `no-log-password` для автоматического предотвращения утечек. Документируйте политику в `README.md` репозитория.

### Сценарий 10: Извлечение секрета через CLI (Debug)

Проверка значения секрета без запуска полного плейбука.

```bash
# Вывод конкретной переменной из зашифрованного файла
ansible localhost -m debug -a "var=db_password" -e "@group_vars/all/vault.yml" --vault-password-file .vault_pass
```

**Для Sysadmin:** Используйте `ansible-vault view` вместо `decrypt` для чтения секретов на production-хостах. `decrypt` оставляет файл в открытом виде, что рискованно на shared серверах.

### Сценарий 11: Аудит и соответствие (Compliance)

Для соответствия требованиям информационной безопасности (ISO 27001, PCI DSS, SOC 2):

1. **Инвентаризация секретов**: Регулярно проверяйте наличие зашифрованных файлов:
    ```bash
    find group_vars host_vars -name "*.yml" -exec grep -l "^$ANSIBLE_VAULT" {} +
    ```

2. **Проверка прав доступа**: Убедитесь, что файлы паролей имеют права `600`:
    ```bash
    find . -name ".vault_pass*" -exec ls -la {} \;
    ```

3. **Аудит использования**: Включите логирование Ansible:
    ```bash
    export ANSIBLE_LOG_PATH="/var/log/ansible/ansible.log"
    ```

4. **Проверка утечек**: Поиск открытых секретов в Git-истории:
    ```bash
    git log --all -p | grep -E "(password|secret|token|key)\s*:"
    ```
    Ansible не подставляет плейсхолдеры вместо секретов, поэтому любой результат grep — это открытый секрет в истории.

**Для SRE:** Настройте автоматический аудит через `ansible-lint` и pre-commit hooks. Регулярно проверяйте историю Git на наличие открытых секретов. Документируйте процедуру реагирования на инциденты утечки.

### Сценарий 12: Резервное копирование и восстановление

Vault-файлы можно safely хранить в Git, но файлы паролей — нет. Для disaster recovery:

1. **Резервное копирование**: Сохраните мастер-пароли в защищенном менеджере секретов или на внешнем носителе в зашифрованном виде.
2. **Восстановление**: При утрате пароля файл восстановить невозможно (AES-256 resistant к brute-force). Восстанавливайте секреты из primary-источника или запрашивайте у команды.
3. **Тестирование восстановления**: Периодически проверяйте возможность расшифровки всех Vault-файлов новым паролем.

**Для Sysadmin:** Настройте автоматическое резервное копирование файлов паролей в зашифрованное хранилище (например, `pass` с GPG или внешний носитель). Тестируйте восстановление минимум раз в квартал.

## Операции и команды

| Команда | Описание | Пример |
|---------|----------|--------|
| `ansible-vault create <file>` | Создание нового зашифрованного файла | `ansible-vault create group_vars/all/vault.yml` |
| `ansible-vault create --vault-id <label>@<source> <file>` | Создание с указанием Vault ID | `ansible-vault create --vault-id prod@.vault_pass group_vars/prod/vault.yml` |
| `ansible-vault edit <file>` | Редактирование зашифрованного файла | `ansible-vault edit group_vars/all/vault.yml` |
| `ansible-vault encrypt <file>` | Шифрование существующего файла | `ansible-vault encrypt group_vars/all/vault.yml` |
| `ansible-vault encrypt --vault-id <label>@<source> <file>` | Шифрование с Vault ID | `ansible-vault encrypt --vault-id dev@.vault_pass_dev group_vars/dev/vault.yml` |
| `ansible-vault decrypt <file>` | Расшифровка файла (внимание: открытый текст на диске) | `ansible-vault decrypt group_vars/all/vault.yml` |
| `ansible-vault view <file>` | Просмотр содержимого без редактирования | `ansible-vault view group_vars/all/vault.yml --vault-password-file .vault_pass` |
| `ansible-vault rekey <file>` | Смена пароля файла | `ansible-vault rekey group_vars/all/vault.yml` |
| `ansible-vault rekey --vault-id old@source --new-vault-id new@source <file>` | Смена Vault ID | `ansible-vault rekey --vault-id prod@old_pass --new-vault-id prod@new_pass group_vars/vault.yml` |
| `ansible-vault encrypt_string '<value>' --name '<var>'` | Шифрование строки для инлайнового использования | `ansible-vault encrypt_string 'MySecret' --name 'db_password'` |
| `ansible-vault encrypt_string '<value>' --name '<var>' --vault-id <label>@<source>` | Шифрование строки с Vault ID | `ansible-vault encrypt_string 'ProdSecret' --name 'api_key' --vault-id prod@.vault_pass` |

## Устранение неполадок

### Ошибка: `Decryption failed`

**Причина**: неверный пароль, Vault ID не совпадает или файл поврежден.

**Решение**:
```bash
# Проверка Vault ID в заголовке
head -1 group_vars/prod/vault.yml
# → $ANSIBLE_VAULT;1.2;AES256;prod (нужен пароль для "prod")

# Расшифровка с явным указанием Vault ID
ansible-vault view group_vars/prod/vault.yml --vault-id prod@.vault_pass_prod
```

### Ошибка: `Vault password file not found`

**Причина**: файл пароля не существует или путь указан неверно.

**Решение**:
```bash
# Проверка существования файла
ls -la .vault_pass

# Проверка прав доступа
stat -c "%a %n" .vault_pass
# → 600 .vault_pass
```

### Ошибка: `Encryption failed` при использовании `encrypt_string`

**Причина**: отсутствует Vault ID или пароль для выбранного ID.

**Решение**:
```bash
# Явное указание Vault ID
ansible-vault encrypt_string 'secret' --name 'api_key' --vault-id prod@.vault_pass_prod
```

### Секреты попадают в логи

**Причина**: отсутствует `no_log: true` или секреты выводятся через `debug`/`register`.

**Решение**:
```yaml
- name: Задача с секретом
  ansible.builtin.command: /usr/bin/secret_tool
  no_log: true

- name: Использование результата
  ansible.builtin.debug:
    msg: "Операция завершена"
  # Нет no_log, но нет и секретов в выводе
```

## Лучшие практики

### Для DevOps

- **no_log**: Всегда используйте `no_log: true` в задачах, работающих с секретами (пароли, токены, ключи). Это исключает утечку значений в логи Ansible.
- **Читаемость Git**: Предпочитайте `ansible-vault encrypt_string` для отдельных переменных. Это сохраняет читаемость Git-диффов и упрощает разрешение конфликтов.
- **Автоматизация**: В CI/CD передавайте пароль через `--vault-password-file` или `ANSIBLE_VAULT_PASSWORD_FILE`. Избегайте `--ask-vault-pass` — он блокирует выполнение.
- **Гранулярность**: Шифруйте значения, а не целые файлы, когда это возможно. Это упрощает code review.
- **Pre-commit**: Настройте `ansible-lint` и `pre-commit` hook для проверки наличия `no_log` и отсутствия открытых секретов.

### Для SRE

- **Мультиокружение**: Используйте Vault IDs (`--vault-id dev@.vault_pass_dev`) для изоляции секретов `dev`, `staging`, `prod`. Это позволяет использовать разные пароли для каждого окружения.
- **Политика ротации**: Настройте политику ротации мастер-паролей (раз в квартал) и следите за ней через `ansible-vault rekey`.
- **Аудит**: Включите логирование Ansible через `ANSIBLE_LOG_PATH`. Регулярно проверяйте историю Git на утечки.
- **Инцидент-респонс**: При компрометации пароля немедленно выполните массовую ротацию. Документируйте процедуру.
- **Строгий режим**: Включите `vault_id_match = True` в `ansible.cfg` для предотвращения случайного использования ключей не по назначению.
- **Динамические секреты**: В Production используйте HashiCorp Vault или аналогичные системы для динамической выдачи секретов. Это исключает хранение статических паролей на диске.

### Для Sysadmin

- **Права доступа**: Устанавливайте `chmod 600` на все файлы паролей. Это ограничивает доступ только владельцу.
- **Временные файлы**: На shared Control Node контролируйте `$TMPDIR` и права доступа. Установите `umask 0077`.
- **Файлы паролей**: Никогда не коммитьте `.vault_pass`, `.vault_pass_dev`. Добавьте их в `.gitignore`.
- **Редакторы**: Некоторые редакторы (VS Code, JetBrains) создают резервные файлы. При использовании `ansible-vault edit` убедитесь, что резервные файлы не попадают в Git.
- **no_log и debug**: `no_log: true` скрывает вывод задачи, но не скрывает переменные, используемые в `register` или `debug` без `no_log`.
- **Просмотр секретов**: Используйте `ansible-vault view` вместо `decrypt` для чтения секретов на production-хостах.
- **Конфигурация**: Используйте `ansible-config dump --defaults | grep vault` для аукта текущей конфигурации Vault.

## См. также

- [Ansible Vault: Основы](./basics.md) — базовые команды, версии заголовков и архитектура.
- [Управление паролями и источниками](./passwords.md) — скрипты для получения паролей и внешние менеджеры секретов.
- [Использование нескольких хранилищ (Multi-Vault)](./multi_vault.md) — детальная работа с Vault ID и метками.
- [Лучшие практики по безопасности](./best_practices.md) — рекомендации по защите секретов в Git и логах.

## Дополнительная информация

### Граничные случаи

- **Смешанные файлы**: файл может содержать как обычные, так и зашифрованные переменные.
- **Кэширование фактов**: обычный `set_fact` **не** попадает в кэш — Ansible сохраняет только факты, помеченные `cacheable: true`. Если секрет задан через `set_fact` с `cacheable: true`, его открытое значение попадёт в кэш на диске (JSON, pickle, redis) вместе со всем остальным. Секреты из vault не должны быть `cacheable`.
- **Память**: секреты расшифровываются в память Control Node. Убедитесь, что у системы достаточно оперативной памяти для крупных инвентарей.
- **Редакторы**: Некоторые редакторы создают резервные файлы в том же каталоге. При использовании `ansible-vault edit` убедитесь, что резервные файлы не попадают в Git.
- **no_log и debug**: `no_log: true` скрывает вывод задачи, но не скрывает переменные, используемые в `register` или `debug` без `no_log`.

### Справочник переменных окружения

| Переменная | Описание | Пример |
|------------|----------|--------|
| `ANSIBLE_VAULT_PASSWORD_FILE` | Путь к файлу пароля по умолчанию | `export ANSIBLE_VAULT_PASSWORD_FILE=~/.vault_pass` |
| `ANSIBLE_VAULT_IDENTITY_LIST` | Список Vault ID через запятую | `export ANSIBLE_VAULT_IDENTITY_LIST="dev@~/.vault_dev,prod@~/.vault_prod"` |
| `EDITOR` | Системный редактор для `ansible-vault edit` | `export EDITOR=nano` |
| `TMPDIR` | Директория для временных файлов | `TMPDIR=~/.tmp` |
