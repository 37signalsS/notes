# Ansible Vault: Лучшие практики

## Определения

- **Лучшие практики Vault**: Набор проверенных правил и техник, направленных на минимизацию риска утечки секретов как в состоянии покоя (в Git), так и во время выполнения автоматизации (в логах, кэше, отчетах).
- **Принцип минимального раскрытия (Least Exposure)**: Стратегия, при которой секретные данные остаются зашифрованными максимально долго и расшифровываются только в момент непосредственного использования в памяти процесса.
- **Эшелонированная защита (Defense in Depth)**: Подход к безопасности, при котором используется несколько уровней контроля (анализ, изоляция, защита при выполнении), обеспечивающий сохранность данных даже при компрометации одного из уровней.
- **OIDC (OpenID Connect)**: Современный стандарт аутентификации, позволяющий CI/CD-пайплайнам (GitLab CI, GitHub Actions) получать временные токены доступа к менеджерам секретов без использования статических паролей.
- **AppRole**: Метод аутентификации в HashiCorp Vault, предназначенный для машин и скриптов, использующий пару `RoleID` и `SecretID`.
- **SOPS (Secrets OPerationS)**: Инструмент для шифрования только значений в YAML/JSON файлах, поддерживающий облачные KMS (AWS, GCP, Azure) и PGP.
- **EncryptedString (Core 2.19+)**: Внутренний тип данных в Ansible, автоматически помечающий секреты для предотвращения их случайного вывода в логи или консоль.

## Предварительные требования

Для применения рекомендаций из данного руководства необходимы:

- **Ansible**: версия 2.4 или выше (рекомендуется ansible-core 2.12+ для полной поддержки Vault ID и EncryptedString).
- **Python**: 3.8+ (совместимость с ansible-core 2.12+).
- **ansible-lint**: для статического анализа (правило `no-log-password`). Установка: `pip install ansible-lint`.
- **pre-commit**: для автоматической проверки перед коммитом (опционально). Установка: `pip install pre-commit`.
- **gitleaks**: для поиска plain-text секретов в Git-истории (опционально). Установка: `brew install gitleaks` (macOS) или `go install github.com/gitleaks/gitleaks/v8@latest`.
- **GPG**: для шифрования файлов паролей (опционально). Установка: `brew install gnupg` (macOS) или `apt install gnupg` (Linux).
- **SOPS**: для шифрования только значений в YAML/JSON файлах (опционально). Установка: `brew install sops` (macOS) или `snap install sops` (Linux).

Проверка версий:
```bash
ansible --version | head -1
# → ansible [core 2.12.0] или выше

ansible-lint --version
# → ansible-lint 6.0.0 или выше

pre-commit --version
# → pre-commit 3.0.0 или выше

gitleaks version
# → v8.18.0 или выше
```

## Основные концепции

### Уровни защиты секретов (Эшелонированная защита)

Безопасность секретов в Ansible строится на четырех фундаментальных уровнях:

1.  **Статический анализ**: Использование линтеров (`ansible-lint`) и `pre-commit` хуков для предотвращения коммита открытых секретов.
2.  **Изоляция в репозитории**: Четкое разделение переменных и кода, использование зашифрованных строк (`encrypt_string`) вместо шифрования целых файлов для сохранения читаемости YAML и Git-диффов.
3.  **Защита Control Node**: Ограничение доступа к мастер-паролям Vault. Использование динамических источников (скрипты, Keyring, GPG, OIDC) вместо хранения `vault_pass.txt` на диске.
4.  **Защита при выполнении (Runtime)**: Использование директив `no_log`, управление кэшированием фактов и ограничение прав доступа на целевых хостах.

### Криптографические ограничения и актуальность (2024-2026)

Ansible Vault использует схему **AES-256-CTR** с **10 000 итерациями PBKDF2-HMAC-SHA256**.
- **Критическое замечание**: 10 000 итераций — это низкий показатель по современным стандартам безопасности (OWASP рекомендует от 600 000+). Это делает файлы Vault уязвимыми к офлайн-перебору на GPU (видеокартах).
- **Рекомендация**: Используйте мастер-пароли Vault длиной **не менее 20-25 символов** с высокой энтропией.
- **Data Tagging (Core 2.19+)**: Механизм `EncryptedString` позволяет системе отслеживать происхождение данных. Если переменная была получена из Vault, Ansible будет блокировать её вывод даже при неявном использовании в модулях отладки.

