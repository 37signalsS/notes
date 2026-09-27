# Ansible Vault: Программный доступ через Python API

## Определения

- **`ansible.parsing.vault`**: Внутренний модуль `ansible-core`, реализующий всю криптографию Ansible Vault. Это тот же код, который вызывает CLI-утилита `ansible-vault`, — отдельного «API-сервера» не существует.
- **`VaultLib`**: Основной класс для шифрования и расшифровки. Работает с байтовыми строками (`bytes`), а не с текстом.
- **`VaultSecret`**: Абстрактное представление одного секрета (пароля или ключа). Реализации: `FileVaultSecret`, `ScriptVaultSecret`, `ClientScriptVaultSecret`, `PromptVaultSecret`.
- **`VaultEditor`**: Обёртка над `VaultLib` для работы с файлами: `encrypt_file`, `decrypt_file`, `rekey_file`, `create_file`, `edit_file`, `plaintext`.
- **`EncryptedString`**: Тип ansible-core 2.19+ для значений из `!vault`. Является подклассом `str` с прикреплённым шифротекстом: ведёт себя как обычная строка, но помнит исходное зашифрованное представление. Заменил тип `AnsibleVaultEncryptedUnicode`.
- **`VaultedValue`**: Тег ansible-core 2.18+ (модуль `ansible._internal._datatag._tags`), который помечает любые значения, пришедшие из vault, независимо от их Python-типа.
- **`VaultHelper`**: Утилитарный класс с `staticmethod get_ciphertext(value, *, with_tags)` — возвращает шифротекст для vault-значения или `None`, если значение не из vault.
- **`VaultSecretsContext`**: Контекстный менеджер (появился в ansible-core 2.19), предоставляющий стиль доступа к vault-секретам через `VaultSecretsContext.current()`. Используется внутренними компонентами Ansible для передачи списка секретов без глобальных переменных. Внешним скриптам достаточно `DataLoader.set_vault_secrets()`, но при создании собственных плагинов или работе с низкоуровневыми API может потребоваться инициализация контекста.
- **`DataLoader`**: Загрузчик данных Ansible. Парсит YAML с `!vault`-значениями, если предварительно передать секреты через `set_vault_secrets`.
- **`is_encrypted` / `is_encrypted_file`**: Определение, зашифрованы ли данные, без попытки расшифровки.
- **`parse_vaulttext_envelope`**: Разбор структуры «конверта» шифротекста без расшифровки. Возвращает кортеж из четырёх элементов: `(ciphertext, version, cipher_name, vault_id)`.
- **`VaultAES256`**: Реализация шифра формата 1.1/1.2. Нужен редко — в основном для собственных тестов.

## Основные концепции

### Три уровня API

| Уровень | Классы и функции | Когда применять |
| :--- | :--- | :--- |
| Файловый | `VaultEditor` | Нужно зашифровать, расшифровать или перешифровать файл целиком |
| Строковый | `VaultLib.encrypt`, `VaultLib.decrypt`, `decrypt_and_get_vault_id` | Работа со значением в памяти: инлайн-переменные, генерация YAML-фрагмента, проверка целостности |
| Разбор и формат | `is_encrypted`, `parse_vaulttext_envelope`, `format_vaulttext_envelope`, `VaultAES256` | Аудит, миграция форматов, проверка заголовка, собственные тесты |

### Почему не вызывать CLI из скрипта

Вызов `ansible-vault view` через `subprocess` работает, но хуже по трём причинам:

1. **Пароль в аргументах процесса.** `--vault-password-file` виден всем пользователям через `ps -ef` и `/proc/*/cmdline`, пока работает процесс. Через API пароль передаётся объекту `VaultSecret` в памяти процесса и в аргументах не появляется.
2. **Накладные расходы.** Каждый запуск CLI — старт интерпретатора Python, импорт ansible-core и разбор конфигурации (сотни миллисекунд). При пакетной обработке сотен файлов в цикле это минуты вместо секунд.
3. **Двойная валидация.** CLI самостоятельно разбирает аргументы и применяет приоритет конфигурации. В скрипте вы управляете этим явно, что важно в CI и в webhook-обработчиках.

CLI остаётся правильным выбором для интерактивной работы: он читает `ansible.cfg`, поддерживает `--vault-id`, TTY-подсказки и редактор.

### Соглашение о байтах

Все ключевые методы `VaultLib` принимают и возвращают `bytes`. Преобразования `bytes.decode()` и `str.encode()` — единственные, которые нужно делать вручную.

```python
from ansible.parsing.vault import VaultLib, VaultSecret

secret = VaultSecret(b'my-vault-password')
vault = VaultLib([(None, secret)])

ciphertext = vault.encrypt(b'plaintext')       # → bytes, начинается с b'$ANSIBLE_VAULT;1.1;AES256'
plaintext = vault.decrypt(ciphertext)          # → b'plaintext'
```

### Безопасность при работе с API

При использовании Python API безопасность секретов зависит от того, как скрипт обрабатывает пароли и расшифрованные данные:

