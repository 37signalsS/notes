# Ansible Vault: Основы

## Определения

- **Ansible Vault**: Встроенный в Ansible механизм шифрования секретов (паролей, ключей API, сертификатов) для безопасного хранения чувствительных данных в системе контроля версий вместе с кодом автоматизации.
- **Хранилище (Vault)**: Зашифрованный YAML-файл или отдельная зашифрованная строка, содержащие секреты.
- **Заголовок Vault**: Первая строка зашифрованного файла, определяющая версию формата и алгоритм: `$ANSIBLE_VAULT;1.1;AES256` или `$ANSIBLE_VAULT;1.2;AES256;label`.
- **Vault ID**: Текстовая метка (например, `dev`, `prod`), связывающая зашифрованный файл с конкретным паролем или источником пароля. Поддерживается с Ansible 2.4+.
- **EncryptedString (ansible-core 2.19+)**: Внутренний тип данных Ansible для автоматического отслеживания зашифрованных значений и предотвращения их случайного вывода в логи (Data Tagging).
- **AES-256-CTR**: Стандартный алгоритм симметричного шифрования, используемый Ansible Vault для защиты данных.
- **PBKDF2-HMAC-SHA256**: Функция формирования криптографического ключа из мастер-пароля. Ansible использует 10 000 итераций хеширования для защиты от перебора.
- **HMAC-SHA256**: Механизм проверки целостности зашифрованных данных. Любая модификация файла без знания пароля обнаруживается при расшифровке.

## Основные концепции

### Архитектура и принципы работы

Ansible Vault использует схему **Encrypt-then-MAC**: сначала данные шифруются алгоритмом AES-256-CTR, затем вычисляется HMAC-SHA256 от шифротекста. Это гарантирует, что любые изменения в зашифрованном файле будут обнаружены ДО попытки расшифровки.

```
Планиновый цикл работы:
1. Чтение файла → проверка заголовка Vault
2. Извлечение соли (Salt, 32 байта) и Vault ID из заголовка
3. Деривация ключа: PBKDF2-HMAC-SHA256 (10 000 итераций) → 80 байт ключевого материала
   - 0-31 байт: ключ шифрования AES-256
   - 32-63 байт: ключ HMAC-SHA256
   - 64-79 байт: вектор инициализации (IV) для CTR
4. Проверка HMAC целостности
5. Расшифровка AES-256-CTR → возврат plaintext в YAML-парсер
6. Пометка значений как EncryptedString (ansible-core 2.19+)
```

**Безопасность выполнения:** Даже зашифрованные переменные могут попасть в логи в открытом виде при отладке или ошибках. Для защиты всегда используйте директиву `no_log: true` в задачах, работающих с секретами.

### Версии формата заголовков

- `$ANSIBLE_VAULT;1.1;AES256`: Классический формат (Ansible 1.5+). Поддерживает только один пароль; при расшифровке Ansible перебирает все предоставленные пароли до первого совпадения.
- `$ANSIBLE_VAULT;1.2;AES256;label`: Современный формат (Ansible 2.4+). Содержит метку Vault ID, что позволяет мгновенно выбрать нужный пароль. Рекомендуется для всех новых проектов.

### Когда зашифрованный файл становится открытым

Зашифрованные данные остаются зашифрованными после выполнения плейбука, но есть одно исключение. Если зашифрованный файл передан в параметр `src` модулей `copy`, `template`, `unarchive`, `script` или `assemble`, Ansible расшифрует его, и на целевой машине файл окажется **в открытом виде**.

Это не уязвимость, а задокументированное поведение: так вы можете хранить конфигурацию или шаблон в репозитории зашифрованным (чтобы не раскрывать детали конфигурации), а на сервер отдавать его уже расшифрованным, чтобы локальные пользователи и процессы могли его прочитать.

```yaml
# templates/app.conf.j2 зашифрован: Ansible расшифрует его перед рендерингом
- name: Развернуть зашифрованный шаблон
  ansible.builtin.template:
    src: app.conf.j2          # файл зашифрован ansible-vault
    dest: /etc/app/app.conf   # на хосте — открытый текст
    owner: root
    group: app
    mode: '0600'
  no_log: true
```