## Практические сценарии

### Сценарий 1: Предотвращение утечек в логах (`no_log: true`)

Даже если переменная зашифрована, ее значение может попасть в логи при выполнении задачи.

**Проблема (Уязвимо):**
```yaml
- name: Create database user
  community.postgresql.postgresql_user:
    name: "{{ db_user }}"
    password: "{{ db_password }}" # db_password будет виден в логах
```

**Решение (Стандарт безопасности):**
Добавляйте `no_log: true` к любой задаче, работающей с секретами. Это скроет параметры и вывод из консоли и логов.
```yaml
- name: Create database user
  community.postgresql.postgresql_user:
    name: "{{ db_user }}"
    password: "{{ db_password }}"
  no_log: true
```

### Сценарий 2: Безопасная организация репозитория

- **Разделяйте конфигурацию и секреты**: Храните секреты в отдельных файлах (например, `prod.vault.yml`) в каталогах `group_vars/` или `host_vars/`.
- **Используйте `encrypt_string` для прозрачности**: Вместо шифрования всего файла зашифруйте только значение переменной. Это позволяет видеть названия ключей в Git и упрощает Code Review.
  ```yaml
  # group_vars/all/secrets.yml
  db_password: !vault |
            $ANSIBLE_VAULT;1.1;AES256
            36383633...
  ```
- **Исключайте открытые секреты**: Всегда добавляйте `vault_pass.txt` и временные файлы в `.gitignore`.

### Сценарий 3: Предотвращение кэширования секретов

Если вы сохраняете секрет как факт через `set_fact`, он может быть записан на диск в кэш-файлы (`fact_caching`).

```yaml
- name: Получение секрета из внешнего источника
  ansible.builtin.set_fact:
    api_token: "{{ lookup('env', 'API_TOKEN') }}"
    # ГАРАНТИРУЕТ, что факт не попадет в долгоживущий кэш
    cacheable: false 
  no_log: true
```

### Сценарий 4: Именование и косвенная адресация

Для предотвращения случайных утечек используйте префикс `vault_` и разделяйте декларацию и использование.

**Рекомендуемый подход:**
1. Зашифруйте значение с префиксом: `vault_db_password: !vault | ...`
2. Создайте публичную переменную-ссылку в другом файле: `db_password: "{{ vault_db_password }}"`

Это позволяет легко искать использование секретов через `grep` и менять источник секрета (например, переход на HashiCorp Vault), не меняя код плейбуков.

### Сценарий 5: Статический анализ и автоматизация (`pre-commit`)

1. **`ansible-lint`**: Правило `no-log-password` автоматически находит задачи, где используются переменные со словами `password`, `secret`, `token`, но отсутствует `no_log: true`.
2. **`pre-commit` хуки**: Используйте `ansible-vault-check` для проверки зашифрованности файлов и `gitleaks` для поиска plain-text секретов.
   ```yaml
   - repo: https://github.com/gitleaks/gitleaks
     rev: v8.21.2
     hooks:
       - id: gitleaks
   ```

### Сценарий 6: Ротация паролей и Rekey

Регулярная смена мастер-пароля — обязательная мера. При смене используйте `rekey`.

```bash
# Смена пароля во всех YAML-файлах репозитория
find . -type f -name "*.yml" -exec grep -l "\$ANSIBLE_VAULT" {} + | \
xargs ansible-vault rekey --vault-id old@source --new-vault-id new@source
```

### Сценарий 7: Безопасное редактирование (`view` vs `edit`)

Команда `ansible-vault edit` создает временную копию файла в `/tmp`.
- **Риск**: На общих Control Node (Shared Server) другие пользователи могут попытаться прочитать временный файл в момент редактирования.
- **Рекомендация**: Используйте `ansible-vault view` для чтения. Для редактирования на общих серверах убедитесь, что `$TMPDIR` указывает на вашу личную защищенную директорию (`chmod 700`).

### Сценарий 8: Интеграция с внешними менеджерами секретов (HashiCorp, AWS)

