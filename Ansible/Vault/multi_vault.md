# Ansible Vault: Использование нескольких хранилищ (Multi-Vault)

## Определения

- **Vault ID (Идентификатор хранилища)**: Текстовая метка (например, `dev`, `prod`, `common`), которая связывает зашифрованные данные с конкретным источником пароля. Это позволяет Ansible однозначно определить, какой ключ использовать для расшифровки, без перебора всех доступных паролей.
- **Метка (Label)**: Имя Vault ID, указываемое перед символом `@` в аргументах командной строки (CLI — Command Line Interface) или в конфигурационных файлах.
- **Identity List (Список идентификаторов)**: Перечень пар `метка@источник`, определяющий все доступные ключи и их происхождение для текущего сеанса автоматизации.
- **Строгое соответствие (Strict Matching)**: Режим работы, при котором Ansible пытается расшифровать файл *только* тем ключом, метка которого совпадает с указанной в заголовке файла.
- **Нечеткое соответствие (Fuzzy/Legacy Matching)**: Режим (по умолчанию), при котором для файлов без меток (версия 1.1) или при отсутствии совпадения меток (если `vault_id_match=False`) Ansible поочередно пробует все предоставленные ключи.
- **Мультиокруженность (Multi-Environment)**: Стратегия управления секретами, при которой для каждого окружения (dev, staging, prod) используется отдельный Vault ID с уникальным паролем.

## Основные концепции

### Предварительные требования

Для использования нескольких хранилищ (Multi-Vault) необходимо:

- **Ansible (ansible-core)**: версия 2.4 или выше (для поддержки Vault ID); рекомендуется ansible-core 2.20+.
- **Python**: 3.8+ (совместимость с ansible-core 2.20+).
- **Хранилища паролей**: минимум два различных пароля для разных окружений (например, `.vault_pass_dev` и `.vault_pass_prod`).
- **Права доступа**: файлы паролей должны иметь права `chmod 600` (только владелец).
- **Структура каталогов**: рекомендуется разделение `group_vars/dev/`, `group_vars/prod/` с отдельными `vault.yml` файлами.

Проверка версии Ansible:
```bash
ansible --version | head -1
# → ansible [core 2.20.0] или выше
```

Проверка прав доступа к файлам паролей:
```bash
ls -la .vault_pass_*
# → -rw------- 1 user group 16 Aug 26 10:00 .vault_pass_dev
# → -rw------- 1 user group 16 Aug 26 10:00 .vault_pass_prod
```

**Для Sysadmin:** На shared Control Node используйте `umask 0077` для автоматического ограничения прав на создаваемые файлы паролей. Контролируйте `$TMPDIR` — временные файлы при работе с Vault создаются именно там.

### Зачем нужно несколько хранилищ

В крупных проектах секреты разделены по уровням доступа или окружениям. Использование разных паролей для разработки (`dev`) и эксплуатации (`prod`) — критический стандарт безопасности.

1. **Безопасность**: Команда разработки может иметь доступ только к `dev`-секретам, не имея технической возможности расшифровать `prod`-данные. Это реализует принцип наименьших привилегий.
2. **Производительность**: При использовании Vault ID Ansible мгновенно выбирает нужный ключ, не тратя время на дорогостоящие операции хеширования (PBKDF2) для перебора всех известных паролей для каждого зашифрованного объекта.
3. **Аудит и отладка**: В логах и заголовках файлов четко видно, какой уровень доступа требуется для выполнения конкретной задачи.

**Для DevOps:** При масштабировании CI/CD (больше 50 Vault-файлов в одном пайплайне) учитывайте кумулятивную задержку KDF. Каждый файл добавляет ~50-100 мс. Используйте `vault_id_match = True` и формат 1.2 для минимизации перебора.

**Для SRE:** Внедрите политику именования Vault ID, исключающую чувствительные данные в метках. Ведите инвентаризацию всех Vault ID и регулярно аудите их использование.

