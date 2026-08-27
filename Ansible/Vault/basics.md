# Ansible Vault: Основы

## Предварительные требования

- **Ansible**: версия 2.4 или выше (рекомендуется 2.12+ для полной поддержки Vault ID и EncryptedString). Проверка версии: `ansible --version`
- **Системный редактор**: команда `ansible-vault edit` использует переменную окружения `$EDITOR` (по умолчанию `vi`). Установите удобный редактор: `export EDITOR=nano` или `export EDITOR=code --wait`
- **Права доступа**: файлы паролей должны быть доступны только владельцу (`chmod 600 .vault_pass`). Нарушение прав доступа приведет к ошибке `InsecureWorldReadablePermissions`
- **Git**: для использования Vault в CI/CD (Continuous Integration / Continuous Deployment) необходимо добавить файлы паролей в `.gitignore` во избежание утечек
- **Операционная память**: при работе с `ansible-vault edit` временные файлы создаются в оперативной памяти (если ОС поддерживает это через `mktemp`) или в `/tmp`. На общих серверах убедитесь, что `$TMPDIR` указывает на защищенную директорию

## Определения

- **Ansible Vault**: Встроенный в Ansible механизм для шифрования секретов, таких как пароли, ключи API (Application Programming Interface — интерфейс программирования приложений) и сертификаты SSL (Secure Sockets Layer — протокол защищенных сокетов). Он позволяет безопасно хранить чувствительные данные в системе контроля версий (Git) вместе с кодом автоматизации.
- **Хранилище (Vault)**: Зашифрованный YAML-файл (YAML Ain't Markup Language — рекурсивный акроним «YAML не язык разметки») или отдельная зашифрованная строка, содержащие секреты.
- **AES-256**: Стандартный алгоритм симметричного шифрования (Advanced Encryption Standard — продвинутый стандарт шифрования с ключом 256 бит), используемый Ansible Vault для защиты данных. В современных версиях используется режим `AES-256-CTR`.
- **PBKDF2**: Функция формирования ключа на основе пароля (Password-Based Key Derivation Function 2). Ansible Vault использует её для преобразования мастер-пароля в криптографический ключ, применяя тысячи итераций хеширования для защиты от перебора.
- **HMAC**: Код аутентификации сообщений с использованием хеш-функций (Hash-based Message Authentication Code). Применяется для проверки целостности данных: если зашифрованный файл был изменен без знания пароля, Ansible обнаружит это при расшифровке.
- **EncryptedString (Core 2.19+)**: Новый внутренний тип данных в Ansible, заменивший `AnsibleVaultEncryptedUnicode`. Упрощает обработку зашифрованных строк плагинами и повышает надежность системы **Data Tagging** (отслеживание происхождения данных для предотвращения утечек в логи).

## Основные концепции

### Принципы работы

Ansible Vault шифрует данные «на лету» во время выполнения плейбука. Зашифрованные данные помечаются заголовком, который указывает на версию формата и алгоритм:
- `$ANSIBLE_VAULT;1.1;AES256`: Классический формат (появился в Ansible 1.5). Требует перебора всех предоставленных паролей до первого успешного совпадения.
- `$ANSIBLE_VAULT;1.2;AES256;label`: Современный формат с поддержкой меток (Vault ID), доступный с версии **Ansible 2.4**. Позволяет мгновенно выбрать нужный пароль по метке `label`.

**Безопасность выполнения:** Даже зашифрованные переменные могут попасть в логи в открытом виде при отладке или ошибках. Для защиты всегда используйте директиву `no_log: true` в задачах, работающих с секретами.

### Источники паролей

Существует несколько способов предоставить пароль для расшифровки через CLI (Command Line Interface — интерфейс командной строки):

#### 1. Интерактивный ввод

Флаг `--ask-vault-pass` запрашивает пароль при каждом запуске:

```bash
ansible-playbook site.yml --ask-vault-pass
# → Vault password: (ввод пароля)
```

**Преимущество**: пароль никогда не записывается на диск.
**Недостаток**: невозможно автоматизировать (не подходит для CI/CD).

#### 2. Файл пароля

Флаг `--vault-password-file` или переменная окружения `ANSIBLE_VAULT_PASSWORD_FILE`:

```bash
# Через флаг
ansible-playbook site.yml --vault-password-file .vault_pass

# Через переменную окружения
export ANSIBLE_VAULT_PASSWORD_FILE=.vault_pass
ansible-playbook site.yml
```

**Создание файла пароля**:
```bash
echo "MySecureVaultPassword" > .vault_pass
chmod 600 .vault_pass
# → -rw------- 1 user user ... .vault_pass
```

#### 3. Vault ID (Ansible 2.4+)

Позволяет использовать несколько паролей с метками для разных окружений:

```bash
# Синтаксис: --vault-id label@source
ansible-playbook site.yml \
  --vault-id dev@.vault_pass_dev \
  --vault-id prod@.vault_pass_prod

# Интерактивный ввод для конкретной метки
ansible-playbook site.yml --vault-id dev@prompt
# → Vault password for dev: (ввод пароля)
```

**Преимущество**: мгновенный выбор нужного пароля по метке без перебора.
**Ограничение**: доступно только в формате заголовка `$ANSIBLE_VAULT;1.2;AES256;label`.

#### 4. Конфигурация (`ansible.cfg`)

Установка пути к файлу пароля по умолчанию:

```ini
[defaults]
# Один пароль для всех vault-файлов
vault_password_file = ./.vault_pass

# Или список Vault IDs для разных окружений
vault_identity_list = dev@.vault_pass_dev, prod@.vault_pass_prod

# Строгий режим Vault ID (только точное совпадение меток)
vault_id_match = True
```

**Приоритет поиска:** При использовании нескольких Vault ID Ansible применяет логику «первого совпадения». Если файл зашифрован с меткой `prod`, но в конфиге первым указан `dev`, Ansible сначала попробует `dev`, поймет, что метка не совпадает (в формате 1.2), и перейдет к `prod`.

> **Важно:** При использовании файлов паролей обязательно ограничивайте права доступа (`chmod 600 .vault_pass`) и добавляйте их в `.gitignore`.

### Основные команды

Все команды поддерживают аргумент `--vault-id` или `--vault-password-file`.

#### `ansible-vault create <file>`

Создает новый зашифрованный файл и открывает его в редакторе:

```bash
# Обычное создание
ansible-vault create group_vars/all/vault.yml
# → Vault password: (ввод пароля)
# → Откроется редактор для ввода секретов

# С указанием Vault ID
ansible-vault create --vault-id prod@.vault_pass group_vars/prod/vault.yml
```

#### `ansible-vault edit <file>`

Редактирует зашифрованный файл. Ansible расшифровывает его во временный файл в оперативной памяти (если поддерживается ОС) и открывает в системном редакторе (переменная `$EDITOR`):

```bash
ansible-vault edit group_vars/all/vault.yml
# → Vault password: (ввод пароля)
# → Откроется редактор с расшифрованным содержимым
# → После сохранения — автоматически зашифрует обратно
```

**Важно**: на общих серверах временные файлы создаются в `/tmp`. Убедитесь, что `$TMPDIR` указывает на защищенную директорию.

#### `ansible-vault encrypt <file>`

Зашифровывает один или несколько существующих файлов:

```bash
# Один файл
ansible-vault encrypt group_vars/all/vault.yml

# Несколько файлов по маске
ansible-vault encrypt group_vars/*.yml

# С указанием Vault ID
ansible-vault encrypt --vault-id dev@.vault_pass group_vars/dev/vault.yml
```

#### `ansible-vault decrypt <file>`

Полностью расшифровывает файл, удалив заголовок Vault:

```bash
ansible-vault decrypt group_vars/all/vault.yml
# → Vault password: (ввод пароля)
# → decryption successful
```

**Внимание:** После этой команды секреты окажутся в открытом виде на диске. Используйте только когда необходимо временно расшифровать файл.

#### `ansible-vault view <file>`

Выводит содержимое в терминал (STDOUT). Безопаснее, чем `decrypt`, так как не оставляет расшифрованных данных в файловой системе:

```bash
ansible-vault view group_vars/all/vault.yml
# → Vault password: (ввод пароля)
# → db_password: MySecretPassword
# → api_key: 12345-abcde
```

#### `ansible-vault rekey <file>`

Изменяет пароль доступа или метку Vault ID:

```bash
# Смена пароля
ansible-vault rekey group_vars/all/vault.yml
# → Vault password: (текущий пароль)
# → New Vault password: (новый пароль)
# → Confirm New Vault password: (повтор)

# Смена Vault ID
ansible-vault rekey --vault-id prod@old_pass --new-vault-id prod@new_pass group_vars/vault.yml
```

#### `ansible-vault encrypt_string`

Зашифровывает строку и выводит YAML-структуру:

```bash
# Базовое использование
ansible-vault encrypt_string 'MySecretValue'
# → !vault |
# →   $ANSIBLE_VAULT;1.1;AES256
# →   353432643765343364623464...

# С именем переменной
ansible-vault encrypt_string 'MySecretValue' --name 'db_password'
# → db_password: !vault |
# →   $ANSIBLE_VAULT;1.1;AES256
# →   353432643765343364623464...

# С Vault ID
ansible-vault encrypt_string 'ProdSecret' --name 'api_key' --vault-id prod@.vault_pass
```

**Полезные флаги**:
- `--name 'var_name'`: Сразу сформировать готовую YAML-структуру.
- `--ask-vault-pass`: Запросить пароль интерактивно.
- `-n 'var_name'`: Сокращенная форма `--name`.

## Практические сценарии

### Сценарий 1: Работа с зашифрованными файлами переменных

Используется для защиты целых файлов в каталогах переменных (`group_vars`, `host_vars`).

**Этап 1: Создание зашифрованного файла**

```bash
# Создание нового зашифрованного файла
ansible-vault create group_vars/all/vault.yml
# → Vault password: (введите пароль)
# → Confirm Vault password: (повторите пароль)
```

В открывшемся редакторе добавьте секреты:
```yaml
db_password: "MySecretPassword"
api_key: "12345-abcde"
ssl_certificate: |
  -----BEGIN CERTIFICATE-----
  MIIDXTCCAkWgAwIBAgIJAJC1...
  -----END CERTIFICATE-----
```

**Этап 2: Проверка зашифрования**

```bash
# Убедитесь, что файл зашифрован
head -1 group_vars/all/vault.yml
# → $ANSIBLE_VAULT;1.1;AES256
```

**Этап 3: Запуск плейбука с секретами**

```bash
ansible-playbook deploy.yml --vault-password-file .vault_pass
# → PLAY [all] ***********************************************************
# → TASK [Gathering Facts] ***********************************************
# → ok: [webserver1]
# → TASK [Deploy application] *******************************************
# → changed: [webserver1]
# → PLAY RECAP ***********************************************************
# → webserver1 : ok=2  changed=1  unreachable=0  failed=0
```

### Сценарий 2: Шифрование отдельных переменных (Inline Vault)

Предпочтительный метод в современных проектах, так как он сохраняет читаемость структуры YAML и Git-диффов.

**Этап 1: Шифрование строки**

```bash
ansible-vault encrypt_string 'MySecretValue' --name 'db_password'
# → db_password: !vault |
# →   $ANSIBLE_VAULT;1.1;AES256
# →   353432643765343364623464...
```

**Этап 2: Вставка в файл переменных**

Создайте обычный файл `group_vars/all/vars.yml` и вставьте зашифрованное значение:

```yaml
# Обычные переменные (читаемы в Git)
db_host: localhost
db_port: 5432
db_user: admin

# Зашифрованная переменная (скрыта в Git)
db_password: !vault |
  $ANSIBLE_VAULT;1.1;AES256
  35343264376534336462346433336137343532303736363236393635333564346236313932616531
```

**Этап 3: Использование в плейбуке**

```yaml
- name: Настройка базы данных
  hosts: dbservers
  vars_files:
    - group_vars/all/vars.yml
  tasks:
    - name: Создание БД
      community.postgresql.postgresql_db:
        name: myapp
        login_user: "{{ db_user }}"
        login_password: "{{ db_password }}"  # Автоматически расшифровывается
```

**Преимущество**: в Git-диффе видны только добавленные/измененные обычные переменные, а зашифрованные значения отображаются как нечитаемые блоки.

### Сценарий 3: Использование меток (Vault ID)

Позволяет безопасно работать с секретами разных окружений (например, `dev` и `prod`) в одном запуске.

**Этап 1: Создание файлов паролей для разных окружений**

```bash
echo "DevVaultPass123" > .vault_pass_dev
echo "Pr0dV@ultS3cure!Pass" > .vault_pass_prod
chmod 600 .vault_pass_dev .vault_pass_prod
```

**Этап 2: Создание зашифрованных файлов с метками**

```bash
# Файл для dev-окружения
ansible-vault create --vault-id dev@.vault_pass_dev group_vars/dev/vault.yml

# Файл для prod-окружения
ansible-vault create --vault-id prod@.vault_pass_prod group_vars/prod/vault.yml
```

**Этап 3: Запуск плейбука с разными окружениями**

```bash
ansible-playbook site.yml \
  --vault-id dev@.vault_pass_dev \
  --vault-id prod@.vault_pass_prod
# → PLAY [all] ***********************************************************
# → TASK [Deploy to dev] *************************************************
# → ok: [dev-server]
# → TASK [Deploy to prod] ************************************************
# → ok: [prod-server]
# → PLAY RECAP ***********************************************************
# → dev-server  : ok=1  changed=0  unreachable=0  failed=0
# → prod-server : ok=1  changed=0  unreachable=0  failed=0
```

**Интерактивный ввод пароля** (альтернатива файлам):

```bash
ansible-playbook site.yml --vault-id dev@prompt --vault-id prod@prompt
# → Vault password for dev: (ввод пароля)
# → Vault password for prod: (ввод пароля)
```

### Сценарий 4: Ротация паролей (Rekey)

Необходима при компрометации пароля или в рамках регулярной политики безопасности.

**Этап 1: Смена пароля с использованием текущего файла**

```bash
ansible-vault rekey --vault-password-file old_pass group_vars/vault.yml
# → New Vault password: (введите новый пароль)
# → Confirm New Vault password: (повторите)
# → Rekey successful
```

**Этап 2: Смена с использованием Vault ID**

```bash
ansible-vault rekey \
  --vault-id prod@old_pass \
  --new-vault-id prod@new_pass \
  group_vars/vault.yml
# → New Vault password for prod: (введите новый пароль)
# → Confirm New Vault password: (повторите)
# → Rekey successful
```

**Этап 3: Массовая ротация**

```bash
# Ротация всех vault-файлов в group_vars
ansible-vault rekey --vault-password-file old_pass group_vars/*/vault.yml
# → Rekeying group_vars/all/vault.yml
# → New Vault password: (ввод пароля)
# → Confirm: (повтор)
# → Rekeying group_vars/dev/vault.yml
# → New Vault password: (тот же пароль или новый)
# → Confirm: (повтор)
```

**Этап 4: Верификация**

```bash
# Проверьте, что файлы расшифровываются новым паролем
ansible-vault view group_vars/vault.yml --vault-password-file new_pass
# → db_password: MySecretPassword
```

### Сценарий 5: Просмотр зашифрованного файла без расшифровки на диске

Безопасный способ чтения секретов без создания расшифрованных копий:

```bash
ansible-vault view group_vars/all/vault.yml --vault-password-file .vault_pass
# → db_password: MySecretPassword
# → api_key: 12345-abcde
```

### Сценарий 6: Проверка зашифрованного файла

Убедитесь, что файл действительно зашифрован:

```bash
ansible-vault view group_vars/all/vault.yml --vault-password-file .vault_pass
# Если файл не зашифрован — выведет содержимое без запроса пароля
# Если зашифрован — запросит пароль или выведет ошибку
```

### Сценарий 7: Шифрование существующего файла с Vault ID

Зашифровать уже существующий файл переменных с присвоением метки:

```bash
ansible-vault encrypt --vault-id dev@.vault_pass_dev group_vars/dev/vault.yml
```

## Проверка работоспособности

После настройки Vault убедитесь в корректной работе:

1. **Проверка зашифрования**:
    ```bash
    # Создайте тестовый файл
    ansible-vault create test_vault.yml --vault-password-file .vault_pass
    # Проверьте, что он зашифрован
    head -1 test_vault.yml
    # → $ANSIBLE_VAULT;1.1;AES256 (или 1.2;AES256;label)
    ```

2. **Проверка расшифровки**:
    ```bash
    ansible-vault view test_vault.yml --vault-password-file .vault_pass
    # → Должно показать содержимое без ошибок
    ```

3. **Проверка работы с плейбуком**:
    ```bash
    ansible-playbook --check --diff test_playbook.yml --vault-password-file .vault_pass
    # → Должен выполнить check mode без ошибок Vault
    ```

4. **Проверка Vault ID**:
    ```bash
    ansible-playbook site.yml --vault-id dev@.vault_pass_dev --vault-id prod@.vault_pass_prod -v
    # → В выводе будет видно, какой Vault ID используется
    ```

## Устранение неполадок

### Ошибка: `Attempting to decrypt but no vault secrets found`

**Причина**: не указан пароль для Vault или не используется нужный Vault ID.

**Решение**:
```bash
# Укажите пароль через флаг
ansible-playbook site.yml --vault-password-file .vault_pass

# Или через переменную окружения
export ANSIBLE_VAULT_PASSWORD_FILE=.vault_pass
ansible-playbook site.yml

# Или через Vault ID
ansible-playbook site.yml --vault-id dev@.vault_pass_dev
```

### Ошибка: `Decryption failed`

**Причина**: неверный пароль или неверный Vault ID для данного файла.

**Решение**:
```bash
# Попробуйте все доступные пароли
ansible-playbook site.yml --vault-id dev@.vault_pass_dev --vault-id prod@.vault_pass_prod

# Проверьте Vault ID в заголовке файла
head -1 group_vars/all/vault.yml
# → $ANSIBLE_VAULT;1.2;AES256;prod (这意味着 нужен пароль для "prod")
```

### Ошибка: `InsecureWorldReadablePermissions`

**Причина**: файл пароля доступен другим пользователям.

**Решение**:
```bash
chmod 600 .vault_pass
ls -la .vault_pass
# → -rw------- 1 user user ... .vault_pass
```

### Ошибка: `Vault password file '...' not found`

**Причина**: указан несуществующий файл пароля.

**Решение**:
```bash
# Проверьте путь
ls -la .vault_pass

# Проверьте конфигурацию
ansible-config dump --defaults | grep vault_password_file
```

### Ошибка: `ERROR! A vault password is required to use Ansible's '--vault-id' option`

**Причина**: Vault ID указан без указания способа получения пароля.

**Решение**:
```bash
# Укажите пароль для конкретного Vault ID
ansible-playbook site.yml --vault-id dev@.vault_pass_dev

# Или используйте интерактивный ввод
ansible-playbook site.yml --vault-id dev@prompt
```

### Ошибка: `ERROR! the vault password file '.vault_pass' does not exist`

**Причина**: файл пароля не найден по указанному пути.

**Решение**:
```bash
# Проверьте текущую директорию
pwd

# Создайте файл пароля
echo "MyVaultPassword" > .vault_pass
chmod 600 .vault_pass
```

### Проблема: Секреты видны в логах

**Причина**: переменные с зашифрованными значениями выводятся в STDOUT при отладке.

**Решение**: используйте директиву `no_log: true` в задачах:
```yaml
- name: Установка пароля БД
  mysql_user:
    name: admin
    password: "{{ db_password }}"
  no_log: true
```

### Проблема: `ansible-vault edit` оставляет временные файлы

**Причина**: после аварийного завершения или при использовании общего сервера временные файлы могут остаться.

**Решение**:
```bash
# Проверьте временные файлы
ls -la /tmp/ansible*

# Настройте защищенную директорию для временных файлов
export TMPDIR=~/.tmp
mkdir -p $TMPDIR
chmod 700 $TMPDIR
```

## Граничные случаи и ограничения

### Смешанные файлы (plaintext + vault)

Файл может содержать как обычные, так и зашифрованные переменные:
```yaml
# Обычная переменная
db_host: localhost

# Зашифрованная переменная (inline vault)
db_password: !vault |
  $ANSIBLE_VAULT;1.1;AES256
  353432...
```

### Строгий режим Vault ID (`vault_id_match`)

По умолчанию Ansible пытается все пароли до первого совпадения. Включите строгий режим в `ansible.cfg`:
```ini
[defaults]
vault_id_match = True
```
При включении Ansible будет использовать только тот пароль, чей Vault ID точно совпадает с меткой в файле.

### Ограничение длины пароля

Ansible Vault не накладывает ограничений на длину пароля, но слишком короткие пароли (< 8 символов) уязвимы к атаке методом полного перебора. Рекомендуется использовать пароли длиной не менее 16 символов.

### Формат заголовков

- `$ANSIBLE_VAULT;1.1;AES256` — классический формат (Ansible 1.5+)
- `$ANSIBLE_VAULT;1.2;AES256;label` — формат с Vault ID (Ansible 2.4+)

Файлы без заголовка Vault считаются обычными YAML-файлами и не шифруются.

### Кроссплатформенность

Vault-файлы, созданные в Linux, корректно расшифровываются в macOS и наоборот, при условии использования одной и той же версии Ansible и совместимого алгоритма (AES-256).

### Лимиты производительности

При расшифровке большого количества Vault-файлов (более 100) может наблюдаться задержка из-за вычислений PBKDF2. В этом случае рассмотрите использование Vault ID для кэширования паролей или внешних менеджеров секретов.

## Дополнительная информация

### Справочник переменных окружения

| Переменная | Описание | Пример |
|------------|----------|--------|
| `ANSIBLE_VAULT_PASSWORD_FILE` | Путь к файлу пароля по умолчанию | `export ANSIBLE_VAULT_PASSWORD_FILE=~/.vault_pass` |
| `ANSIBLE_VAULT_IDentities` | Список Vault ID через запятую | `export ANSIBLE_VAULT_IDentities="dev@~/.vault_dev,prod@~/.vault_prod"` |
| `EDITOR` | Системный редактор для `ansible-vault edit` | `export EDITOR=nano` |
| `TMPDIR` | Директория для временных файлов | `export TMPDIR=~/.tmp` |

### Структура типичного проекта

```
project/
├── ansible.cfg                  # vault_password_file = .vault_pass
├── .vault_pass                  # Пароль (в .gitignore)
├── .vault_pass_dev              # Пароль dev-окружения (в .gitignore)
├── .vault_pass_prod             # Пароль prod-окружения (в .gitignore)
├── .gitignore                   # Содержит .vault_pass*
├── group_vars/
│   ├── all/
│   │   ├── vars.yml             # Обычные переменные
│   │   └── vault.yml            # Зашифрованные секреты
│   ├── dev/
│   │   ├── vars.yml
│   │   └── vault.yml
│   └── prod/
│       ├── vars.yml
│       └── vault.yml
├── host_vars/
│   └── server1/
│       └── vault.yml
├── roles/
│   └── app/
│       └── defaults/
│           └── main.yml         # Может содержать inline vault
└── site.yml
```

### Краткая сводка лучших практик

- Храните зашифрованные файлы в Git, но пароли — никогда
- Используйте `encrypt_string` вместо целых файлов для минимизации зашифрованного контента
- Всегда добавляйте `no_log: true` к задачам с секретами
- Разделяйте пароли для разных окружений через Vault ID
- Регулярно ротируйте пароли (минимум раз в квартал)
- Ограничивайте права доступа к файлам паролей (`chmod 600`)
- Используйте `ansible-vault view` вместо `decrypt` для чтения секретов

Детальные рекомендации — см. [Лучшие практики по безопасности](./best_practices.md).

### Углубленные темы
- [Лучшие практики по безопасности](./best_practices.md) — использование `no_log`, интеграция с CI/CD и линтинг.
- [Управление паролями и источниками](./passwords.md) — скрипты для получения паролей и внешние менеджеры.
- [Использование нескольких хранилищ (Multi-Vault)](./multi_vault.md) — детальная работа с Vault ID и метками.

### Технические детали
- [Практические примеры использования](./examples.md) — готовые сценарии для реальных задач.
- [Алгоритмы и криптография](./algorithms.md) — подробности работы AES-256-CTR и HMAC-SHA256.