**Обязательные меры при таком подходе:**

- ограничить права на целевом файле (`mode: '0600'`) и владельца;
- для особо чувствительных конфигов предпочитать `tmpfs` вместо диска;
- помнить, что `ansible-vault decrypt` на хосте даёт тот же открытый текст, но ещё и оставляет файл на диске — `template` с `src` предпочтительнее.

Полный список модулей с таким поведением: `copy`, `template`, `unarchive`, `script`, `assemble`.

### Ограничения безопасности

Количество итераций PBKDF2 (10 000) является историческим компромиссом между безопасностью и скоростью работы. По современным меркам (OWASP 2025 — от 600 000 итераций) это значение считается **низким**. Единственный надежный способ компенсировать это — использование мастер-паролей длиной **от 20 символов** с высокой энтропией.

**Формат 1.0** (`$ANSIBLE_VAULT;1.0;AES256`) поддерживается только для чтения и автоматически конвертируется в 1.1 при следующей записи. Шифровать новые данные в формате 1.0 нельзя.

### Кроссплатформенность

Vault-файлы, созданные в Linux, корректно расшифровываются в macOS и Windows (при условии использования совместимых версий Python и ansible-core).

### Производительность

При расшифровке большого количества Vault-файлов (>100) может наблюдаться задержка из-за вычислений PBKDF2 (~50-100 мс на файл для современного CPU). Для оптимизации используйте формат 1.2 с Vault ID и `vault_id_match = True`.

## Предварительные требования

- **Ansible (ansible-core)**: версия 2.4 или выше (текущая стабильная версия — 2.20+, рекомендуется последняя поддерживаемая версия). Проверка версии: `ansible --version`
- **Системный редактор**: команда `ansible-vault edit` использует переменную окружения `$EDITOR` (по умолчанию `vi`). Установите удобный редактор: `export EDITOR=nano` или `export EDITOR=code --wait`
- **Права доступа**: файлы паролей должны быть доступны только владельцу (`chmod 600 .vault_pass`). Нарушение прав доступа приведет к ошибке `InsecureWorldReadablePermissions`
- **Git**: для использования Vault в CI/CD добавьте файлы паролей в `.gitignore`
- **Операционная память**: при работе с `ansible-vault edit` временные файлы создаются в оперативной памяти (если ОС поддерживает) или в `$TMPDIR`. На общих серверах убедитесь, что `$TMPDIR` указывает на защищенную директорию

## Конфигурация

### `ansible.cfg`

```ini
[defaults]
# Один пароль для всех vault-файлов
vault_password_file = ./.vault_pass

# Или список Vault ID для разных окружений
vault_identity_list = dev@.vault_pass_dev, prod@.vault_pass_prod

# Строгий режим Vault ID (только точное совпадение меток)
vault_id_match = True

# Метка по умолчанию, если она не указана явно
vault_identity = default

# Метка, которой шифровать по умолчанию (при нескольких Vault ID)
vault_encrypt_identity = prod
```

**Полный справочник опций секции `[defaults]`:**

| Опция в `ansible.cfg` | Переменная окружения | Назначение |
| :--- | :--- | :--- |
| `vault_password_file` | `ANSIBLE_VAULT_PASSWORD_FILE` | Файл или исполняемый скрипт с паролем для одного хранилища |
| `vault_identity_list` | `ANSIBLE_VAULT_IDENTITY_LIST` | Список хранилищ в формате `label@source`, через запятую. Эквивалент нескольких `--vault-id` |
| `vault_id_match` | `ANSIBLE_VAULT_ID_MATCH` | Если `True`, для расшифровки используется только пароль с совпадающей меткой. По умолчанию `False` |
| `vault_identity` | `ANSIBLE_VAULT_IDENTITY` | Метка по умолчанию для случаев, когда она не задана явно. Значение по умолчанию — `default` |
| `vault_encrypt_identity` | `ANSIBLE_VAULT_ENCRYPT_IDENTITY` | Метка, которой шифровать по умолчанию, если передано несколько `--vault-id`. Переопределяется флагом `--encrypt-vault-id` |

Проверить фактически применённые значения и их источник:

```bash
ansible-config dump --only-changed | grep -i vault
# → vault_password_file /path/to/.vault_pass None

ansible-config list | grep -i vault
# → DEFAULT_VAULT_IDENTITY_LIST (vault_identity_list) ... ['[]']
```

**Приоритет поиска:** При использовании нескольких Vault ID Ansible применяет логику «первого совпадения». Если файл зашифрован с меткой `prod`, но в конфиге первым указан `dev`, Ansible сначала попробует `dev`, поймет, что метка не совпадает, и перейдет к `prod`.

> **Важно:** При использовании файлов паролей обязательно ограничивайте права доступа (`chmod 600 .vault_pass`) и добавляйте их в `.gitignore`.

### Переменные окружения

| Переменная | Описание | Пример |
|------------|----------|--------|
| `ANSIBLE_VAULT_PASSWORD_FILE` | Путь к файлу или скрипту с паролем | `export ANSIBLE_VAULT_PASSWORD_FILE=~/.vault_pass` |
| `ANSIBLE_VAULT_IDENTITY_LIST` | Список Vault ID через запятую | `export ANSIBLE_VAULT_IDENTITY_LIST="dev@~/.vault_dev,prod@~/.vault_prod"` |
| `ANSIBLE_VAULT_IDENTITY` | Метка хранилища по умолчанию | `export ANSIBLE_VAULT_IDENTITY=dev` |
| `ANSIBLE_VAULT_ENCRYPT_IDENTITY` | Метка, которой шифровать по умолчанию | `export ANSIBLE_VAULT_ENCRYPT_IDENTITY=prod` |
| `ANSIBLE_VAULT_ID_MATCH` | Строгое соответствие меток (аналог `vault_id_match`) | `export ANSIBLE_VAULT_ID_MATCH=True` |
| `EDITOR` | Системный редактор для `ansible-vault edit` | `export EDITOR=nano` |
| `TMPDIR` | Диретория для временных файлов | `export TMPDIR=~/.tmp` |

## Операции и команды

Все команды поддерживают аргумент `--vault-id` или `--vault-password-file`. При использовании нескольких Vault ID может потребоваться `--encrypt-vault-id`.

### Полный справочник флагов

| Флаг | Применимость | Назначение |
| :--- | :--- | :--- |
| `--vault-id <label>@<source>` | все команды | Метка и источник пароля. `source` — путь к файлу, исполняемый скрипт, `prompt` или `@prompt`. Можно указать несколько раз |
| `--vault-password-file`, `--vault-pass-file` | все команды | Файл или скрипт с паролем без указания метки. Эквивалент `--vault-id @<source>` |
| `-J`, `--ask-vault-password`, `--ask-vault-pass` | все команды | Интерактивный запрос пароля. Эквивалент `--vault-id @prompt` |
| `--encrypt-vault-id <label>` | `create`, `edit`, `encrypt`, `encrypt_string`, `rekey` | Метка, которой шифровать. Обязателен, если передано несколько `--vault-id`. Переопределяет `vault_encrypt_identity` |
| `--new-vault-id <label>@<source>` | `rekey` | Новая метка и источник для перешифровки |
| `--new-vault-password-file <path>` | `rekey` | Новый файл пароля для перешифровки |
| `--output <file>`, `--output -` | `decrypt`, `encrypt`, `encrypt_string` | Записать результат в файл или в stdout вместо изменения исходного |
| `--name`, `-n` | `encrypt_string` | Имя переменной для формирования готовой YAML-структуры |
| `--stdin-name <var>` | `encrypt_string` | Имя переменной, когда секрет читается из stdin. Переключает режим на чтение из stdin |
| `--show-input` | `encrypt_string` | Не скрывать ввод при интерактивном запросе секрета. По умолчанию ввод скрыт |
| `--prompt`, `-p` | `encrypt_string` | Запросить имя переменной и секрет интерактивно вместо аргумента командной строки. Несовместим с чтением из stdin |
| `--skip-tty-check` | `create`, `edit` | Разрешить открытие редактора без привязанного TTY (CI, cron) |

### `ansible-vault create <file>`


Создает новый зашифрованный файл и открывает его в редакторе:

```bash
# Обычное создание
ansible-vault create group_vars/all/vault.yml
# → Vault password: (ввод пароля)
# → Откроется редактор для ввода секретов

# С указанием Vault ID
ansible-vault create --vault-id prod@.vault_pass group_vars/prod/vault.yml

# С явным указанием метки шифрования (при нескольких Vault ID)
ansible-vault create --encrypt-vault-id prod --vault-id prod@.vault_pass group_vars/prod/vault.yml
```

### `ansible-vault edit <file>`

Редактирует зашифрованный файл. Ansible расшифровывает его во временный файл в оперативной памяти (если поддерживается ОС) и открывает в системном редакторе:

```bash
ansible-vault edit group_vars/all/vault.yml
# → Vault password: (ввод пароля)
# → Откроется редактор с расшифрованным содержимым
# → После сохранения — автоматически зашифрует обратно
```

**Важно**: на общих серверах временные файлы создаются в `$TMPDIR` или `/tmp`. Убедитесь, что директория защищена.

### `ansible-vault encrypt <file>`

Зашифровывает один или несколько существующих файлов:

```bash
# Один файл
ansible-vault encrypt group_vars/all/vault.yml

# Несколько файлов по маске
ansible-vault encrypt group_vars/*.yml

# С указанием Vault ID
ansible-vault encrypt --vault-id dev@.vault_pass_dev group_vars/dev/vault.yml

# С явным указанием метки шифрования
ansible-vault encrypt --encrypt-vault-id dev --vault-id dev@.vault_pass_dev group_vars/dev/vault.yml
```

### `ansible-vault decrypt <file>`

Полностью расшифровывает файл, удалив заголовок Vault:

```bash
ansible-vault decrypt group_vars/all/vault.yml
# → Vault password: (ввод пароля)
# → decryption successful
```

**Внимание:** После этой команды секреты окажутся в открытом виде на диске. Используйте только когда необходимо временно расшифровать файл.

### `ansible-vault view <file>`

Выводит содержимое в терминал (STDOUT). Безопаснее, чем `decrypt`, так как не оставляет расшифрованных данных в файловой системе:

```bash
ansible-vault view group_vars/all/vault.yml --vault-password-file .vault_pass
# → db_password: MySecretPassword
# → api_key: 12345-abcde
```

### `ansible-vault rekey <file>`

Изменяет пароль доступа или метку Vault ID:

```bash
# Смена пароля
ansible-vault rekey group_vars/all/vault.yml
# → Vault password: (текущий пароль)
# → New Vault password: (новый пароль)
# → Confirm New Vault password: (повтор)

# Смена Vault ID
ansible-vault rekey --vault-id prod@old_pass --new-vault-id prod@new_pass group_vars/vault.yml

# С использованием нового файла пароля
ansible-vault rekey --vault-id prod@old_pass --new-vault-password-file new_pass group_vars/vault.yml
```

**Важное ограничение:** `rekey` требует, чтобы файл был зашифрован **целиком, одним конвертом** — то есть начинался с заголовка `$ANSIBLE_VAULT;`. Под капотом команда читает всё содержимое файла и передаёт его в `decrypt_and_get_vault_id()`, поэтому частично зашифрованный файл (обычный YAML с отдельными inline-блоками `!vault` вперемешку с открытыми значениями) перешифровать нельзя: расшифровке подвергается весь файл, а не отдельные значения.

Из этого следуют два разных случая:

| Ситуация | Можно ли `rekey` | Почему |
| :--- | :--- | :--- |
| Файл целиком зашифрован (`group_vars/prod/vault.yml` начинается с `$ANSIBLE_VAULT;`) | Да | Весь файл — один конверт, `rekey` расшифровывает и шифрует его заново |
| Файл с inline-блоками `!vault` среди открытого YAML | Нет | Такой файл не является конвертом; попытка даст ошибку формата |
| Отдельное значение, созданное через `encrypt_string` | Нет | Механизма `rekey` для отдельных значений не существует; выборочной ротации по одному значению нет |

Практические следствия:

- держите секреты в **отдельных целиком зашифрованных файлах** — только их можно ротировать автоматизированно;
- `encrypt_string` удобен для единичных нестандартных случаев (например, токен в инвентаре), но такой секрет придётся ротировать вручную;
- если файл с inline-значениями нужно перевести на новый мастер-пароль, сначала расшифруйте его через `ansible-vault view`, сохраните открытые значения во временный файл **вне репозитория**, затем зашифруйте заново через `ansible-vault encrypt` и удалите временный файл.

> Массовая ротация: `find group_vars -name '*.yml' | xargs ansible-vault rekey --vault-id prod@old_pass --new-vault-id prod@new_pass`. Команда упадёт на любом незашифрованном или частично зашифрованном файле — сначала отфильтруйте список через `git grep -l '^\$ANSIBLE_VAULT' -- '*.yml'`.

### `ansible-vault encrypt_string`

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

# С явным указанием метки шифрования
ansible-vault encrypt_string 'ProdSecret' --name 'api_key' --vault-id prod@.vault_pass --encrypt-vault-id prod

# Интерактивный ввод секрета (безопасно — не попадает в историю shell)
ansible-vault encrypt_string --prompt
# → Variable name (enter for no name): api_key
# → String to encrypt (hidden):
# → api_key: !vault |
# →   $ANSIBLE_VAULT;1.1;AES256

# Чтение секрета из stdin без попадания в историю и аргументы процесса
echo -n 'letmein' | ansible-vault encrypt_string --vault-id dev@.vault_pass --stdin-name 'db_password'
# → Reading plaintext input from stdin.
# → db_password: !vault |
# →   $ANSIBLE_VAULT;1.1;AES256

