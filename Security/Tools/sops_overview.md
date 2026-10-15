# SOPS (Secrets OPerationS) — обзор и руководство

## 1. Определения

**SOPS (Secrets OPerationS)** — это инструмент с открытым исходным кодом для управления секретами, изначально разработанный Mozilla, а в 2023 году переданный в **CNCF (Sandbox)**. Он представляет собой редактор зашифрованных файлов, который позволяет безопасно хранить структурированные данные (YAML, JSON, .env, INI, BINARY) в системах контроля версий, таких как Git.

В 2026 году SOPS остается отраслевым стандартом для GitOps-пайплайнов благодаря своей способности шифровать только **значения (values)**, оставляя **ключи (keys)** в открытом виде. Это сохраняет читаемость структуры файлов и позволяет использовать стандартные инструменты сравнения (`git diff`) без риска утечки данных.

## 2. Основные концепции

### Модель шифрования
Ключевая особенность SOPS — использование **конвертной модели шифрования (envelope encryption)**:
1. Для каждого файла генерируется уникальный 256-битный симметричный **ключ шифрования данных (DEK)**.
2. Данные шифруются этим DEK с использованием алгоритма AES-GCM (или ChaCha20-Poly1305).
3. Сам DEK шифруется одним или несколькими **мастер-ключами**.
4. Зашифрованный DEK и метаданные (информация о мастер-ключах) хранятся в секции `sops` внутри самого файла.

### Мастер-ключи
В качестве мастер-ключей могут выступать:
- **Облачные KMS:** AWS KMS, Google Cloud KMS, Azure Key Vault. Рекомендуется для production-сред в 2026 году.
- **age:** (Actually Good Encryption) — современная, простая и быстрая альтернатива PGP. Рекомендуемый метод для локальной разработки и командной работы.
- **PGP / GPG:** Традиционный метод, постепенно вытесняемый `age` из-за сложности управления ключевыми парами.
- **HashiCorp Vault:** Интеграция с централизованными хранилищами секретов.

## 3. Практические сценарии

### Установка
В 2026 году актуальной стабильной версией является **v3.13.0**.

```bash
# Загрузка бинарного файла (пример для Linux amd64)
wget https://github.com/getsops/sops/releases/latest/download/sops-linux-amd64
chmod +x sops-linux-amd64
sudo mv sops-linux-amd64 /usr/local/bin/sops

# Проверка версии
sops --version
```

### Шифрование файла

1.  **Подготовка исходного файла:**
    ```yaml
    # secrets.yaml
    db_password: "SuperSecretPassword123"
    api_key: "abc-123"
    ```

2.  **Варианты шифрования:**

    **Вариант A — PGP:**
    ```bash
    sops --encrypt --pgp YOUR_PGP_FINGERPRINT secrets.yaml > secrets.enc.yaml
    ```

    **Вариант B — age (Рекомендуется в 2026):**
    ```bash
    # Генерирование ключа (если нет)
    age-keygen -o age.key
    # Зашифрование публичным ключом
    sops --encrypt --age age1abc... secrets.yaml > secrets.enc.yaml
    ```

    **Вариант C — через переменную окружения (удобно для age):**
    ```bash
    export SOPS_AGE_KEY_FILE=$(pwd)/age.key
    sops --encrypt secrets.yaml > secrets.enc.yaml
    ```

    **Вариант D — Облачный KMS (AWS):**
    ```bash
    sops --encrypt --kms arn:aws:kms:region:account:key/id secrets.yaml > secrets.enc.yaml
    ```

### Расшифровка файла
Для расшифровки не требуется указывать ключи вручную — SOPS считывает метаданные из секции `sops`:

```bash
sops --decrypt secrets.enc.yaml > secrets.yaml
```

### Редактирование зашифрованного файла "на лету"
SOPS расшифровывает файл во временную директорию (обычно в `/dev/shm` или `tmpfs` для безопасности) и открывает его в `$EDITOR`. После сохранения файл автоматически зашифровывается обратно.

```bash
sops secrets.enc.yaml
```

### Запуск команд с секретами (`exec-env`)
Инструмент расшифровывает файл и передает его содержимое как переменные окружения дочернему процессу. Это предотвращает запись расшифрованных секретов на диск.