### Логика выбора ключа

Ansible поддерживает два формата заголовков:
- **Версия 1.1 (`$ANSIBLE_VAULT;1.1;AES256`)**: Не содержит метки. Ansible будет пробовать все ключи из `vault_identity_list` по порядку, пока один из них не подойдет. Детали см. в [Ansible Vault: Основы](./basics.md#основные-концепции).
- **Версия 1.2 (`$ANSIBLE_VAULT;1.2;AES256;label`)**: Содержит метку. Логика зависит от настройки `vault_id_match`.

#### Режим `vault_id_match = True` (Рекомендуется)

Система ищет в `vault_identity_list` источник, соответствующий метке `label`.
- Если совпадение найдено — используется этот ключ.
- Если совпадение НЕ найдено — расшифровка завершается ошибкой, даже если другой пароль из списка технически мог бы расшифровать данные. Это предотвращает случайное использование ключей не по назначению.

**Для SRE:** Строгий режим (`vault_id_match = True`) — обязательный минимум для production. Он исключает эскалацию привилегий через доступ к dev-паролю в prod-окружении.

#### Режим `vault_id_match = False` (По умолчанию, Legacy)

При отсутствии совпадения меток Ansible перебирает все ключи из списка. Этот режим сохраняется для обратной совместимости с проектами, использующими формат 1.1.

> **Важно:** Для новых проектов используйте формат 1.2 с метками и `vault_id_match = True`. Детали о структуре заголовков и криптографии см. в [Алгоритмы и криптография](./algorithms.md#формат-заголовков).

### Утечка метаданных (Security Warning)

**Важно:** Метка Vault ID в заголовке файла (формат 1.2) хранится в **открытом виде**. Это означает, что любой, кто имеет доступ к репозиторию, может узнать названия ваших окружений или команд (например, `prod-db-root`). Избегайте использования чувствительной информации в названиях меток.

**Для Sysadmin:** Используйте нейтральные имена (`prod`, `db`, `app`) вместо композитных (`prod-db-root-admin`). Заголовок хранится в открытом виде; его видно через `head -1 secrets.yml`.

## Практические сценарии

### Сценарий 1: Создание секретов с привязкой к окружению

При создании секрета через CLI необходимо указывать идентификатор, чтобы Ansible прописал правильную метку версии 1.2 в заголовок.

```bash
# Создание файла для эксплуатации (пароль будет запрошен интерактивно)
ansible-vault create --vault-id prod@prompt group_vars/prod/vault.yml

# Инлайновое шифрование строки для разработки
ansible-vault encrypt_string --vault-id dev@.vault_pass_dev 'secret_val' --name 'vault_db_pass'
```

**Для DevOps:** При создании новых Vault-файлов всегда используйте `--vault-id` с явным указанием метки. Это исключает потерю данных при последующей миграции на строгий режим.

### Сценарий 2: Глобальная настройка в ansible.cfg

Рекомендуемый способ для командной разработки, позволяющий избежать ручной передачи аргументов при каждом запуске плейбука.

```ini
# ansible.cfg
[defaults]
# Список идентификаторов и источников
vault_identity_list = dev@.vault_pass_dev, prod@.vault_pass_prod, common@.vault_pass_common

# Включение строгого соответствия меток
vault_id_match = True
```

**Для Sysadmin:** После изменения `ansible.cfg` проверьте конфигурацию командой `ansible-config dump | grep vault`. Убедитесь, что параметры применены корректно.

### Сценарий 3: Запуск плейбука с переопределением через ENV

В пайплайнах (CI/CD) список идентификаторов можно передать через переменную окружения, что имеет приоритет над `ansible.cfg`.

```bash
# Передача списка источников через системную переменную окружения
export ANSIBLE_VAULT_IDENTITY_LIST="prod@/tmp/prod.pass, ops@/tmp/ops.pass"
ansible-playbook site.yml
```

**Приоритет аргументов командной строки**: `--vault-id` > `ANSIBLE_VAULT_IDENTITY_LIST` > `vault_identity_list` в `ansible.cfg`.

**Для DevOps:** В CI/CD используйте переменную окружения `ANSIBLE_VAULT_IDENTITY_LIST` для передачи зашифрованных паролей. Никогда не передавайте пароли через `ANSIBLE_VAULT_PASSWORD` — Ansible не поддерживает это из соображений безопасности.

### Сценарий 4: Массовая ротация и смена меток

Команда `rekey` позволяет перевести старые секреты (версия 1.1) на новый формат с метками или изменить существующие метки.

```bash
# Перевод всех файлов из 1.1 в 1.2 с меткой 'prod'
ansible-vault rekey --vault-id old_password_file --new-vault-id prod@new_password_file group_vars/all/*.yml
```

**Для SRE:** При компрометации пароля выполните массовую ротацию: `find group_vars -name "*.yml" | xargs ansible-vault rekey --vault-id old@source --new-vault-id new@source`. Удаляйте старые файлы паролей только после проверки расшифровки.

### Сценарий 5: CI/CD пайплайн с несколькими хранилищами

Передача Vault ID в CI/CD через зашифрованные переменные:

```yaml
# .github/workflows/deploy.yml
name: Deploy with Multi-Vault
on:
  push:
    branches: [main, develop]

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Decrypt vault passwords
        env:
          VAULT_PASS_DEV: ${{ secrets.VAULT_PASS_DEV }}
          VAULT_PASS_PROD: ${{ secrets.VAULT_PASS_PROD }}
        run: |
          echo "$VAULT_PASS_DEV" > .vault_pass_dev
          echo "$VAULT_PASS_PROD" > .vault_pass_prod
          chmod 600 .vault_pass_*

      - name: Run playbook
        env:
          ANSIBLE_VAULT_IDENTITY_LIST: "dev@.vault_pass_dev, prod@.vault_pass_prod"
        run: |
          ansible-playbook --vault-id dev@.vault_pass_dev \
                           --vault-id prod@.vault_pass_prod \
                           site.yml
```

**Для DevOps:** На self-hosted раннере контролируйте права доступа к директории с секретами. Удаляйте временные файлы в `post` шагах. Никогда не передавайте пароль через `echo` в логи.

### Сценарий 6: Docker-контейнер с несколькими хранилищами

Передача Vault ID в Docker-контейнер через переменные окружения:

```dockerfile
# Dockerfile
FROM ubuntu:22.04

RUN apt-get update && apt-get install -y ansible python3-pip

COPY requirements.txt /tmp/requirements.txt
RUN pip3 install -r /tmp/requirements.txt

COPY .vault_pass_* /vault_pass/
RUN chmod 600 /vault_pass/*

ENV ANSIBLE_VAULT_IDENTITY_LIST="dev@/vault_pass/.vault_pass_dev,prod@/vault_pass/.vault_pass_prod"

WORKDIR /ansible
COPY . .
```

```yaml
# docker-compose.yml
version: '3.8'
services:
  ansible:
    build: .
    environment:
      - ANSIBLE_VAULT_IDENTITY_LIST=dev@/vault_pass/.vault_pass_dev,prod@/vault_pass/.vault_pass_prod
    volumes:
      - ./inventory:/ansible/inventory
      - ./playbooks:/ansible/playbooks
      - ./.vault_pass_dev:/vault_pass/.vault_pass_dev:ro
      - ./.vault_pass_prod:/vault_pass/.vault_pass_prod:ro
    command: ansible-playbook -i inventory/hosts playbooks/site.yml --vault-id dev@/vault_pass/.vault_pass_dev --vault-id prod@/vault_pass/.vault_pass_prod
```

**Для Sysadmin:** Используйте `:ro` (read-only) для томов с файлами паролей. Никогда не монтируйте файлы паролей в контейнер с возможностью записи.

### Сценарий 7: Иерархия Vault ID с общими секретами

Создание иерархии, где общий секрет (`common`) доступен всем окружениям, а специфические — только своим:

```
group_vars/
├── all/
│   └── vault.yml          # зашифрован с common@prompt
├── dev/
│   ├── vars.yml           # зашифрован с dev@prompt
│   └── vault.yml          # зашифрован с dev@prompt
└── prod/
    ├── vars.yml           # зашифрован с prod@prompt
    └── vault.yml          # зашифрован с prod@prompt
```

```ini
# ansible.cfg
[defaults]
vault_identity_list = dev@.vault_pass_dev, prod@.vault_pass_prod, common@.vault_pass_common

# Строгий режим: каждый файл расшифровывается только своим ключом
vault_id_match = True
```

```bash
# Шифрование общего секрета (доступен всем)
ansible-vault encrypt_string --vault-id common@.vault_pass_common \
  'shared_db_password' --name 'db_password'

# Шифрование dev-специфичного секрета
ansible-vault encrypt_string --vault-id dev@.vault_pass_dev \
  'dev_only_token' --name 'debug_token'
```

**Для SRE:** Используйте отдельный Vault ID `common` только для действительно общих секретов. Не храните в `common` секреты, которые должны быть доступны только определенным командам или окружениям.

### Сценарий 8: Ротация пароля для конкретного Vault ID без перешифровки всех файлов

Пошаговая ротация пароля для одного окружения:

```bash
# 1. Создание нового файла пароля
echo "new_prod_password" > .vault_pass_prod_new
chmod 600 .vault_pass_prod_new

# 2. Перешифровка prod-файлов с новым паролем
ansible-vault rekey --vault-id prod@.vault_pass_prod \
                    --new-vault-id prod@.vault_pass_prod_new \
                    group_vars/prod/vault.yml

# 3. Замена старого файла пароля
mv .vault_pass_prod .vault_pass_prod_old
mv .vault_pass_prod_new .vault_pass_prod

# 4. Проверка расшифровки
ansible-vault view --vault-id prod@.vault_pass_prod group_vars/prod/vault.yml

# 5. Удаление старого пароля (после проверки)
rm .vault_pass_prod_old
```

**Для Sysadmin:** Никогда не удаляйте старый файл пароля до успешной проверки расшифровки всех файлов. Храните резервную копию старого пароля в защищенном хранилище в течение 7 дней после ротации.

### Сценарий 9: Автоматическое определение Vault ID по окружению

Скрипт для автоматического выбора Vault ID на основе имени ветки или хоста:

```bash
#!/bin/bash
# auto_vault_id.sh

ENVIRONMENT="${1:-$(hostname -s)}"
VAULT_PASS_DIR=".vault_pass"

case "$ENVIRONMENT" in
  dev|development|localhost)
    VAULT_ID="dev"
    VAULT_PASS="${VAULT_PASS_DIR}/.vault_pass_dev"
    ;;
  staging|stage)
    VAULT_ID="staging"
    VAULT_PASS="${VAULT_PASS_DIR}/.vault_pass_staging"
    ;;
  prod|production)
    VAULT_ID="prod"
    VAULT_PASS="${VAULT_PASS_DIR}/.vault_pass_prod"
    ;;
  *)
    echo "Неизвестное окружение: $ENVIRONMENT"
    echo "Доступные: dev, staging, prod"
    exit 1
    ;;
esac

echo "Окружение: $ENVIRONMENT"
echo "Vault ID: $VAULT_ID"
echo "Файл пароля: $VAULT_PASS"

# Запуск плейбука
ansible-playbook --vault-id "${VAULT_ID}@${VAULT_PASS}" site.yml
```

Использование:
```bash
chmod +x auto_vault_id.sh
./auto_vault_id.sh prod
```

**Для SRE:** Добавьте этот скрипт в `pre-commit` hook или Makefile для автоматического выбора правильного Vault ID. Документируйте supported значения окружений.

### Сценарий 10: Тестирование всех Vault ID в проекте

Скрипт для проверки корректности всех хранилищ паролей:

```bash
#!/bin/bash
# test_all_vaults.sh

VAULT_PASS_DIR=".vault_pass"
GROUP_VARS_DIR="group_vars"

echo "=== Проверка всех Vault ID ==="

for vault_pass in "${VAULT_PASS_DIR}"/.vault_pass_*; do
  VAULT_ID=$(basename "$vault_pass" | sed 's/\.vault_pass_//')
  echo ""
  echo "Проверка Vault ID: $VAULT_ID"

  # Поиск файлов с этим Vault ID
  FILES_FOUND=0
  for vault_file in $(find "${GROUP_VARS_DIR}" -name "*.yml" -type f); do
    HEADER=$(head -1 "$vault_file" 2>/dev/null)
    FILE_VAULT_ID=$(echo "$HEADER" | cut -d';' -f4)

    if [ "$FILE_VAULT_ID" = "$VAULT_ID" ]; then
      FILES_FOUND=$((FILES_FOUND + 1))
      echo -n "  Расшифровка: $vault_file ... "
      if ansible-vault view --vault-id "${VAULT_ID}@${vault_pass}" "$vault_file" > /dev/null 2>&1; then
        echo "OK"
      else
        echo "ОШИБКА"
      fi
    fi
  done

  if [ "$FILES_FOUND" -eq 0 ]; then
    echo "  Файлы не найдены (пропуск)"
  fi
done

echo ""
echo "=== Проверка завершена ==="
```

**Для SRE:** Добавьте этот скрипт в CI/CD пайплайн для автоматической проверки всех Vault ID после каждого деплоя. Настройте алерт при обнаружении ошибок расшифровки.

### Сценарий 11: Миграция с одного Vault ID на несколько

Пошаговая миграция проекта с единого хранилища на разделенные:

```bash
#!/bin/bash
# migrate_to_multi_vault.sh

SINGLE_VAULT_PASS="${1:?Укажите текущий пароль}"
DEV_PASS="${2:?Укажите пароль для dev}"
PROD_PASS="${3:?Укажите пароль для prod}"

echo "Миграция на несколько хранилищ..."

# 1. Перешифровка dev-файлов
echo "Этап 1: Перешифровка dev-файлов..."
ansible-vault rekey --vault-id default@"${SINGLE_VAULT_PASS}" \
                    --new-vault-id dev@"${DEV_PASS}" \
                    group_vars/dev/*.yml

# 2. Перешифровка prod-файлов
echo "Этап 2: Перешифровка prod-файлов..."
ansible-vault rekey --vault-id default@"${SINGLE_VAULT_PASS}" \
                    --new-vault-id prod@"${PROD_PASS}" \
                    group_vars/prod/*.yml

# 3. Перешифровка общих файлов (если есть)
if [ -d "group_vars/all" ]; then
  echo "Этап 3: Перешифровка общих файлов..."
  ansible-vault rekey --vault-id default@"${SINGLE_VAULT_PASS}" \
                      --new-vault-id common@"${DEV_PASS}" \
                      group_vars/all/*.yml
fi

# 4. Обновление ansible.cfg
echo "Этап 4: Обновление ansible.cfg..."
cat > ansible.cfg.new << EOF
[defaults]
vault_identity_list = dev@.vault_pass_dev, prod@.vault_pass_prod, common@.vault_pass_common
vault_id_match = True
EOF

echo ""
echo "Миграция завершена. Обновите ansible.cfg вручную или:"
mv ansible.cfg.new ansible.cfg

# 5. Проверка
echo ""
echo "Этап 5: Проверка..."
ansible-playbook --syntax-check site.yml --vault-id dev@"${DEV_PASS}" --vault-id prod@"${PROD_PASS}"
```

**Для Sysadmin:** Выполняйте миграцию на тестовом стенде перед применением к production. Сохраните резервную копию исходных Vault-файлов и паролей до начала миграции.

## Операции и команды

### Команды с несколькими Vault ID

| Команда | Описание |
|---------|----------|
| `ansible-vault create --vault-id <label>@<source> <file>` | Создание нового зашифрованного файла с указанным Vault ID |
| `ansible-vault encrypt --vault-id <label>@<source> <file>` | Шифрование существующего файла с меткой версии 1.2 |
| `ansible-vault rekey --vault-id <old_label>@<old_source> --new-vault-id <new_label>@<new_source> <file>` | Смена пароля или метки Vault ID |
| `ansible-vault encrypt_string --vault-id <label>@<source> --name <var_name> '<value>'` | Шифрование отдельной строки с указанием Vault ID |

> **Примечание:** Общий справочник команд (`create`, `edit`, `view`, `decrypt`) и переменных окружения см. в [Ansible Vault: Основы — Операции и команды](./basics.md#операции-и-команды).

### Приоритет источников

При использовании нескольких Vault ID Ansible применяет следующую логику:
1. Аргументы командной строки (`--vault-id`)
2. Переменная окружения (`ANSIBLE_VAULT_IDENTITY_LIST`)
3. Конфигурационный файл (`vault_identity_list` в `ansible.cfg`)

Для файлов версии 1.2 с `vault_id_match = True` производительность не зависит от количества ключей в списке — Ansible мгновенно находит нужный по метке.

## Устранение неполадок

### Ошибка: `Vault password not found for identity`

**Причина**: Vault ID не найден в `vault_identity_list` или файл пароля не существует.

```bash
# Проверка vault_identity_list в ansible.cfg
grep vault_identity_list ansible.cfg

# Проверка существования файлов паролей
ls -la .vault_pass_*

# Проверка переданных Vault ID
ansible-playbook site.yml --vault-id dev@.vault_pass_dev --list-vault-ids
```

### Ошибка: `Decryption failed` для конкретного Vault ID

**Причина**: неверный пароль или файл зашифрован другим Vault ID.

```bash
# Проверка Vault ID в заголовке файла
head -1 group_vars/prod/vault.yml
# → $ANSIBLE_VAULT;1.2;AES256;prod

# Попытка расшифровки с указанием правильного Vault ID
ansible-vault view --vault-id prod@.vault_pass_prod group_vars/prod/vault.yml

# Если Vault ID не совпадает — перешифровка с правильной меткой
ansible-vault rekey --vault-id old@.vault_pass_old --new-vault-id prod@.vault_pass_prod group_vars/prod/vault.yml
```

### Ошибка: `Too many vault secrets` при большом количестве Vault ID

**Причина**: количество Vault ID превышает рекомендуемый лимит (>10) при использовании формата 1.1.

```bash
# Проверка количества Vault ID
grep -o '@' <<< "$(grep vault_identity_list ansible.cfg)" | wc -l

# Оптимизация: группировка похожих окружений
# Вместо dev, dev-test, dev-staging, dev-local → dev (для всех dev-окружений)
```

**Для SRE:** Для формата 1.2 с `vault_id_match=True` количество Vault ID не влияет на производительность. Если у вас >10 окружений, проверьте, можно ли объединить похожие окружения под общий Vault ID.

### Ошибка: `ANSIBLE_VAULT_IDENTITY_LIST ignored` в CI/CD

**Причина**: приоритет аргументов командной строки над переменными окружения.

```bash
# Неправильно: ENV перезаписывается CLI
export ANSIBLE_VAULT_IDENTITY_LIST="dev@.vault_pass_dev"
ansible-playbook site.yml --vault-id prod@.vault_pass_prod  # ENV игнорируется

# Правильно: используйте либо ENV, либо CLI
ansible-playbook site.yml  # Использует ANSIBLE_VAULT_IDENTITY_LIST
# ИЛИ
ansible-playbook site.yml --vault-id dev@.vault_pass_dev --vault-id prod@.vault_pass_prod
```

### Предупреждение: `Vault ID label mismatch` (non-strict mode)

**Причина**: `vault_id_match=False` (по умолчанию) и метка в файле не совпадает с ни одним из переданных Vault ID.

```bash
# Включение строгого режима (рекомендуется)
# ansible.cfg
[defaults]
vault_id_match = True

# Или передача всех необходимых Vault ID
ansible-playbook site.yml \
  --vault-id dev@.vault_pass_dev \
  --vault-id prod@.vault_pass_prod \
  --vault-id common@.vault_pass_common
```

## Лучшие практики

- **Строгий режим (`vault_id_match = True`)**: Включайте строгий режим соответствия меток для предотвращения случайного использования ключей не по назначению.
- **Формат 1.2 с метками**: Используйте заголовки версии 1.2 с Vault ID для всех новых проектов; это исключает неоднозначность при расшифровке.
- **Права доступа**: Устанавливайте `chmod 600` на все файлы паролей и ограничивайте доступ к ним.
- **Метаданные**: Избегайте использования чувствительной информации в названиях меток Vault ID — они хранятся в открытом виде в заголовке файла.
- **Оптимизация хранилищ**: Группируйте похожие окружения под одним Vault ID; для файлов версии 1.2 с `vault_id_match=True` производительность не зависит от количества ключей.
- **Приоритет источников**: Используйте переменную окружения `ANSIBLE_VAULT_IDENTITY_LIST` для CI/CD-пайплайнов, а `ansible.cfg` — для локальной разработки.
- **Ротация**: Регулярно меняйте пароли для Vault ID с помощью `ansible-vault rekey` и удаляйте старые файлы паролей после проверки.

**Для SRE:** Внедрите политику ротации мастер-паролей (раз в квартал) и следите за ней через `ansible-vault rekey`. Настройте аудит: логируйте запуски плейбуков с Vault через `ANSIBLE_LOG_PATH`.

**Для Sysadmin:** Настройте `umask 0077` для автоматического ограничения прав на создаваемые файлы паролей. Используйте `ansible-vault view` вместо `decrypt` для чтения секретов на production-хостах — `decrypt` оставляет открытый текст на диске.

## См. также

- [Ansible Vault: Основы](./basics.md) — базовый синтаксис, архитектура шифрования и команды.
- [Управление паролями и источниками](./passwords.md) — детали работы с клиентскими скриптами и CLI.
- [Лучшие практики по безопасности](./best_practices.md) — рекомендации по защите секретов в Git и логах.

## Дополнительная информация

### Граничные случаи

- **Количество Vault ID**: нет технических ограничений; на практике >10 Vault ID замедляют расшифровку файлов версии 1.1 (перебор всех ключей). Для версии 1.2 с `vault_id_match=True` количество не влияет на производительность.
- **Длина Vault ID метки**: рекомендуется до 32 символов; метка хранится в открытом виде в заголовке файла.
- **Специальные символы в Vault ID**: допускаются буквы, цифры, дефисы и подчеркивания; пробелы и знаки `@`, `:` запрещены.
- **Параллельное использование**: при параллельном запуске плейбуков каждый процесс использует свои Vault ID; конфликтов не возникает.
- **Кроссплатформенность**: Vault ID и файлы паролей совместимы между Linux, macOS и Windows (с Python и ansible-core).
- **Приоритет источников**: `ansible.cfg` < переменная окружения < аргументы командной строки.
- **Ротация паролей**: при смене пароля для Vault ID необходимо перешифровать все файлы с этой меткой.
- **Общие секреты**: для секретов, доступных нескольким окружениям, используйте отдельный Vault ID (например, `common`).
- **Утечка метаданных**: Vault ID хранится в открытом виде; избегайте использования конфиденциальной информации в названиях меток.
