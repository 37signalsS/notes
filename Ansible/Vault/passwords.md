# Ansible Vault: Управление паролями

## Определения

- **Источник пароля (Password Source)**: Метод, с помощью которого Ansible получает ключ для расшифровки данных. Выбор метода зависит от требований к автоматизации и уровня безопасности.
- **Идентификатор хранилища (Vault ID)**: Метка (например, `dev`, `prod`), позволяющая связать зашифрованный файл с конкретным паролем или источником при использовании нескольких хранилищ (Multi-Vault).
- **Клиентский скрипт (Client Script)**: Исполняемый файл (Python, Bash), который Ansible запускает для динамического получения пароля из внешних систем управления секретами (HashiCorp Vault, AWS Secrets Manager, KeepassXC).
- **GPG-шифрование (GNU Privacy Guard)**: Протокол шифрования, используемый для защиты самих файлов паролей Vault. Позволяет хранить пароли в репозитории в зашифрованном виде, расшифровывая их «на лету» через скрипт.
- **OIDC (OpenID Connect)**: Современный стандарт аутентификации, позволяющий CI/CD-пайплайнам получать временные токены доступа к менеджерам секретов без использования статических паролей.
- **STDOUT (Standard Output)**: Стандартный поток вывода, куда клиентский скрипт должен выводить пароль для его считывания инструментом Ansible.

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

## Гигиена и безопасность в Production

- **Минимизация записи на диск**: В Production всегда предпочитайте передачу пароля через дескрипторы файлов (`<(echo $PASS)`) или клиентские скрипты, чтобы избежать появления расшифрованного пароля в файловой системе.
- **Маскирование в логах**: Убедитесь, что ваш CI-сервер маскирует переменные, которые используются для получения паролей Vault.
- **Принцип минимальных привилегий**: AppRole в HashiCorp Vault должен иметь доступ `read` только к тем путям, которые необходимы для конкретного плейбука.
- **Аудит**: Логируйте обращения к мастер-паролям в системе управления секретами для отслеживания несанкционированных запусков плейбуков.

## Дополнительная информация

### Углубленные темы
- [Ansible Vault: Основы](./basics.md) — базовый синтаксис и версии заголовков.
- [Использование нескольких хранилищ (Multi-Vault)](./multi_vault.md) — детальная работа с Vault ID и метками.
- [Лучшие практики по безопасности](./best_practices.md) — директива `no_log`, OIDC (OpenID Connect) и защита при выполнении.

### Технические детали
- [Практические примеры использования](./examples.md) — реальные сценарии применения в инфраструктуре.
- [Алгоритмы шифрования](./algorithms.md) — подробности AES-256 (Advanced Encryption Standard) и криптографических схем.
