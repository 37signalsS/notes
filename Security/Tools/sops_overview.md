# SOPS (Secrets OPerationS)

## 1. Определения

**SOPS (Secrets OPerationS)** — это инструмент с открытым исходным кодом от Mozilla для управления секретами. Он представляет собой редактор зашифрованных файлов, который позволяет безопасно хранить структурированные данные (YAML, JSON, .env, INI) в системах контроля версий, таких как Git.

## 2. Основные концепции

Ключевая особенность SOPS — **шифрование только значений (values)** в файле, в то время как ключи (keys) остаются в открытом виде. Это позволяет сохранять структуру и читаемость файла, а также видеть изменения в `git diff`, не раскрывая при этом сами секреты.

SOPS использует конвертную модель шифрования:

1. Для каждого файла генерируется уникальный ключ шифрования данных (DEK).
2. Этот DEK шифруется одним или несколькими **мастер-ключами**.
3. Зашифрованный DEK хранится в метаданных файла SOPS.

В качестве мастер-ключей могут выступать:

- Облачные KMS (AWS, GCP, Azure)
- PGP / GPG ключи
- [age](https://github.com/FiloSottile/age) ключи
- HashiCorp Vault

## 3. Практические сценарии

### Установка

```bash
wget https://github.com/getsops/sops/releases/latest/download/sops-linux-amd64
chmod +x sops-linux-amd64
sudo mv sops-linux-amd64 /usr/local/bin/sops
```

### Шифрование файла

1. **Создать файл с секретами:**

    ```yaml
    # secrets.yaml
    db_password: "SuperSecretPassword123"
    api_key: "abc-123"
    ```

2. **Выбрать мастер-ключ и зашифровать:**

    **Вариант A — PGP:**
    ```bash
    sops --encrypt --pgp YOUR_PGP_FINGERPRINT secrets.yaml > secrets.enc.yaml
    ```

    **Вариант B — age (рекомендуется):**
    ```bash
    # Сгенерировать ключ
    age-keygen -o age.key
    # Зашифровать публичным ключом
    sops --encrypt --age age1abc... secrets.yaml > secrets.enc.yaml
    ```

    **Вариант C — через переменную окружения:**
    ```bash
    export SOPS_AGE_KEY_FILE=age.key
    sops --encrypt secrets.yaml > secrets.enc.yaml
    ```

    Зашифрованный файл `secrets.enc.yaml` можно безопасно коммитить в Git.

### Расшифровка файла

Для расшифровки не требуется указывать ключ — SOPS читает метаданные из зашифрованного файла:

```bash
sops --decrypt secrets.enc.yaml > secrets.yaml
```

Метаданные (ключ шифрования, использованный мастер-ключ) хранятся в секции `sops` внутри зашифрованного файла.

### Редактирование зашифрованного файла

SOPS позволяет редактировать зашифрованный файл "на лету". Он откроет его в вашем `$EDITOR` в расшифрованном виде, а после сохранения автоматически зашифрует обратно.

```bash
sops secrets.enc.yaml
```

### Запуск команды с секретами из окружения

`sops exec-env` расшифровывает файл и передаёт его содержимое как переменные окружения дочернему процессу, не создавая временных файлов на диске:

```bash
sops exec-env secrets.enc.yaml 'my-command --with-args'
```

Если файл в формате `.env` — переменные передаются напрямую. Для YAML/JSON SOPS преобразует структуру в плоские имена переменных (например, `db_password`, `api_key`).

### Использование в GitOps

SOPS широко используется в связке с ArgoCD и Flux. В CI/CD пайплайне или в контроллере GitOps (при наличии доступа к мастер-ключу) зашифрованные файлы расшифровываются перед применением в кластер Kubernetes.

## 4. Продвинутые детали

### Файл конфигурации `.sops.yaml`

Для упрощения работы можно создать файл `.sops.yaml` в корне репозитория. В нем указываются правила создания и шифрования для разных файлов, включая используемые мастер-ключи. Это избавляет от необходимости каждый раз указывать ключи в командной строке.

```yaml
# .sops.yaml
creation_rules:
  # Для prod-файлов — age ключ
  - path_regex: prod/.*\.yaml$
    age: age1abc...

  # Для dev-файлов — другой ключ
  - path_regex: dev/.*\.yaml$
    age: age1def...

  # Для всех остальных .env файлов — PGP
  - path_regex: \.env$
    pgp: YOUR_PGP_FINGERPRINT
```

После настройки `.sops.yaml` команды упрощаются до:

```bash
sops --encrypt prod/secrets.yaml > prod/secrets.enc.yaml
sops --decrypt prod/secrets.enc.yaml
```

### Ротация ключей

SOPS поддерживает ротацию мастер-ключей. С помощью команды `sops updatekeys` можно перешифровать ключ данных (DEK) новым набором мастер-ключей, что позволяет легко добавлять или отзывать доступы.

### Проверка целостности (MAC)

SOPS добавляет в метаданные HMAC (keyed-hash message authentication code) для обнаружения несанкционированных изменений зашифрованного файла. Если файл был изменён после шифрования, `sops --decrypt` завершится с ошибкой.

Проверить целостность без расшифровки:

```bash
sops --decrypt --mac-only secrets.enc.yaml
```

### Конвертация форматов

SOPS поддерживает чтение и запись разных форматов, что позволяет конвертировать файлы между YAML, JSON и .env:

```bash
# Зашифровать YAML → выдать как JSON
sops --encrypt --input-type yaml --output-type json secrets.yaml > secrets.json

# Расшифровать JSON → сохранить как YAML
sops --decrypt --input-type json --output-type yaml secrets.json > secrets.yaml

# Преобразование без шифрования (только конвертация)
sops --decrypt --input-type yaml --output-type dotenv secrets.enc.yaml > secrets.env
```
