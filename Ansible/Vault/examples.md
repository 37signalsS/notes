# Ansible Vault: Практические примеры

## Определения

- **Практические примеры Vault**: Сборник прикладных сценариев применения Ansible Vault для защиты конфиденциальных данных (секретов) в различных окружениях: разработка (Development), непрерывная интеграция и доставка (CI/CD — Continuous Integration / Continuous Delivery) и эксплуатация (Production).
- **Тип переменной File (GitLab CI)**: Механизм CI/CD, при котором содержимое секретной переменной сохраняется во временный файл на диске раннера (Runner), а сама переменная содержит путь к этому файлу.
- **GitHub Secrets**: Зашифрованное хранилище переменных в GitHub Actions, позволяющее безопасно передавать секреты в рабочие процессы (Workflows) через контекст `${{ secrets.NAME }}`.
- **Инлайновое шифрование (Inline Encryption)**: Метод шифрования конкретных значений переменных, позволяющий оставлять структуру YAML-файла (YAML Ain't Markup Language — «YAML не язык разметки») открытой и читаемой для систем контроля версий.
- **Vault Password Script**: Исполняемый файл (Python, Bash), который Ansible вызывает для получения пароля расшифровки. Скрипт должен возвращать только строку пароля в стандартный поток вывода (STDOUT).

## Основные концепции

### Уровни изоляции секретов

При выборе объекта шифрования следует придерживаться принципа гранулярности:
- **Шифрование значений (Рекомендуется)**: Используйте `ansible-vault encrypt_string`. Это сохраняет читаемость Git-диффов (разницы между версиями файлов) и упрощает разрешение конфликтов при слиянии веток.
- **Шифрование файлов**: Подходит для больших блоков данных (например, SSL-сертификатов — Secure Sockets Layer или приватных SSH-ключей — Secure Shell).
- **Метки доступа (Vault ID)**: Позволяют разграничивать доступ к секретам разных команд или окружений (например, `dev` и `prod`) в рамках одного репозитория.

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

### Сценарий 2: Интеграция с Vagrant

Vagrant автоматически передает пароль Vault провижинеру (Provisioner) Ansible, обеспечивая безопасную локальную разработку.

1. **Создание файла пароля**:
    ```bash
    echo "local_dev_pass" > .vault_pass
    # ВАЖНО: Добавьте .vault_pass в .gitignore!
    ```

2. **Настройка `Vagrantfile`**:
    ```ruby
    Vagrant.configure("2") do |config|
      config.vm.provision "ansible" do |ansible|
        ansible.playbook = "playbook.yml"
        # Указание файла пароля для автоматизации
        ansible.vault_password_file = ".vault_pass"
      end
    end
    ```

### Сценарий 3: Современный CI/CD пайплайн (GitLab CI 2024-2025)

Использование переменной типа **File** — стандарт безопасности, исключающий утечку пароля через команды `echo` в логах.

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

### Сценарий 4: Интеграция с GitHub Actions

В GitHub Actions секреты передаются через временные файлы, создаваемые в процессе выполнения Workflow.

1. **Настройка секрета**:
    - `Settings -> Secrets and variables -> Actions`.
    - Создайте секрет `ANSIBLE_VAULT_PASSWORD`.

2. **Конфигурация `.github/workflows/deploy.yml`**:
    ```yaml
    jobs:
      deploy:
        runs-on: ubuntu-latest
        steps:
          - uses: actions/checkout@v4
          - name: Run Playbook
            env:
              VAULT_PASS: ${{ secrets.ANSIBLE_VAULT_PASSWORD }}
            run: |
              echo "$VAULT_PASS" > .vault_pass
              chmod 600 .vault_pass
              ansible-playbook deploy.yml --vault-password-file .vault_pass
              rm .vault_pass
    ```

### Сценарий 5: Использование внешнего хранилища (HashiCorp Vault) через скрипт

Этот метод исключает хранение пароля Vault на диске раннера, получая его динамически через API.

1. **Скрипт получения пароля (`get_vault_pass.py`)**:
    ```python
    #!/usr/bin/env python3
    import os
    import requests

    def get_secret():
        url = "https://vault.example.com/v1/secret/data/ansible"
        token = os.getenv("VAULT_TOKEN")
        response = requests.get(url, headers={"X-Vault-Token": token})
        return response.json()['data']['data']['password']

    if __name__ == "__main__":
        print(get_secret())
    ```

2. **Запуск**:
    ```bash
    export VAULT_TOKEN="s.xyz..."
    ansible-playbook site.yml --vault-password-file ./get_vault_pass.py
    ```

### Сценарий 6: Шифрование строк в YAML-инвентаре

Применяется, когда параметры подключения (например, `ansible_ssh_pass`) специфичны для конкретного хоста.

1. **Генерация зашифрованной строки**:
    ```bash
    ansible-vault encrypt_string 'TargetHostPassword' --name 'ansible_ssh_pass'
    ```

2. **Вставка в инвентарь (`hosts.yml`)**:
    ```yaml
    all:
      hosts:
        db-node-01:
          ansible_host: 192.168.1.50
          ansible_user: deploy
          # Инлайновый секрет
          ansible_ssh_pass: !vault |
            $ANSIBLE_VAULT;1.1;AES256
            6633363365313835663738643633393165333066373238313437346132333036
    ```

### Сценарий 7: Массовая перешифровка (Batch Rekeying)

Используется для смены паролей во всем проекте одной командой.

```bash
# Поиск всех vault-файлов и смена пароля
find group_vars host_vars -name "*.vault.yml" | \
xargs ansible-vault rekey --vault-id old@.old_pass --new-vault-id new@.new_pass
```

### Сценарий 8: Извлечение секрета через CLI (Debug)

Иногда нужно проверить значение секрета без запуска полного плейбука.

```bash
# Вывод конкретной переменной из зашифрованного файла
ansible localhost -m debug -a "var=db_password" -e "@group_vars/all/vault.yml" --vault-password-file .vault_pass
```

### Сценарий 9: Валидация гигиены секретов с ansible-lint

Использование статического анализа для предотвращения случайного коммита открытых секретов.

1. **Настройка правила**:
    `ansible-lint` автоматически проверяет наличие директивы `no_log: true` в задачах, использующих переменные с именами `password`, `secret`, `token`.

2. **Пример защищенной задачи**:
    ```yaml
    - name: Get secret from HashiCorp Vault via API
      ansible.builtin.uri:
        url: "https://vault.example.com/v1/secret/data/app"
        headers:
          X-Vault-Token: "{{ vault_token }}"
      register: vault_response
      # Обязательно для предотвращения утечки содержимого ответа в логи
      no_log: true 
    ```

### Сценарий 10: Интеграция с HashiCorp Vault через lookup-плагин

Современный подход вместо скриптов — прямое получение секретов из HashiCorp Vault без промежуточных файлов.

1. **Установка плагина**:
    ```bash
    ansible-galaxy collection install community.hashicorp
    ```

2. **Конфигурация плейбука**:
    ```yaml
    - name: Получение секретов из HashiCorp Vault
      hosts: localhost
      vars:
        vault_token: "{{ lookup('env', 'VAULT_TOKEN') }}"
      tasks:
        - name: Получение пароля БД из Vault
          ansible.builtin.set_fact:
            db_password: "{{ lookup('community.hashicorp.vault_kv2_get', 'kv/data/db', token=vault_token).secret.password }}"
          no_log: true

        - name: Использование секрета
          ansible.builtin.debug:
            msg: "Длина пароля: {{ db_password | length }}"
    ```

3. **Конфигурация `~/.vault`** (опционально):
    ```hcl
    vault {
      address = "https://vault.example.com:8200"
    }
    ```

### Сценарий 11: Интеграция с Docker и Docker Compose

Безопасная передача секретов в контейнеризированные приложения.

**Способ 1: Docker BuildKit с секретами** (рекомендуется):
```dockerfile
# Dockerfile
RUN --mount=type=secret,id=vault_token \
    VAULT_TOKEN=$(cat /run/secrets/vault_token) && \
    ansible-playbook site.yml --vault-password-file /dev/stdin <<< "$VAULT_TOKEN"
```

```bash
# Сборка с секретом
export VAULT_TOKEN=$(vault login -method=oidc -token-only)
docker build --secret id=vault_token,env=VAULT_TOKEN -t my-app .
```

**Способ 2: Docker Compose с Vault Agent**:
```yaml
# docker-compose.yml
version: '3.8'
services:
  app:
    image: my-app:latest
    depends_on:
      - vault-agent
    tmpfs:
      - /secrets:size=1M,noexec,nosuid

  vault-agent:
    image: hashicorp/vault:1.15
    cap_add:
      - IPC_LOCK
    command: agent -config=/etc/vault/config.hcl
    volumes:
      - ./agent-config.hcl:/etc/vault/config.hcl:ro
```

### Сценарий 12: Мультиокружественный деплой с Vault IDs

Безопасное управление секретами для dev/staging/prod в одном пайплайне.

1. **Структура файлов**:
    ```
    group_vars/
    ├── dev/
    │   ├── vars.yml      # Обычные переменные
    │   └── vault.yml     # Секреты dev (метка: dev)
    ├── staging/
    │   ├── vars.yml
    │   └── vault.yml     # Секреты staging (метка: staging)
    └── prod/
        ├── vars.yml
        └── vault.yml     # Секреты prod (метка: prod)
    ```

2. **Создание зашифрованных файлов**:
    ```bash
    # Dev
    ansible-vault create --vault-id dev@.vault_pass_dev group_vars/dev/vault.yml

    # Staging
    ansible-vault create --vault-id staging@.vault_pass_staging group_vars/staging/vault.yml

    # Prod
    ansible-vault create --vault-id prod@.vault_pass_prod group_vars/prod/vault.yml
    ```

3. **Запуск для конкретного окружения**:
    ```bash
    # Только dev
    ansible-playbook site.yml --limit dev --vault-id dev@.vault_pass_dev

    # Все окружения
    ansible-playbook site.yml \
      --vault-id dev@.vault_pass_dev \
      --vault-id staging@.vault_pass_staging \
      --vault-id prod@.vault_pass_prod
    ```

### Сценарий 13: Настройка через ansible.cfg

Централизованная конфигурация Vault без передачи флагов в каждой команде.

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

### Сценарий 14: Шифрование целых каталогов

Массовое шифрование всех файлов переменных в проекте.

```bash
# Шифрование всех vault-файлов
find group_vars host_vars -name "*.vault.yml" -exec ansible-vault encrypt {} \;

# Проверка зашифрования
for f in $(find group_vars host_vars -name "*.vault.yml"); do
  echo "=== $f ==="
  head -1 "$f"
done

# Расшифровка для временной работы (УДАЛИТЕ после использования!)
ansible-vault decrypt group_vars/prod/vault.yml
# ... работа с открытыми секретами ...
ansible-vault encrypt group_vars/prod/vault.yml
```

### Сценарий 15: Использование Vault в ролях

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
      $ANSIBLE_VAULT;1.1;AES256
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

4. **Запуск сVault**:
    ```bash
    ansible-playbook site.yml --vault-password-file .vault_pass
    ```

## Дополнительная информация

### Устранение неполадок

#### Ошибка: `Decryption failed` при запуске CI/CD

**Причина**: файл пароля не имеет правил `chmod 600` или Vault ID не совпадает.

**Решение**:
```bash
# GitLab CI — добавьте в before_script
chmod 600 "$VAULT_PASS_FILE"

# Проверьте Vault ID в заголовке
head -1 group_vars/all/vault.yml
# → $ANSIBLE_VAULT;1.2;AES256;prod (нужен пароль для "prod")
```

#### Ошибка: `Vault password file not found` в Docker

**Причина**: файл пароля не смонтирован в контейнер.

**Решение**:
```yaml
# docker-compose.yml
services:
  app:
    volumes:
      - ./.vault_pass:/run/secrets/vault_pass:ro
    environment:
      - ANSIBLE_VAULT_PASSWORD_FILE=/run/secrets/vault_pass
```

### Граничные случаи

- **Смешанные файлы**: файл может содержать как обычные, так и зашифрованные переменные
- **Кэширование фактов**: при использовании `cache_fact = True` секреты могут попасть в кэш
- **Переменные окружения**: Ansible **не поддерживает** прямую передачу пароля через `ANSIBLE_VAULT_PASSWORD` — только через `ANSIBLE_VAULT_PASSWORD_FILE`

### Справочник переменных окружения

| Переменная | Описание | Пример |
|------------|----------|--------|
| `ANSIBLE_VAULT_PASSWORD_FILE` | Путь к файлу пароля | `export ANSIBLE_VAULT_PASSWORD_FILE=~/.vault_pass` |
| `ANSIBLE_VAULT_IDentities` | Список Vault ID | `export ANSIBLE_VAULT_IDentities="dev@~/.vault_dev"` |
| `VAULT_TOKEN` | Токен HashiCorp Vault | `export VAULT_TOKEN="s.xxxx"` |
| `VAULT_ADDR` | Адрес сервера Vault | `export VAULT_ADDR="https://vault.example.com:8200"` |

### Связанные руководства

- [Ansible Vault: Основы](./basics.md) — базовые команды и версии заголовков.
- [Лучшие практики по безопасности](./best_practices.md) — глубокое погружение в `no_log` и эшелонированную защиту.
- [Управление паролями и источниками](./passwords.md) — детали работы с `--vault-id` и скриптами.
- [Алгоритмы и криптосхемы](./algorithms.md) — подробности шифрования AES-256-CTR (Advanced Encryption Standard).
- [Интеграция Vault с Docker](../Vault/guides/vault_docker_integration.md) — контейнеризация и безопасность секретов.