```bash
sops exec-env secrets.enc.yaml 'my-command --with-args'
```
- Если файл `.env` — переменные передаются напрямую.
- Для YAML/JSON SOPS преобразует вложенную структуру в плоские имена (например, `db_password`, `api_key`).

### Точечное редактирование значений (`--set`)
Позволяет изменить одно вложенное значение без открытия редактора. Удобно для скриптовой ротации секретов в CI/CD.

```bash
# Изменить значение db.password
sops --set '["db"]["password"] "new-secret-value"' secrets.enc.yaml

# Можно комбинировать с -e/-i для шифрования на месте
SOPS_AGE_RECIPIENTS=age1<id> sops -e -i --set '["api"]["key"] "new-key"' secrets.yaml
```
Синтаксис пути — JSON-подобный массив ключей. Значение указывается после пути в кавычках. Файл перешифровывается на месте.

### Использование в GitOps (2026)

-   **Flux CD:** Имеет нативную поддержку расшифровки через провайдеров (age, PGP, KMS). Настраивается в объекте `Kustomization` через поле `decryption`.
-   **Argo CD:** Требует использования плагинов, таких как **KSOPS** или **Argocd Vault Plugin**.
-   **Helm Secrets:** Плагин, позволяющий использовать зашифрованные `values.yaml` напрямую в Helm:
    ```bash
    helm secrets upgrade --install my-app ./chart -f secrets.enc.yaml
    ```

## 4. Продвинутые детали

### Файл конфигурации `.sops.yaml`
Позволяет автоматизировать выбор ключей на основе пути к файлу. Должен находиться в корне репозитория.

```yaml
# .sops.yaml
creation_rules:
  # Для prod-файлов — AWS KMS и резервный age-ключ
  - path_regex: prod/.*\.yaml$
    kms: "arn:aws:kms:eu-central-1:123456789012:key/..."
    age: "age1dev_admin_key..."

  # Для dev-файлов — только age
  - path_regex: dev/.*\.yaml$
    age: "age1team_dev_key..."

  # Для всех остальных .env файлов — PGP
  - path_regex: \.env$
    pgp: "YOUR_PGP_FINGERPRINT"
```

### Ротация и обновление ключей
Команда `sops updatekeys` позволяет перешифровать DEK файла с использованием актуальных мастер-ключей, указанных в `.sops.yaml`. Это критично при отзыве доступа или смене инфраструктуры.

```bash
sops updatekeys secrets.enc.yaml
```

### Проверка целостности (MAC)
SOPS вычисляет HMAC (Hash-based Message Authentication Code) для обнаружения несанкционированных изменений зашифрованного файла вне SOPS. Если файл был поврежден или изменен вручную, расшифровка завершится ошибкой.

Проверка без полной расшифровки:
```bash
sops --decrypt --mac-only secrets.enc.yaml
```

### Конвертация форматов
SOPS позволяет на лету менять формат представления данных:

```bash
# Зашифровать YAML и сохранить как JSON
sops --encrypt --input-type yaml --output-type json secrets.yaml > secrets.json

# Расшифровать JSON и вывести как YAML
sops --decrypt --input-type json --output-type yaml secrets.json

# Преобразование зашифрованного YAML в формат .env (без шифрования результата)
sops --decrypt --input-type yaml --output-type dotenv secrets.enc.yaml > secrets.env
```

### Мульти-рецепторное шифрование (Multi-recipient)
SOPS поддерживает шифрование для нескольких получателей одновременно. Это позволяет команде использовать разные ключи (например, личные `age`-ключи участников) для доступа к одному и тому же файлу без передачи общих секретов.

### См. также
- [GitOps: управление секретами](../../GitOps/secrets_encryption.md)
- [Управление секретами в Kubernetes](../../Kubernetes/Security/application_secrets_management.md)
- [HashiCorp Vault: обзор](../../Vault/overview.md)
- [Обзор управления секретами](../Concepts/secrets_management_overview.md)
- [GPG и age: сравнение бэкендов](../../Linux/Security/Tools/gpg_and_openpgp.md)