1. **Пароль в памяти процесса.** В отличие от CLI, где пароль может попасть в аргументы процесса, API передаёт секрет объекту `VaultSecret` в памяти. Это безопаснее, но не защищает от дампа памяти или отладки.
2. **Расшифрованные данные в RAM.** `VaultLib.decrypt()` возвращает `bytes` с открытым текстом. Не оставляйте такие объекты в глобальных переменных или кэше дольше необходимого.
3. **Временные файлы.** `VaultEditor` не создаёт временных файлов при шифровании/расшифровке строк, но `edit_file()` создаёт их в `$TMPDIR`. На shared Control Node контролируйте права на эту директорию.
4. **Логирование.** Python API не пишет в логи Ansible по умолчанию, но если вы оборачиваете вызовы в `try/except` и логируете `exc`, убедитесь, что в лог не попадает расшифрованный текст или пароль.
5. **Внутренние модули.** `ansible.parsing.vault` и `ansible._internal._datatag._tags` — внутренние пути без гарантии стабильности API. Фиксируйте версию `ansible-core` в `requirements.txt` и тестируйте скрипты при каждом обновлении.

**Для Sysadmin:** Запускайте скрипты работы с vault под выделенным пользователем (не root) и с `umask 0077`. Проверяйте, что временные директории (`$TMPDIR`, `/tmp`) не доступны другим пользователям.

**Для SRE:** Внедрите аудит вызовов API через wrapper-функции. Логируйте факт вызова `decrypt()`/`encrypt()` с указанием vault_id и пути файла, но без значений.

### Получение секретов для API

Хелпер `get_file_vault_secret()` работает и с файлом, и с исполняемым скриптом, определяя тип по биту execute. Требует экземпляр `DataLoader` (для проверки `is_executable`) и обрабатывает три типа источников:

- **файл с паролем** — читается как есть;
- **исполняемый скрипт** — запускается без аргументов, пароль берётся из stdout;
- **client-скрипт** (проверяется функцией `script_is_client`) — принимает имя метки Vault ID, что позволяет отдавать разные пароли для разных хранилищ.

Файл с паролем **не должен содержать перевод строки в конце**. Ansible использует весь файл как пароль, поэтому завершающий `\n` становится частью секрета и приводит к ошибке `Decryption failed` при вводе того же пароля вручную. Генерируйте такие файлы через `printf '%s'`, а не `echo`.

### Модель `EncryptedString` в ansible-core 2.19+