Для крупных Production сред рекомендуется использовать внешние системы как основной SSoT секретов.
- **Lookup-плагины**: Прямое получение из HashiCorp Vault, AWS Secrets Manager или 1Password во время выполнения.
  ```yaml
  - name: Получение пароля БД из HashiCorp Vault
    set_fact:
      db_pass: "{{ lookup('community.hashicorp.vault_kv2_get', 'kv/data/db').secret.password }}"
    no_log: true
  ```
- **OIDC (OpenID Connect)**: Использование беспарольной аутентификации в GitLab CI (17.0+) для получения динамических секретов.

### Сценарий 9: Шаблоны с секретами —Hardening

Когда `ansible.builtin.template` рендерит шаблон, итоговый файл на целевой машине содержит секрет в открытом виде.

**Меры защиты:**
- **Права доступа**: Всегда ограничивайте права доступа: `mode: '0600'` или `'0400'`.
- **Ephemeral storage**: По возможности записывайте чувствительные конфиги в `tmpfs` (RAM-диск).
- **no_log**: Скроет утечку из логов при рендеринге шаблона.

### Сценарий 10: Docker Swarm/Kubernetes — использование Secrets

Типичная ошибка — подстановка пароля напрямую в `environment`. Правильный подход: использование встроенных механизмов оркестраторов.

```yaml
# docker-compose.yml — БЕЗОПАСНО: пароль передается через файл в RAM (tmpfs)
services:
  db:
    image: postgres:16-alpine
    secrets:
      - db_password
    environment:
      # Приложение должно поддерживать чтение из файла
      POSTGRES_PASSWORD_FILE: /run/secrets/db_password

secrets:
  db_password:
    external: true
```

### Сценарий 11: EncryptedString и Data Tagging (ansible-core 2.19+)

Механизм `EncryptedString` автоматически отслеживает происхождение данных и блокирует вывод секретов в логи:

```yaml
# Автоматическое определение Vault-переменных
- name: Получение секрета из Vault
  ansible.builtin.set_fact:
    api_key: "{{ vault_api_key }}"
  # EncryptedString автоматически помечает api_key как секрет

# Попытка вывода секрета через debug — БЕЗОПАСНО
- name: Вывод переменной (секрет будет скрыт)
  ansible.builtin.debug:
    var: api_key
  # → Вывод: "api_key: [VALUE_IS_ENCRYPTED]"

# Явный вывод секрета (только для отладки)
- name: Явный вывод секрета (ОПАСНО — только в dev)
  ansible.builtin.debug:
    msg: "API Key: {{ api_key }}"
  when: environment == "dev"
  no_log: true
```

**Важно:** `EncryptedString` работает только с переменными, полученными из Vault. Для секретов, полученных из других источников (env, lookup), используйте `no_log: true` явно.

### Сценарий 12: SOPS — шифрование только значений в YAML

SOPS (Secrets OPerationS) позволяет шифровать только значения переменных, сохраняя читаемость ключей:

```bash
# Установка SOPS
brew install sops  # macOS
# или
snap install sops  # Linux

# Шифрование файла с использованием GPG
sops --encrypt --in-place group_vars/prod/secrets.yml

# Шифрование с использованием AWS KMS
sops --encrypt --kms "arn:aws:kms:us-east-1:123456789012:key/12345678-1234-1234-1234-123456789012" \
  --in-place group_vars/prod/secrets.yml
```

```yaml
# group_vars/prod/secrets.yml (после шифрования)
db_password: ENC[AES256_GCM,data:encrypted_data_here,iv:iv_here,tag:tag_here]
api_key: ENC[AES256_GCM,data:another_encrypted_data,iv:iv_here,tag:tag_here]
```

```bash
# Расшифровка для чтения
sops --decrypt group_vars/prod/secrets.yml

# Редактирование (автоматическая расшифровка и перешифровка)
sops group_vars/prod/secrets.yml
```

**Интеграция с Ansible:** SOPS-зашифрованные значения можно использовать через lookup-плагин:
```yaml
- name: Получение секрета из SOPS
  ansible.builtin.set_fact:
    db_password: "{{ lookup('community.sops.sops', 'group_vars/prod/secrets.yml', key='db_password') }}"
  no_log: true
```