# Вывод в stdout без изменения исходного файла
ansible-vault encrypt group_vars/all/vault.yml --output - | head -1
# → $ANSIBLE_VAULT;1.2;AES256;prod
```

**Утечка в историю shell.** Передача секрета аргументом командной строки (`ansible-vault encrypt_string 'MySecret'`) сохраняет его в `~/.bash_history` **и** делает видимым в списке процессов (`ps -ef`, `/proc/*/cmdline`) на всё время выполнения. Это относится и к переменным, если значение подставляется до кавычек. В продакшене используйте только три безопасных способа:

1. `--prompt` (или `-p`) — интерактивный ввод с скрытием echoed символов;
2. `stdin` — пайп из `echo`/`cat`/генератора пароля;
3. генерация на месте — `openssl rand -base64 32 | ansible-vault encrypt_string --stdin-name 'db_password'`.

`--prompt` запрашивает **два** значения: сначала имя переменной (`Variable name (enter for no name): `), затем сам секрет (`String to encrypt (hidden): `). Ввод скрыт по умолчанию; `--show-input` его показывает, что годится только для отладки на пустых значениях.

Режимы ввода взаимоисключающие. Ansible выбирает чтение из stdin, если в аргументах есть `-`, указан `--stdin-name` либо нет ни аргументов, ни `--prompt`. Совмещение `--prompt` с чтением из stdin приводит к ошибке:

```bash
ansible-vault encrypt_string --prompt --stdin-name 'db_password'
# → ERROR! The --prompt option is not supported if also reading input from stdin
```

Пустой ввод не шифруется: и пустой ответ на `--prompt`, и пустой stdin приводят к ошибке `not encrypting`, а не к зашифрованному пустому значению.

Тот же принцип действует для `ansible-vault create` и `edit` в CI: если в систему контроля версий попадает файл пароля, он там и останется, а `--ask-vault-pass` в CI бесполезен, потому что CI не интерактивен — используйте `--vault-password-file` с файлом-секретом из CI-хранилища.

**Полезные флаги**:
- `--name 'var_name'`, `-n`: Сразу сформировать готовую YAML-структуру.
- `--stdin-name 'var_name'`: То же, но для секрета, читаемого из stdin; переключает режим на stdin.
- `--prompt`, `-p`: Запросить имя переменной и секрет интерактивно (не попадает в историю shell).
- `--show-input`: Не скрывать ввод при интерактивном запросе (только для отладки).
- `--ask-vault-pass`: Запросить пароль интерактивно (относится к паролю, не к секрету).
- `--encrypt-vault-id <label>`: Явно указать метку для шифрования (при нескольких Vault ID).
- `--output <file>` / `--output -`: Записать результат в файл или stdout, не изменяя исходный.

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

### Сценарий 4: Верификация и тестирование

После настройки Vault убедитесь в корректной работы:

```bash
# 1. Создание тестового файла
ansible-vault create test_vault.yml --vault-password-file .vault_pass

# 2. Проверка заголовка
head -1 test_vault.yml
# → $ANSIBLE_VAULT;1.1;AES256 (или 1.2;AES256;label)

# 3. Проверка расшифровки
ansible-vault view test_vault.yml --vault-password-file .vault_pass
# → Должно показать содержимое без ошибок

# 4. Проверка работы с плейбуком
# ВНИМАНИЕ: --diff печатает аргументы модулей, поэтому вместе с секретами.
# Используйте его только в связке с no_log: true на задачах с секретами
# либо отключите вывод диффа для всего прогона.
ansible-playbook --check --diff test_playbook.yml --vault-password-file .vault_pass
# → Должен выполнить check mode без ошибок Vault

# Безопасная альтернатива для CI, где секреты передаются в модули:
# просто не включайте --diff. Флаг не задан — дифф не выводится.
ansible-playbook --check test_playbook.yml --vault-password-file .vault_pass
# → ok: [webserver1] (без диффа)

# 5. Удаление тестового файла
rm test_vault.yml
```

## Проверка работоспособности

### Базовые проверки

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
    # --diff печатает аргументы модулей, включая значения переменных.
    # Применяйте только вместе с no_log: true на задачах с секретами
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

**Причина**: неверный пароль или неверный Vault ID для данного файла. Сообщение неоднозначно — Ansible проверяет HMAC до расшифровки, но ключ HMAC выведен из пароля, поэтому повреждённый файл даёт ту же ошибку.

**Диагностика**: сначала сверьте метку в заголовке с переданным `vault_id`, затем проверьте целостность через `git diff` или повторное шифрование.

**Решение**:
```bash
# Попробуйте все доступные пароли
ansible-playbook site.yml --vault-id dev@.vault_pass_dev --vault-id prod@.vault_pass_prod

# Проверьте Vault ID в заголовке файла
head -1 group_vars/all/vault.yml
# → $ANSIBLE_VAULT;1.2;AES256;prod (это означает нужен пароль для "prod")
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

## Лучшие практики

### Базовый набор (SRE/Sysadmin)

- **Храните зашифрованные файлы в Git**, но пароли — никогда
- **Используйте `encrypt_string`** вместо целых файлов для минимизации зашифрованного контента и сохранения читаемости Git-диффов
- **Всегда добавляйте `no_log: true`** к задачам с секретами
- **Разделяйте пароли для разных окружений** через Vault ID
- **Регулярно ротируйте пароли** (минимум раз в квартал) с помощью `ansible-vault rekey`
- **Ограничивайте права доступа** к файлам паролей (`chmod 600`)
- **Используйте `ansible-vault view`** вместо `decrypt` для чтения секретов
- **Используйте пароли длиной не менее 20 символов** с высокой энтропией для компенсации 10 000 итераций PBKDF2
- **Включите строгий режим `vault_id_match = True`** в `ansible.cfg`
- **Всегда добавляйте файлы паролей в `.gitignore`**
- **Не передавайте пароли через `ANSIBLE_VAULT_PASSWORD`** — Ansible не поддерживает это из соображений безопасности (утечка через `ps aux`). Используйте только `ANSIBLE_VAULT_PASSWORD_FILE`.

### Для Sysadmin

- Настройте `$TMPDIR` на защищенную директорию при работе на shared Control Node
- Используйте `ansible-vault view` вместо `edit` для чтения секретов на production-хостах
- Добавьте `.vault_pass*` в глобальный `.gitignore` для всего окружения
- Настройте umask `0077` для автоматического ограничения прав на создаваемые файлы
- Используйте `ansible-config dump --defaults | grep vault` для аукта текущей конфигурации Vault

### Для SRE

- Внедрите политику ротации мастер-паролей (раз в квартал) и следите за ней через `ansible-vault rekey`
- Используйте `vault_id_match = True` для предотвращения случайного использования ключей не по назначению
- Настройте аудит: логируйте запуски плейбуков с Vault через `ANSIBLE_LOG_PATH`
- При компрометации пароля немедленно выполните массовую ротацию: `find group_vars -name "*.yml" | xargs ansible-vault rekey --vault-id old@source --new-vault-id new@source`
- Избегайте использования чувствительной информации в названиях меток Vault ID (они хранятся в открытом виде в заголовке файла)

## См. также

- [Управление паролями и источниками](./passwords.md) — скрипты для получения паролей и внешние менеджеры секретов.
- [Использование нескольких хранилищ (Multi-Vault)](./multi_vault.md) — детальная работа с Vault ID и метками.
- [Лучшие практики по безопасности](./best_practices.md) — векторы утечек, ротация, интеграция с CI/CD.
- [Программный доступ через Python API](./ansible-vault-api.md) — `VaultLib`, `VaultSecret`, шифрование и расшифровка из кода.
- [Алгоритмы и криптография](./algorithms.md) — подробности AES-256-CTR, HMAC-SHA256 и PBKDF2.

## Дополнительная информация

### Переменные окружения

Полный справочник переменных окружения и опций `ansible.cfg` приведен в секции [Конфигурация](#переменные-окружения) этого файла: `ANSIBLE_VAULT_PASSWORD_FILE`, `ANSIBLE_VAULT_IDENTITY_LIST`, `ANSIBLE_VAULT_IDENTITY`, `ANSIBLE_VAULT_ENCRYPT_IDENTITY`, `ANSIBLE_VAULT_ID_MATCH`, `EDITOR`, `TMPDIR`.

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

### Аудит и соответствие (Compliance)

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
   Пустой вывод — хороший знак. Плейсхолдеров вида `[VALUE_IS_ENCRYPTED]` в выводе не бывает: если grep что-то нашёл, значит в истории есть открытый секрет.

### Резервное копирование и восстановление

Vault-файлы можно безопасно хранить в Git, но файлы паролей — нет. Для disaster recovery:

1. **Резервное копирование**: Сохраните мастер-пароли в защищенном менеджере секретов (HashiCorp Vault, 1Password, Bitwarden) или на внешнем носителе в зашифрованном виде.
2. **Восстановление**: При утрате пароля файл восстановить невозможно (AES-256 устойчив к перебору). Восстанавливайте секреты из основного источника или запрашивайте у команды.
3. **Тестирование восстановления**: Периодически проверяйте возможность расшифровки всех Vault-файлов новым паролем.

### Ограничения и известные особенности

- **Временные файлы**: `ansible-vault edit` создает временные копии. На shared Control Node контролируйте `$TMPDIR` и права доступа.
- **Кэширование фактов**: обычный `set_fact` **не** попадает в кэш — Ansible сохраняет только факты, помеченные `cacheable: true`. Если секрет задан через `set_fact` с `cacheable: true`, его открытое значение попадёт в кэш на диске (JSON, pickle, redis) вместе со всем остальным. Секреты из vault не должны быть `cacheable`. Подробнее — [Лучшие практики по безопасности](./best_practices.md).
- **`--diff` и `--verbose`**: печатают аргументы модулей и значения переменных, то есть потенциально секреты. Применяйте только вместе с `no_log: true`.
- **Inline-переменные нельзя перешифровать**: `rekey` работает только с файлами. Массовая ротация требует, чтобы секреты лежали в отдельных зашифрованных файлах.
- **Расшифровка на целевом хосте**: `copy`, `template`, `unarchive`, `script`, `assemble` расшифровывают `src` — на хосте файл окажется в открытом виде.
- **Память**: секреты расшифровываются в память Control Node. Убедитесь, что у системы достаточно оперативной памяти для крупных инвентарей.
- **Редакторы**: Некоторые редакторы (VS Code, JetBrains) создают резервные файлы в том же каталоге. При использовании `ansible-vault edit` убедитесь, что резервные файлы не попадают в Git.
- **no_log и debug**: `no_log: true` скрывает вывод задачи, но не скрывает переменные, используемые в `register` или `debug` без `no_log`.