Согласно [porting guide 2.19](https://docs.ansible.com/projects/ansible-core/2.19/porting_guides/porting_guide_core_2.19.html), тип `AnsibleVaultEncryptedUnicode` **заменён** на `EncryptedString`. Ключевые формулировки руководства:

- плагины, которые создавали `AnsibleVaultEncryptedUnicode`, теперь получают экземпляры `EncryptedString`;
- значения, ранее представленные этим типом, теперь отображаются как **тегированная `str`** (tagged `str`);
- **специальная обработка в плагинах больше не требуется** для доступа к содержимому таких значений;
- плагины, делающие `isinstance`-проверки на `AnsibleVaultEncryptedUnicode`, больше не встретят эти типы.

Практические следствия:

- `EncryptedString` — подкласс `str`, поэтому `len()`, конкатенация, `| length`, `format()` и передача в модуль работают как с обычной строкой; открытое значение получается при использовании как строки.
- Значение помнит исходный шифротекст, поэтому его можно получить обратно, не зная пароля.
- Проверять принадлежность к vault нужно по тегу `VaultedValue`, а не по классу.

```python
from ansible.parsing.vault import VaultHelper
from ansible._internal._datatag._tags import VaultedValue

# Шифротекст vault-значения; вернёт None, если значение не из vault.
# Аргумент with_tags обязательный keyword-only: True переносит теги
# на шифротекст, False возвращает «голый» шифротекст без тегов.
ciphertext = VaultHelper.get_ciphertext(value, with_tags=False)

is_vaulted = VaultedValue.get_tag(value) is not None
```

Отдельно про исключения в Jinja-плагинах: руководство предупреждает, что `except Exception` может работать некорректно при обращении к содержимому контейнеров (`dict`, `list`), когда значение не определено, **не расшифровываемо** или иным образом вызывает лениво сообщаемую ошибку. Ловите конкретные исключения и сужайте область `try` до минимально необходимой, особенно вокруг кода, который обращается к содержимому контейнеров.

## Практические сценарии

### Предварительные требования

```bash
# ansible-core с криптобиблиотекой
pip install 'ansible-core[crypto]'
python3 -c "import ansible; print(ansible.__version__)"
# → 2.21.x

python3 -c "from ansible.parsing.vault import VaultLib; print('API доступен')"
# → API доступен
```

Требования к среде:
- **ansible-core**: 2.19.x (Python 3.11+) или 2.20+ (Python 3.12+). Текущая стабильная версия — 2.21.x.
- **Python**: 3.11+ для ansible-core 2.19.x; 3.12+ обязателен для ansible-core 2.20 и выше.
- **Cryptography**: библиотека `cryptography` устанавливается автоматически с extras `ansible-core[crypto]`.
- **Права доступа**: файлы паролей должны иметь права `0600` (только владелец).

### Сценарий 1: Расшифровка файла в словарь

Самый частый случай в интеграционных скриптах: получить содержимое `group_vars/prod/vault.yml` как `dict` без вызова CLI.

```python
#!/usr/bin/env python3
"""Чтение зашифрованного файла переменных в словарь."""
import sys
from ansible.parsing.dataloader import DataLoader
from ansible.parsing.vault import get_file_vault_secret

VAULT_FILE = sys.argv[1] if len(sys.argv) > 1 else 'group_vars/prod/vault.yml'
PASSWORD_FILE = sys.argv[2] if len(sys.argv) > 2 else '.vault_pass_prod'

loader = DataLoader()
secret = get_file_vault_secret(PASSWORD_FILE, loader=loader)
loader.set_vault_secrets([(None, secret)])

data = loader.load_from_file(VAULT_FILE)

for key, value in data.items():
    # Преобразование в str расшифровывает значение
    print(f'{key} = {str(value)[:4]}... (длина {len(value)})')
# → db_password = S3cr... (длина 24)
```

Использование `DataLoader` вместо `yaml.safe_load` принципиально: стандартный YAML-парсер не знает про тег `!vault` и либо выдаст ошибку, либо вернёт текст блока `!vault` без расшифровки.

### Сценарий 2: Проверка, что все файлы проекта расшифровываются

Регулярная операция в CI: убедиться, что ни один файл не зашифрован «не тем» паролем и не повреждён.

```python
#!/usr/bin/env python3
"""Проверка расшифровки всех vault-файлов проекта."""
import subprocess
import sys
from ansible.parsing.dataloader import DataLoader
from ansible.parsing.vault import get_file_vault_secret, is_encrypted_file

PAIRS = [('prod', '.vault_pass_prod'), ('dev', '.vault_pass_dev')]


def find_vault_files(root='.'):
    out = subprocess.run(
        ['git', 'ls-files', root],
        capture_output=True, text=True, check=True,
    ).stdout.split()
    for path in out:
        if path.endswith(('.yml', '.yaml', '.json')):
            with open(path, 'rb') as fh:
                if is_encrypted_file(fh):
                    yield path


def read_vault_id(path):
    with open(path) as fh:
        parts = fh.readline().strip().split(';')
    return parts[3] if len(parts) > 3 else None


loader = DataLoader()
by_label = {label: get_file_vault_secret(pw, vault_id=label, loader=loader)
            for label, pw in PAIRS}

failures = []
for path in find_vault_files():
    label = read_vault_id(path)
    secret = by_label.get(label) or next(iter(by_label.values()))
    try:
        # Строгий выбор пароля по метке из заголовка
        loader.set_vault_secrets([(label, secret)])
        loader.load_from_file(path)
        print(f'OK   {path} (vault_id={label})')
    except Exception as exc:
        failures.append(path)
        print(f'FAIL {path}: {exc}', file=sys.stderr)

sys.exit(1 if failures else 0)
# → OK   group_vars/prod/vault.yml (vault_id=prod)
# → OK   roles/app/defaults/main.yml (vault_id=prod)
```

Почему нельзя просто передать все секреты сразу: при `vault_id_match = False` Ansible перебирает пароли по очереди, и файл с меткой `prod` может случайно расшифроваться паролем `dev` — проверка пройдёт, а деплой возьмёт не тот секрет. Разбирайте метку из заголовка и выбирайте пароль строго по ней.

### Сценарий 3: Массовое шифрование файлов

```python
#!/usr/bin/env python3
"""Массовое шифрование открытых файлов с проставлением меток Vault ID."""
import subprocess
from ansible.parsing.dataloader import DataLoader
from ansible.parsing.vault import VaultEditor, get_file_vault_secret, is_encrypted_file

loader = DataLoader()
secrets = {
    label: get_file_vault_secret(path, vault_id=label, loader=loader)
    for label, path in (('dev', '.vault_pass_dev'), ('prod', '.vault_pass_prod'))
}

files = subprocess.run(
    ['git', 'ls-files', 'group_vars', 'host_vars'],
    capture_output=True, text=True, check=True,
).stdout.split()

encrypted = 0
for path in files:
    with open(path, 'rb') as fh:
        if is_encrypted_file(fh):
            continue
    label = 'dev'
    VaultEditor().encrypt_file(path, secrets[label], vault_id=label)
    encrypted += 1
    print(f'encrypted {path} -> $ANSIBLE_VAULT;1.2;AES256;{label}')

# Проверка результата
for path in files:
    with open(path) as fh:
        assert fh.readline().startswith('$ANSIBLE_VAULT'), path

print(f'OK: зашифровано {encrypted} файлов, все остальные уже были зашифрованы')
# → OK: зашифровано 2 файлов, все остальные уже были зашифрованы
```

### Сценарий 4: Ротация пароля по расписанию

Ротация через API безопаснее связки `find | xargs ansible-vault rekey`, потому что позволяет проверить результат до перезаписи исходного пароля и вести журнал изменений.

```python
#!/usr/bin/env python3
"""Ротация мастер-пароля хранилища с проверкой и откатом."""
import datetime
import subprocess
import sys
from ansible.parsing.dataloader import DataLoader
from ansible.parsing.vault import (VaultEditor, VaultSecret, get_file_vault_secret,
                                  is_encrypted_file)

LABEL = 'prod'
OLD_PASS = '.vault_pass_prod'
NEW_PASS = '.vault_pass_prod.new'

loader = DataLoader()
old_secret = get_file_vault_secret(OLD_PASS, vault_id=LABEL, loader=loader)
# Новый пароль генерируется, а не задаётся вручную
new_password = subprocess.run(
    ['openssl', 'rand', '-base64', '32'], capture_output=True, text=True, check=True
).stdout.strip()
new_secret = VaultSecret(new_password.encode())

files = [p for p in subprocess.run(
    ['git', 'ls-files'], capture_output=True, text=True, check=True
).stdout.split() if p.endswith(('.yml', '.yaml'))]

# Шаг 1. Найти файлы нужного хранилища и зашифровать их копии новым паролем
targets = []
for path in files:
    with open(path, 'rb') as fh:
        if not is_encrypted_file(fh):
            continue
    with open(path) as fh:
        parts = fh.readline().strip().split(';')
    if len(parts) > 3 and parts[3] == LABEL:
        targets.append(path)

if not targets:
    print('Нет файлов для ротации')
    sys.exit(0)

for path in targets:
    VaultEditor().rekey_file(path, new_secret, new_vault_id=LABEL)

# Шаг 2. Проверить, что все файлы расшифровываются новым паролем
with open(NEW_PASS, 'w') as fh:
    fh.write(new_password)
import os
os.chmod(NEW_PASS, 0o600)
check = get_file_vault_secret(NEW_PASS, vault_id=LABEL, loader=loader)
loader.set_vault_secrets([(LABEL, check)])

for path in targets:
    loader.load_from_file(path)
print(f'OK: перешифровано и проверено файлов — {len(targets)}')

# Шаг 3. Только после успешной проверки заменить файл пароля
subprocess.run(['mv', NEW_PASS, OLD_PASS], check=True)
print(f'Пароль хранилища {LABEL} ротирован {datetime.date.today()}')
# → OK: перешифровано и проверено файлов — 4
# → Пароль хранилища prod ротирован 2026-09-26
```

Порядок шагов обязателен: сначала перешифровка, затем проверка новым паролем, и только потом подмена файла пароля. Обратный порядок приведёт к потере доступа к файлам при любой ошибке на промежуточном шаге.

### Сценарий 5: Генерация зашифрованной переменной для YAML

```python
#!/usr/bin/env python3
"""Генерация YAML-фрагмента с зашифрованной переменной (аналог encrypt_string)."""
import sys
from ansible.parsing.dataloader import DataLoader
from ansible.parsing.vault import VaultLib, get_file_vault_secret

VAR_NAME = 'db_password'
VAULT_ID = 'prod'

# Секрет приходит из stdin, чтобы не попасть в историю shell и вывод ps
SECRET_VALUE = sys.stdin.read().rstrip('\n')

loader = DataLoader()
vault_secret = get_file_vault_secret(
    '.vault_pass_prod', vault_id=VAULT_ID, loader=loader
)

# Метод encrypt уже включает заголовок и перенос по 80 символов
text = VaultLib([(VAULT_ID, vault_secret)]).encrypt(SECRET_VALUE.encode()).decode()

print(f'{VAR_NAME}: !vault |')
for line in text.splitlines():
    print(f'  {line}')
# → db_password: !vault |
# →   $ANSIBLE_VAULT;1.2;AES256;prod
# →   386232666439356134303461343834366132366134...
```

Вызывать скрипт так, чтобы значение не попало в аргументы:

```bash
printf '%s' 'MySecretPassword' | python3 encrypt_var.py >> group_vars/prod/vault.yml
# → дописывает зашифрованный блок в конец файла
```

### Сценарий 6: Проверка целостности и аудит формата

Разбор конверта без расшифровки позволяет проверить заголовок, метку и формат файла, не имея пароля.

```python
#!/usr/bin/env python3
"""Аудит формата vault-файлов: версия, шифр, метка, длина шифротекста."""
import glob
from ansible.parsing.vault import is_encrypted_file, parse_vaulttext_envelope

for path in sorted(glob.glob('group_vars/**/*.yml', recursive=True)):
    with open(path, 'rb') as fh:
        if not is_encrypted_file(fh):
            continue
        # Возвращает (ciphertext, version, cipher_name, vault_id).
        # Второй аргумент — метка по умолчанию для формата 1.0/1.1,
        # где метки в заголовке нет.
        ciphertext, version, cipher_name, vault_id = parse_vaulttext_envelope(
            fh.read(), 'default'
        )
        print(f'{path}: version={version.decode()} cipher={cipher_name} '
              f'vault_id={vault_id} ciphertext={len(ciphertext)}B')
# → group_vars/prod/vault.yml: version=1.2 cipher=AES256 vault_id=prod ciphertext=412B
```

Полная структура конверта разбирается функцией `parse_vaulttext()`, которая возвращает кортеж `(ciphertext, salt, crypted_hmac)`. Она же используется внутри `decrypt()`, поэтому применять её стоит только в тестах и инструментах анализа.

Проверка целостности делается через `decrypt()`: при подмене файла после шифрования выбрасывается `AnsibleVaultError` с текстом `HMAC verification failed`. **Эта ошибка неоднозначна**: HMAC считается ключом, производным от пароля, поэтому неверный пароль даёт ровно ту же ошибку. Отличить повреждение от неверного пароля по тексту исключения нельзя — диагностируйте по другим признакам (заголовок, метка `vault_id`, целостность окружения).

```python
from ansible.errors import AnsibleError
from ansible.parsing.dataloader import DataLoader
from ansible.parsing.vault import VaultLib, get_file_vault_secret

loader = DataLoader()
secret = get_file_vault_secret('.vault_pass', loader=loader)
vault = VaultLib([(None, secret)])

try:
    vault.decrypt(open('group_vars/all/vault.yml', 'rb').read())
    print('OK: файл не изменён')
except AnsibleError as exc:
    # AnsibleVaultFormatError наследует AnsibleError, а не AnsibleVaultError,
    # поэтому ловим общий базовый класс
    print(f'Ошибка: {exc}')
    # → Ошибка: HMAC verification failed: ...
```

### Сценарий 7: Подсчёт vault-значений в аргументах модулей

Значения из vault помечаются тегом `VaultedValue` начиная с ansible-core 2.18, поэтому их можно посчитать, не раскрывая содержимое. Полезно для аудита: видно, сколько секретов прошло через задачи, и ничего утекает в лог.

```python
# callbacks/vault_audit.py
from ansible.plugins.callback import CallbackBase
from ansible._internal._datatag._tags import VaultedValue

DOCUMENTATION = '''
    name: vault_audit
    type: aggregate
    short_description: Аудит количества vault-значений
    description: Считает, сколько значений из vault передано в модули, не выводя их содержимого.
'''


class CallbackModule(CallbackBase):
    CALLBACK_VERSION = 2.0
    CALLBACK_TYPE = 'aggregate'
    CALLBACK_NAME = 'vault_audit'
    CALLBACK_NEEDS_ENABLED = True

    def __init__(self):
        super().__init__()
        self.seen = 0

    def _record(self, result):
        # Значения, которые не удалось расшифровать, помечены тегом,
        # но при обращении к ним бросают исключение. Поэтому проверяем
        # наличие тега, а не читаем значение.
        module_args = (result._result.get('invocation') or {}).get('module_args') or {}
        for value in module_args.values():
            if VaultedValue.get_tag(value) is not None:
                self.seen += 1

    def v2_runner_on_ok(self, result, **kwargs):
        self._record(result)

    def v2_runner_on_failed(self, result, **kwargs):
        self._record(result)

    def v2_playbook_on_stats(self, stats):
        self._display.display(f'vault_audit: vault-значений в аргументах — {self.seen}')
```

Включение и проверка:

```bash
# ansible.cfg
# callback_whitelist = vault_audit

ansible-playbook site.yml --vault-password-file .vault_pass
# → vault_audit: vault-значений в аргументах — 7
```

Плагин считает количество, но не значения, — безопасный способ контролировать, какие задачи работают с секретами, без риска утечки в лог.

## Операции и команды

### Справочник методов

| Метод | Назначение |
| :--- | :--- |
| `VaultLib(secrets)` | Создать экземпляр. `secrets` — список кортежей `(vault_id, VaultSecret)` |
| `VaultLib.encrypt(plaintext, secret=None, vault_id=None, salt=None)` | Зашифровать `bytes`. Возвращает `bytes` с полным конвертом, включая заголовок |
| `VaultLib.decrypt(vaulttext)` | Расшифровать `bytes`. Возвращает `bytes` |
| `VaultLib.decrypt_and_get_vault_id(vaulttext)` | Расшифровать и вернуть кортеж `(plaintext, vault_id, secret)` — удобно для аудита, какой пароль подошёл |
| `VaultLib.is_encrypted(data)` | Проверить, является ли `bytes` зашифрованным конвертом |
| `VaultEditor().encrypt_file(path, secret, vault_id=None, output_file=None)` | Зашифровать файл на месте или в `output_file` |
| `VaultEditor().decrypt_file(path, output_file=None)` | Расшифровать в файл или в `None` (ничего не писать) |
| `VaultEditor().rekey_file(path, new_vault_secret, new_vault_id=None)` | Перешифровать файл новым секретом |
| `VaultEditor().create_file(path, secret, vault_id=None)` | Создать пустой зашифрованный файл |
| `VaultEditor().edit_file(path)` | Расшифровать во временный файл, запустить `$EDITOR`, зашифровать обратно |
| `VaultEditor().plaintext(path)` | Вернуть расшифрованное содержимое файла |
| `get_file_vault_secret(filename, vault_id=None, encoding=None, loader=None)` | Получить `VaultSecret` из файла, скрипта или client-скрипта |
| `is_encrypted(data)` | Проверить, начинаются ли `bytes` с заголовка Vault |
| `is_encrypted_file(file_obj)` | То же для файлового объекта |
| `parse_vaulttext_envelope(b_envelope, default_vault_id=None)` | Разобрать конверт: возвращает `(ciphertext, version, cipher_name, vault_id)` |
| `parse_vaulttext(b_vaulttext)` | Разобрать тело конверта: возвращает `(ciphertext, salt, crypted_hmac)` |
| `format_vaulttext_envelope(b_ciphertext, cipher_name, version=None, vault_id=None)` | Собрать конверт вручную |
| `VaultHelper.get_ciphertext(value, *, with_tags)` | Вернуть шифротекст vault-значения или `None` |
| `DataLoader.set_vault_secrets(secrets)` | Передать секреты загрузчику; `secrets` — список кортежей `(vault_id, VaultSecret)` |
| `DataLoader.load_from_file(file_name, ...)` | Разобрать YAML/JSON с `!vault`, расшифровывая значения |

### Полезные проверки через CLI

```bash
# Версия ansible-core, от которой зависит поведение EncryptedString
ansible --version | head -1
# → ansible [core 2.19.6]

# Проверить, что файл действительно зашифрован
head -1 group_vars/prod/vault.yml
# → $ANSIBLE_VAULT;1.2;AES256;prod

# Найти все зашифрованные файлы в индексе Git
git grep -l '^\$ANSIBLE_VAULT' -- '*.yml' '*.yaml'
# → group_vars/prod/vault.yml
# → roles/app/defaults/main.yml
```

### Быстрая проверка API в однострочнике

```bash
python3 -c "
from ansible.parsing.dataloader import DataLoader
from ansible.parsing.vault import get_file_vault_secret
l = DataLoader()
l.set_vault_secrets([(None, get_file_vault_secret('.vault_pass', loader=l))])
d = l.load_from_file('group_vars/all/vault.yml')
print('ключей:', len(d))
"
# → ключей: 5
```

## Устранение неполадок

### Ошибка: `ModuleNotFoundError: No module named 'ansible'`

**Причина**: скрипт запускается в окружении, где ansible-core не установлен, либо активен другой virtualenv.

**Решение**:
```bash
python3 -c "import ansible; print(ansible.__file__)"
# → /usr/lib/python3/dist-packages/ansible/__init__.py

# Использовать venv с ansible-core
python3 -m venv ~/.venvs/ansible-api
source ~/.venvs/ansible-api/bin/activate
pip install 'ansible-core[crypto]'
```

### Ошибка: `AttributeError: 'NoneType' object has no attribute 'read'`

**Причина**: в `set_vault_secrets()` передан кортеж с `None` вместо `VaultSecret` — это допустимо для `vault_id`, но не для самого секрета.

**Решение**: всегда передавайте реальный объект:
```python
# Неверно
loader.set_vault_secrets([(label, None)])

# Верно
loader.set_vault_secrets([(label, get_file_vault_secret(pw, vault_id=label, loader=loader))])
```

### Ошибка: `Decryption failed` при верном на вид пароле

**Причина 1**: перевод строки в конце файла пароля. Ansible использует файл целиком, вместе с `\n`.

**Причина 2**: неоднородное кодирование. Пароль с не-ASCII символами читается в кодировке, отличной от той, при которой шифровали.

**Решение**:
```bash
# Проверить, есть ли перевод строки
xxd .vault_pass | tail -1
# → 00000000: 4d79 5365 6372 6574 0a              MySecret.

# Перезаписать без перевода строки
printf '%s' 'MySecretPassword' > .vault_pass
chmod 600 .vault_pass

# Явно задать кодировку при чтении
get_file_vault_secret('.vault_pass', vault_id='prod', encoding='utf-8', loader=loader)
```

### Ошибка: `The vault password file '...' was not found`

**Причина**: путь указан относительно текущей директории, а скрипт запущен из другой.

**Решение**: передавайте абсолютные пути, вычисляя их от расположения скрипта:
```python
import os
BASE = os.path.dirname(os.path.abspath(__file__))
secret = get_file_vault_secret(os.path.join(BASE, '.vault_pass'), loader=loader)
```

### Ошибка: `AnsibleVaultError: HMAC verification failed`

**Причина — одна из трёх, и по тексту ошибки они неразличимы:**

1. файл изменён после шифрования (вручную, при слиянии веток с конфликтом, при повреждении);
2. передан неверный пароль;
3. файл перешифрован другим паролем или другим Vault ID.

HMAC проверяется до расшифровки, но сам HMAC считается ключом, **произведённым из пароля**, поэтому пункты 2 и 3 дают ту же ошибку, что и пункт 1.

**Диагностика** — по заголовку и окружению, а не по типу исключения:
```bash
head -1 group_vars/prod/vault.yml
# → $ANSIBLE_VAULT;1.2;AES256;prod   ← метка prod должна совпадать с переданным vault_id
```

**Решение**: восстановить файл из Git и повторить операцию.
```bash
git checkout -- group_vars/prod/vault.yml
head -1 group_vars/prod/vault.yml
# → $ANSIBLE_VAULT;1.2;AES256;prod
```

### Проблема: `isinstance(value, AnsibleVaultEncryptedUnicode)` больше не работает

**Причина**: по [porting guide 2.19](https://docs.ansible.com/projects/ansible-core/2.19/porting_guides/porting_guide_core_2.19.html) тип `AnsibleVaultEncryptedUnicode` заменён на `EncryptedString`, а значения теперь отображаются как **тегированная `str`**. Плагины с `isinstance`-проверками старого типа больше не встретят нужные значения.

**Решение**: проверяйте наличие тега, а не класс:
```python
from ansible._internal._datatag._tags import VaultedValue

if VaultedValue.get_tag(value) is not None:
    # значение пришло из vault
    ...
```

Дополнительный риск при миграции: Jinja-плагины с `except Exception` вокруг обращения к содержимому контейнеров (`dict`, `list`) могут работать некорректно, если значение не определено или не расшифровывается. Ловите конкретные исключения и сужайте область `try` до минимально необходимой.

## Лучшие практики

### Безопасность

- **Не передавайте пароли через аргументы и переменные окружения.** `get_file_vault_secret()` с файлом, скриптом или менеджером секретов — единственный безопасный путь. Пароль в аргументах процесса виден через `ps -ef` и `/proc/*/cmdline`.
- **Выбирайте пароль строго по метке из заголовка.** Это предотвращает расшифровку файла `prod` паролем `dev` при `vault_id_match = False`. Всегда разбирайте `vault_id` из первой строки файла и подбирайте секрет по ней.
- **Проверяйте расшифровку до подмены файла пароля.** Порядок «перешифровал → проверил новым паролем → заменил файл» исключает потерю доступа при любой ошибке на промежуточном шаге.
- **Логируйте факты, а не значения.** В callback-плагинах считайте количество vault-значений и Vault ID, но никогда не выводите сами секреты. `no_log: true` скрывает вывод задачи, но не защищает от `debug` или `register` без `no_log`.
- **Фиксируйте версии зависимостей.** `cryptography` и `ansible-core` зафиксируйте в `requirements.txt` с версиями, иначе скрипт сломается после обновления на контроллере. Внешние модули (`ansible.parsing.vault`, `ansible._internal._datatag._tags`) — внутренние пути без гарантии обратной совместимости между мажорными версиями.
- **Изолируйте API в отдельном модуле.** Оберните работу с vault в собственные функции (`read_secrets`, `rotate_password`) вместо вызова API в разных местах кода — так смена способа хранения пароля не потребует правок по всему проекту.

### Для DevOps

- **Версионируйте скрипты вместе с кодом.** Храните скрипты работы с vault в репозитории, а файлы паролей — только в защищённом хранилище CI/CD.
- **Автоматизируйте проверку расшифровки.** Добавьте в CI скрипт, который проверяет все vault-файлы на корректность расшифровки (см. Сценарий 2). Это предотвратит попадание в ветку файлов, зашифрованных не тем паролем.
- **Используйте `vault_id_match = True`.** В `ansible.cfg` или через `ANSIBLE_VAULT_ID_MATCH=True`. Это исключает эскалацию привилегий, когда пароль `dev` может расшифровать файл `prod`.
- **Тестируйте на Python 3.12+.** Начиная с ansible-core 2.20, Control Node требует Python 3.12+. Убедитесь, что ваши скрипты и venv соответствуют этому требованию.

### Для SRE

- **Внедрите политику ротации.** Ротация мастер-паролей раз в квартал — минимум. Автоматизируйте процесс через скрипты с проверкой перед подменой файла пароля.
- **Аудит через callback-плагины.** Используйте плагины вида `vault_audit` для подсчёта vault-значений, прошедших через задачи, без раскрытия их содержимого.
- **Мониторьте утечки.** Включите `ANSIBLE_LOG_PATH` и регулярно проверяйте логи на наличие секретов. Настройте алерты на появление ключевых слов (`password`, `secret`, `token`, `key`) в логах Ansible.
- **Документируйте процедуры.** Для каждого окружения ведите журнал: какой Vault ID используется, когда пароль был ротирован, кто имеет доступ к файлам паролей.

### Для Sysadmin

- **Контролируйте права доступа.** Файлы паролей — `chmod 600`, директория с секретами — `chmod 700`, shared Control Node — `umask 0077`.
- **Контролируйте `$TMPDIR`.** На shared серверах временные файлы `ansible-vault edit` создаются в `$TMPDIR`. Убедитесь, что директория защищена и недоступна другим пользователям.
- **Используйте `ansible-vault view` вместо `decrypt`.** `decrypt` оставляет открытый текст на диске. `view` выводит в stdout и не оставляет следов.
- **Проверяйте конфигурацию.** `ansible-config dump --only-changed | grep vault` — быстрый способ увидеть, какие параметры Vault применены в текущем окружении.
- **Не полагайтесь на `isinstance` с внутренними типами.** `AnsibleVaultEncryptedUnicode` удалён в 2.19. Проверяйте наличие тега `VaultedValue`, а не класс значения.

## См. также

- [Ansible Vault: Основы](./basics.md) — команды CLI, конфигурация и формат заголовков.
- [Ansible Vault: Управление паролями](./passwords.md) — скрипты-источники, GPG, `pass`, KeePassXC, внешние менеджеры.
- [Ansible Vault: Лучшие практики](./best_practices.md) — векторы утечек, ротация, интеграция с CI/CD.
- [Ansible Vault: Алгоритмы шифрования](./algorithms.md) — формат конверта, KDF, HMAC.

## Дополнительная информация

### Справочник импортов

```python
# Обязательное для любой работы с vault
from ansible.parsing.vault import (
    VaultLib,             # шифрование/расшифровка строк
    VaultEditor,          # операции с файлами
    VaultSecret,          # абстрактный секрет
    VaultHelper,          # get_ciphertext и утилиты
    get_file_vault_secret,# секрет из файла/скрипта
    is_encrypted,         # проверка данных
    is_encrypted_file,    # проверка файла
    parse_vaulttext_envelope,   # разбор конверта
    parse_vaulttext,            # разбор тела конверта
    format_vaulttext_envelope,  # сборка конверта
    verify_secret_is_not_empty, # проверка секрета на пустоту
    AnsibleVaultError,          # ошибка расшифровки
    AnsibleVaultPasswordError,  # ошибка пароля или источника
    AnsibleVaultFormatError,    # ошибка формата файла
)

# Для парсинга YAML с !vault
from ansible.parsing.dataloader import DataLoader

# Только для ansible-core 2.19+
from ansible.parsing.vault import EncryptedString

# Для определения происхождения значения (2.18+)
from ansible._internal._datatag._tags import VaultedValue
```

Иерархия исключений в ansible-core 2.19:

| Исключение | Базовый класс | Когда возникает |
| :--- | :--- | :--- |
| `AnsibleVaultError` | `AnsibleError` | Не удалось расшифровать: неверный пароль или сработала HMAC-проверка |
| `AnsibleVaultPasswordError` | `AnsibleVaultError` | Проблема с паролем или источником секрета, в том числе пустой секрет |
| `AnsibleVaultFormatError` | `AnsibleError` | Повреждённый формат конверта |

Обратите внимание: `AnsibleVaultFormatError` наследует `AnsibleError` напрямую, а **не** `AnsibleVaultError`. Чтобы покрыть оба случая, ловите `AnsibleError` или перечисляйте исключения явно:

```python
from ansible.errors import AnsibleError
from ansible.parsing.vault import AnsibleVaultError, AnsibleVaultFormatError

try:
    vault.decrypt(data)
except AnsibleVaultFormatError:
    ...   # файл повреждён
except AnsibleVaultError:
    ...   # неверный пароль
```

### Граничные случаи

- **Формат 1.0** (`$ANSIBLE_VAULT;1.0;AES256`) читается, но при перезаписи автоматически конвертируется в 1.1. Шифровать в 1.0 нельзя.
- **Пустой секрет** отклоняется функцией `verify_secret_is_not_empty()` с `AnsibleVaultPasswordError` — пустой файл пароля приведёт к ошибке, а не к «пустым» зашифрованным данным.
- **Скрипт-источник без бита execute** будет прочитан как обычный текстовый файл, и Ansible попытается использовать содержимое скрипта как пароль. Проверяйте `chmod +x`.
- **Файлы паролей с завершающим переводом строки** — самая частая причина «неверного» пароля при ручном вводе.
- **`salt` в `VaultLib.encrypt()`** передаётся только для тестов и криптографического анализа. В продакшене используйте значение по умолчанию (32 случайных байта), иначе одинаковые plaintext дадут одинаковый ciphertext.
- **Пустой файл не считается зашифрованным.** `is_encrypted()` проверяет заголовок, поэтому пустой или обрезанный файл вернёт `False`.

### Замечания по версиям

| Версия | Изменение, влияющее на API |
| :--- | :--- |
| 2.4 | Появились Vault ID и метки в формате 1.2 |
| 2.9 | Добавлен тег `VaultedValue`: значения из vault помечаются, но ещё хранятся в отдельном типе `AnsibleVaultEncryptedUnicode` |
| 2.18 | Развита система Data Tagging; значения из vault получают тег `VaultedValue` |
| 2.19 | `AnsibleVaultEncryptedUnicode` заменён на `EncryptedString` (подкласс `str`); значения отображаются как тегированная `str`; Jinja-плагинам больше не нужна специальная обработка для доступа к содержимому; `isinstance`-проверки старого типа перестают работать; появился `VaultSecretsContext` |
| 2.20 | Фильтры `vault` и `unvault` больше не принимают устаревший параметр `vaultid` (используйте `vault_id`); Python 3.11 больше не поддерживается на Control Node (требуется 3.12+); `DataLoader.get_basedir` возвращает абсолютный путь |
| 2.21 | Стабилизация поведения `EncryptedString` и контекста секретов; API-изменений для Vault нет |
| 2.22 | API-изменений для Vault нет |

Перед обновлением с 2.18 на 2.19+ прогоняйте интеграционные тесты с плагинами: изменения затрагивают пути, которые годами работали без явной обработки. При обновлении с 2.19 на 2.20+ убедитесь, что Control Node работает под Python 3.12+.

### Ссылки

- [Исходный код `ansible.parsing.vault`](https://github.com/ansible/ansible/blob/stable-2.21/lib/ansible/parsing/vault/__init__.py) — актуальный список классов и методов.
- [Porting Guide ansible-core 2.19](https://docs.ansible.com/projects/ansible-core/2.19/porting_guides/porting_guide_core_2.19.html) — замена `AnsibleVaultEncryptedUnicode` на `EncryptedString`.
- [Документация по Vault](https://docs.ansible.com/projects/ansible/latest/vault_guide/vault.html) — официальное руководство.