### Сценарий 13: GPG-шифрование файлов паролей Vault

Использование GPG для дополнительной защиты файлов паролей Vault:

```bash
# Создание GPG-ключа (если нет)
gpg --gen-key

# Шифрование файла пароля Vault
gpg --encrypt --recipient your@email.com .vault_pass_prod
# → .vault_pass_prod.gpg

# Удаление открытого файла
rm .vault_pass_prod

# Создание скрипта для расшифровки
cat > fetch_vault_pass.sh << 'EOF'
#!/bin/bash
gpg --decrypt .vault_pass_prod.gpg 2>/dev/null
EOF
chmod +x fetch_vault_pass.sh
```

```ini
# ansible.cfg
[defaults]
vault_password_file = ./fetch_vault_pass.sh
```

**Преимущества:** Файл пароля зашифрован на диске; расшифровывается только в момент использования; ключ GPG может быть защищен passphrase.

### Сценарий 14: Безопасность в CI/CD (GitHub Actions, GitLab CI)

Правила безопасной работы с Vault в CI/CD:

```yaml
# .github/workflows/secure_deploy.yml
name: Secure Deploy with Vault
on:
  push:
    branches: [main]

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Decrypt vault password
        env:
          VAULT_PASS_ENCRYPTED: ${{ secrets.VAULT_PASS_GPG }}
          GPG_PRIVATE_KEY: ${{ secrets.GPG_PRIVATE_KEY }}
          GPG_PASSPHRASE: ${{ secrets.GPG_PASSPHRASE }}
        run: |
          echo "$GPG_PRIVATE_KEY" > /tmp/gpg_key.asc
          gpg --import /tmp/gpg_key.asc
          rm /tmp/gpg_key.asc
          echo "$VAULT_PASS_ENCRYPTED" | gpg --decrypt --batch --passphrase "$GPG_PASSPHRASE" > /tmp/.vault_pass
          chmod 600 /tmp/.vault_pass

      - name: Run playbook
        env:
          ANSIBLE_VAULT_PASSWORD_FILE: /tmp/.vault_pass
        run: |
          ansible-playbook --vault-password-file /tmp/.vault_pass site.yml

      - name: Cleanup
        if: always()
        run: rm -f /tmp/.vault_pass /tmp/gpg_key.asc
```

**Ключевые принципы:**
- Никогда не храните пароли Vault в переменных окружения в открытом виде.
- Используйте зашифрованные секреты GitHub/GitLab для хранения зашифрованных паролей.
- Расшифровывайте пароли только в момент использования и удаляйте после.
- Ограничивайте доступ к секретам на уровне веток/окружений.

### Сценарий 15: Мониторинг и аудит использования Vault

Настройка логирования и мониторинга операций с Vault:

```bash
# Включение логирования Ansible
export ANSIBLE_LOG_PATH="/var/log/ansible/ansible.log"
export ANSIBLE_DEBUG=True  # Только для отладки!

# Просмотр логов Vault-операций
grep -i "vault" /var/log/ansible/ansible.log | tail -20

# Проверка использования секретов в логах (поиск утечек)
grep -E "(password|secret|token|key).*=" /var/log/ansible/ansible.log | grep -v "VALUE_IS_ENCRYPTED"
# Если есть результаты — секреты утекают в логи!
```

**Рекомендации по аудиту:**
- Регулярно проверяйте логи на наличие открытых секретов.
- Используйте `ansible-lint` для автоматического поиска задач без `no_log`.
- Настройте алерты на попытки вывода Vault-переменных в логи.
- Ведите журнал ротации паролей Vault.

### Сценарий 16: Структура репозитория для безопасности

Рекомендуемая структура каталогов для максимальной безопасности:

```
ansible-project/
├── ansible.cfg                  # Конфигурация (vault_password_file)
├── .gitignore                   # Исключения для Git
├── .pre-commit-config.yaml      # Pre-commit хуки
├── group_vars/
│   ├── all/
│   │   ├── vars.yml             # Общие переменные (открытые)
│   │   └── vault.yml            # Общие секреты (зашифрованы)
│   ├── dev/
│   │   ├── vars.yml             # Dev-переменные
│   │   └── vault.yml            # Dev-секреты
│   └── prod/
│       ├── vars.yml             # Prod-переменные
│       └── vault.yml            # Prod-секреты
├── host_vars/
│   └── db-primary/
│       └── vault.yml            # Секреты конкретного хоста
├── roles/
│   └── common/
│       ├── defaults/
│       │   └── main.yml         # Значения по умолчанию (открытые)
│       └── vars/
│           └── main.yml         # Переменные роли
├── playbooks/
│   └── site.yml                 # Основной плейбук
├── inventory/
│   ├── hosts                    # Инвентарь
│   └── group_vars/              # Групповые переменные (для инвентаря)
├── scripts/
│   ├── fetch_vault_pass.sh      # Скрипт получения пароля Vault
│   └── rotate_vault.sh          # Скрипт ротации паролей
└── docs/
    └── vault-management.md      # Документация по управлению Vault
```

**Правила:**
- Все `vault.yml` файлы должны быть зашифрованы.
- Файлы паролей (`vault_pass*`) не должны находиться в репозитории.
- Используйте `.gitignore` для исключения секретов.
- Разделяйте переменные и секреты по окружениям.
- Ведите документацию по управлению Vault.

## Устранение неполадок

### Ошибка: `Vault password not found` при использовании скрипта

**Причина**: скрипт получения пароля не найден, не executable или содержит ошибки.

```bash
# Проверка существования скрипта
ls -la scripts/fetch_vault_pass.sh

# Проверка прав доступа
chmod +x scripts/fetch_vault_pass.sh

# Проверка работоспособности скрипта
./scripts/fetch_vault_pass.sh
# → Должен вывести пароль Vault

# Проверка shebang
head -1 scripts/fetch_vault_pass.sh
# → Должно быть: #!/bin/bash или #!/usr/bin/env bash
```

### Ошибка: `Permission denied` при чтении файла пароля

**Причина**: неправильные права доступа на файл пароля Vault.

```bash
# Проверка прав доступа
ls -la .vault_pass_*
# → Должно быть: -rw------- (600)

# Исправление прав
chmod 600 .vault_pass_*

# Проверка владельца
ls -la .vault_pass_*
# → Должно быть: owner:group (не root:root на общих серверах)
```

### Предупреждение: `no_log` не скрывает секрет в логах

**Причина**: `no_log: true` применяется к задаче, но секрет выводится через `debug` или `register` в другой задаче.

```yaml
# НЕПРАВИЛЬНО: секрет утекает через register
- name: Получение секрета
  ansible.builtin.set_fact:
    db_password: "{{ vault_db_password }}"
  no_log: true

- name: Вывод секрета (УТЕЧКА!)
  ansible.builtin.debug:
    var: db_password
  # register также может вызвать утечку

# ПРАВИЛЬНО: no_log на всех задачах с секретами
- name: Получение секрета
  ansible.builtin.set_fact:
    db_password: "{{ vault_db_password }}"
  no_log: true

- name: Использование секрета
  ansible.builtin.template:
    src: templates/db.conf.j2
    dest: /etc/app/db.conf
    mode: '0600'
  no_log: true
```

### Ошибка: `ansible-lint` не находит нарушений `no-log-password`

**Причина**: правило `no-log-password` может быть отключено или переменная не содержит ключевых слов.

```bash
# Включение правила в .ansible-lint
cat > .ansible-lint << EOF
enable_list:
  - no-log-password
  - yaml[line-length]
  - name[template]
EOF

# Проверка конкретного файла
ansible-lint --rules .ansible-lint playbooks/deploy.yml

# Ручной поиск задач с password/secret без no_log
grep -n -E "(password|secret|token|key).*:" playbooks/*.yml | \
  xargs -I {} sh -c 'grep -q "no_log: true" {} || echo "УТЕЧКА: {}"'
```

### Ошибка: `gitleaks` не находит секреты в Git-истории

**Причина**: gitleaks не настроен или секреты зашифрованы Vault.

