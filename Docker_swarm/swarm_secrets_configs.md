# Docker Swarm: Secrets and Configs

## Определения

**Секреты (Secrets)** — встроенный механизм Docker Swarm для безопасного хранения чувствительных данных (пароли, токены, SSH-ключи). Секреты хранятся в зашифрованной Raft-базе данных кластера и монтируются в контейнеры как файлы в оперативной памяти (`tmpfs`).

**Конфигурации (Configs)** — аналогичный секретам механизм для управления нечувствительными данными (конфигурационные файлы, настройки приложений).

## Базовые концепции

### Хранение и доступ

| Характеристика | Secrets | Configs |
|---|---|---|
| **Шифрование** | AES-256 (в Raft) | Нет |
| **Путь в контейнере** | `/run/secrets/<name>` | `/<name>` |
| **Хранение** | tmpfs (RAM) | tmpfs (RAM) |
| **Изменяемость** | Неизменяемы | Неизменяемы |

### Принцип работы

1. **Создание:** Объект создается через CLI или docker-compose
2. **Назначение:** Секрет/конфигурация назначается сервису
3. **Монтирование:** При запуске контейнера объект монтируется в tmpfs
4. **Использование:** Приложение читает файл как обычный файл в ФС

### Неизменяемость (Immutability)

После создания ни секрет, ни конфигурацию нельзя отредактировать. Для обновления:

1. Создать новый объект с обновленными данными
2. Обновить сервис для использования новой версии
3. Удалить старую версию

```sh
# Обновление секрета
docker secret create db_password_v2 ./new_password.txt
docker service update --secret-rm db_password --secret-add db_password_v2 my-service
```

## Практические сценарии

### Базовое управление (CLI)

#### Создание секретов

```sh
# Из файла
docker secret create db_password ./password.txt

# Из stdin
echo "my_secret_password" | docker secret create api_token -

# С указанием имени файла
docker secret create --label env=prod db_config ./config.json
```

#### Создание конфигураций

```sh
# Из файла
docker config create app_config ./app.yaml

# С метаданными
docker config create --label version=1.0 nginx_conf ./nginx.conf
```

#### Просмотр и управление

```sh
# Список секретов/конфигураций
docker secret ls
docker config ls

# Детальная информация
docker secret inspect db_password
docker config inspect app_config

# Удаление
docker secret rm db_password
docker config rm app_config
```

### Использование в сервисах

#### Базовое подключение

```sh
# Секрет
docker service create --name my-app \
  --secret db_password \
  my-image

# Конфигурация
docker service create --name my-app \
  --config app_config \
  my-image
```

#### Подключение с указанием пути

```sh
# Секрет в кастомном пути
docker service create --name my-app \
  --secret source=db_password,target=/etc/app/db_pass \
  my-image

# Конфигурация в кастомном пути
docker service create --name my-app \
  --config source=app_config,target=/etc/app/config.yaml \
  my-image
```

#### Использование в docker-compose

```yaml
version: '3.8'

services:
  app:
    image: my-app:latest
    secrets:
      - db_password
      - api_token
    configs:
      - app_config
    deploy:
      replicas: 3

  db:
    image: postgres:15
    secrets:
      - db_password
    environment:
      POSTGRES_PASSWORD_FILE: /run/secrets/db_password

secrets:
  db_password:
    external: true
  api_token:
    external: true

configs:
  app_config:
    external: true
```

**Развертывание:**

```sh
# Создать секреты и конфигурации
docker secret create db_password ./password.txt
docker secret create api_token ./token.txt
docker config create app_config ./app.yaml

# Развернуть стек
docker stack deploy -c docker-compose.yml myapp
```

### Продвинутое использование

#### Чтение секрета в приложении (Python)

```python
def read_secret(secret_name):
    try:
        with open(f'/run/secrets/{secret_name}', 'r') as f:
            return f.read().strip()
    except FileNotFoundError:
        raise Exception(f"Secret {secret_name} not found")

db_password = read_secret('db_password')
```

#### Чтение секрета в приложении (Node.js)

```javascript
const fs = require('fs');

function readSecret(secretName) {
    return fs.readFileSync(`/run/secrets/${secretName}`, 'utf8').trim();
}

const dbPassword = readSecret('db_password');
```

#### Конвертация секрета в переменную окружения

Если приложение требует переменную окружения вместо файла:

```yaml
version: '3.8'

services:
  app:
    image: my-app:latest
    secrets:
      - db_password
    entrypoint: ["/bin/sh", "-c"]
    command:
      - |
        export DB_PASSWORD=$(cat /run/secrets/db_password)
        exec /app/start.sh

secrets:
  db_password:
    external: true
```

### Troubleshooting

#### Секрет не доступен в контейнере

**Проверка:**

```sh
# Убедиться, что секрет назначен сервису
docker service inspect --format='{{range .Spec.TaskTemplate.ContainerSpec.Secrets}}{{.SecretName}}{{end}}' my-service

# Проверить внутри контейнера
docker exec <container> ls -la /run/secrets/
```

**Возможные причины:**

- Секрет не назначен сервису
- Неправильный путь (`/run/secrets/` по умолчанию)
- Контейнер запущен с `--privileged` (может изменить поведение tmpfs)

#### Ошибка "secret not found"

**Проверка:**

```sh
# Проверить существование секрета
docker secret ls

# Проверить, что секрет создан до сервиса
docker secret inspect db_password
```

**Решение:** Секреты должны быть созданы до развертывания сервиса.

#### Конфликт имен секретов

Если несколько сервисов используют секреты с одинаковыми именами:

```sh
# Использовать алиасы
docker service create --name my-app \
  --secret source=db_password_v1,target=db_password \
  --secret source=db_password_v2,target=db_password_new \
  my-image
```

### Безопасность

#### Лучшие практики

- **Минимальные привилегии:** Назначайте секреты только тем сервисам, которым они необходимы
- **Ротация:** Регулярно обновляйте секреты (раз в 30–90 дней)
- **Аудит:** Ведите журнал создания и использования секретов
- **Шифрование:** Для особо чувствительных данных используйте внешние хранилища (Vault)

#### Ограничения

- Секреты видны в виде plain text внутри контейнера
- Любой с доступом к контейнеру может прочитать секреты
- Секреты не шифруются при передаче внутри кластера (только в Raft)

Для повышенных требований к безопасности используйте **[HashiCorp Vault](../Vault/overview.md)** с динамической генерацией секретов.

## Дополнительная информация

### Сравнение с альтернативами

| Метод | Безопасность | Сложность | Кластер |
|---|---|---|---|
| **Swarm Secrets** | Высокая | Низкая | ✓ |
| **Compose Secrets** | Средняя | Низкая | ✗ |
| **ENV variables** | Низкая | Низкая | ✓ |
| **Vault** | Максимальная | Высокая | ✓ |

Подробное сравнение — в **[Управление секретами в Docker](../Docker/Docker_security/secrets_management.md)**.

### Интеграция с Vault

Для enterprise-сценариев рассмотрите интеграцию с HashiCorp Vault:

- Динамическая генерация секретов
- Политики доступа и аудит
- Автоматическая ротация

Руководство по интеграции — в **[Vault и Docker](../Vault/guides/vault_docker_integration.md)**.

### Связанные документы

- **Общее управление секретами** — **[../Docker/Docker_security/secrets_management.md](../Docker/Docker_security/secrets_management.md)**
- **CLI Reference** — **[swarm_management_cli.md](./swarm_management_cli.md)**
- **Vault интеграция** — **[../Vault/guides/vault_docker_integration.md](../Vault/guides/vault_docker_integration.md)**