```bash
# Проверка конфигурации gitleaks
cat > .gitleaks.toml << EOF
[allowlist]
  description = "Allow Ansible Vault encrypted strings"
  regexes = ['''\\$ANSIBLE_VAULT;1\.[12];AES256''']
  paths = ['''group_vars/.*\.yml$''']
EOF

# Запуск с конфигурацией
gitleaks detect --config .gitleaks.toml --verbose

# Просмотр Git-истории на наличие секретов
git log --all --full-history -- "*.yml" | grep -v "\$ANSIBLE_VAULT"
```

## Граничные случаи и ограничения

- **`no_log` и `debug`**: `no_log: true` скрывает вывод задачи, но не скрывает переменные, используемые в `register` или `debug` без `no_log`.
- **`EncryptedString` и lookup-плагины**: `EncryptedString` работает только с переменными, полученными напрямую из Vault. Lookup-плагины (HashiCorp, AWS) не помечают переменные как `EncryptedString`.
- **SOPS и Ansible**: SOPS-зашифрованные значения не расшифровываются автоматически Ansible; требуется lookup-плагин `community.sops.sops`.
- **Pre-commit хуки и обход**: Pre-commit хуки можно обойти через `git commit --no-verify`; используйте серверные хуки Git для дополнительной защиты.
- **GPG-шифрование и производительность**: GPG-расшифровка добавляет задержку (~100-500 мс) к каждому запуску плейбука.
- **Vault Pass скрипты и безопасность**: Скрипты получения пароля не должны логировать пароль; используйте `set +x` для отключения отладки.
- **`rekey` и parаллельное выполнение**: Не запускайте `ansible-vault rekey` parаллельно для файлов из одного окружения; это может привести к race condition.
- **Docker и tmpfs**: При использовании Docker Secrets убедитесь, что приложение поддерживает чтение пароля из файла (`*_FILE` переменные).
- **CI/CD и temporary files**: В CI/CD всегда удаляйте временные файлы с секретами в `post` шагах или `if: always()`.
- **Множественные Vault ID и производительность**: При использовании >10 Vault ID с форматом 1.1 (без меток) время расшифровки увеличивается пропорционально количеству хранилищ.

## Справочник переменных окружения

| Переменная | Описание | Приоритет |
|------------|----------|-----------|
| `ANSIBLE_VAULT_PASSWORD_FILE` | Путь к файлу или скрипту с паролем Vault | Высокий (перезаписывает `ansible.cfg`) |
| `ANSIBLE_VAULT_IDENTITY_LIST` | Список Vault ID через запятую (формат: `id1@pass1, id2@pass2`) | Средний (перезаписывает `ansible.cfg`) |
| `ANSIBLE_VAULT_ENCRYPT_IDENTITY` | Vault ID для шифрования по умолчанию | Средний |
| `ANSIBLE_LOG_PATH` | Путь к файлу логов Ansible | Низкий (для аудита) |
| `ANSIBLE_DEBUG` | Включение отладочного режима (True/False) | Низкий (только для отладки) |
| `TMPDIR` | Директория для временных файлов (важно для безопасности `ansible-vault edit`) | Системная |

**Приоритет аргументов командной строки**: `--vault-password-file` > `ANSIBLE_VAULT_PASSWORD_FILE` > `vault_password_file` в `ansible.cfg`.

## Дополнительная информация

### Связанные руководства
- [Ansible Vault: Основы](./basics.md) — базовый синтаксис, создание и редактирование файлов.
- [Управление паролями и источниками](./passwords.md) — настройка клиентских скриптов и иерархия приоритетов.
- [Использование нескольких хранилищ (Multi-Vault)](./multi_vault.md) — детальная работа с Vault ID и метками.

### Технический справочник
- [Практические примеры использования](./examples.md) — реальные сценарии применения в инфраструктуре.
- [Алгоритмы шифрования](./algorithms.md) — подробности формата заголовка 1.2 и использования AES-256-CTR.

### Ссылки и стандарты
- [Ansible Security Best Practices Official](https://docs.ansible.com/ansible/latest/user_guide/playbooks_best_practices.html#security-best-practices)
- [OWASP Password Storage Cheat Sheet 2025](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html)
- [Gitleaks: Scan for secrets](https://github.com/gitleaks/gitleaks)
- [SOPS: Secrets OPerationS](https://github.com/getsops/sops)
- [Ansible-lint: no-log-password](https://docs.ansible-lint.com/rules/no-log-password/)
