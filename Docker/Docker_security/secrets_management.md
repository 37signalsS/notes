# Управление секретами в Docker

**Актуально для:** Docker Engine 29.x. Docker Compose v2.24+. BuildKit (включён по умолчанию с Docker 23.0+).

Данный документ описывает методы безопасного хранения и передачи конфиденциальных данных (паролей, токенов, ключей API) в экосистеме Docker на отдельных хостах и небольших стеках (standalone и Docker Compose).

> **Статус:** Docker Swarm имеет собственный SSoT-документ — **[Секреты и конфигурации в Swarm](../../Docker_swarm/swarm_secrets_configs.md)**. Здесь описываются только методы standalone и Docker Compose.

## Предварительные требования

- **Docker Engine 29.x** с включённым BuildKit (`DOCKER_BUILDKIT=1` по умолчанию с версии 23.0)
- **Docker Compose v2.24+** (встроен в Docker CLI как `docker compose`)
- **ОС:** Linux (для нативной поддержки `tmpfs` и `bind-mount` секретов). Windows-контейнеры поддерживаются ограниченно — секреты доставляются как bind-mount без `tmpfs`
- **Локальные инструменты (опционально):** `age` или `gpg` для шифрования файлов секретов перед хранением вне репозитория; `sops` для шифрования YAML/ENV-файлов в Git
- **Файлы секретов** — хранятся за пределами репозитория (добавлены в `.gitignore`), доступ к ним ограничен на уровне ОС (mode `0400` или `0600`)

## Определения

**Управление секретами (Secrets Management)** — совокупность практик по безопасному хранению, ограничению доступа, аудиту и ротации чувствительных данных.

**Секрет** — любая информация, компрометация которой может нанести ущерб системе (пароли БД, API-ключи, TLS-сертификаты, секретные ключи **JWT (JSON Web Token)**).

**Паттерн `_FILE`** — конвенция, при которой приложение принимает путь к файлу с секретом вместо самого значения (например, `DB_PASSWORD_FILE=/run/secrets/db_pass`), что позволяет избежать утечки секрета через переменные окружения.

**tmpfs** — временная файловая система, хранящаяся исключительно в оперативной памяти (RAM). Используется для монтирования секретов, гарантируя, что они никогда не будут записаны на диск хоста или контейнера.

**BuildKit** — современный движок сборки Docker (включён по умолчанию с Docker 23.0). Предоставляет `--mount=type=secret` для передачи секретов в контейнер сборки без их сохранения в слоях образа.

**Слоистая утечка (Layer Leak)** — утечка секрета, оставшегося в истории слоёв образа после удаления файла в последующем `RUN`. Удалённый файл скрывается whiteout, но физически остаётся в нижнем слое и доступен через `docker save`.

## Базовые концепции

Безопасность секретов в Docker базируется на минимизации их видимости в метаданных контейнера.

### 1. Переменные окружения (**ENV**) — Критический риск

Самый распространенный, но **наименее безопасный** метод.

- **Риски:** Секреты видны в выводе `docker inspect`, `docker history`, `/proc/1/environ`. Они попадают в логи при сбоях и доступны всем дочерним процессам. В 2026 году использование `ENV` для секретов в production-средах считается грубым нарушением безопасности.
- **Рекомендация:** Если приложение не поддерживает чтение из файлов, используйте специализированные "entrypoint-скрипты", которые получают секрет из файла и экспортируют его в окружение только для основного процесса.

### 2. Секреты Docker Compose

Механизм для одиночных хостов и небольших стеков. Секреты монтируются как файлы в `tmpfs` по пути `/run/secrets/`.

- **Особенности:** В Docker Compose секреты могут быть как внешними (`external: true`), так и загружаться из локальных файлов. При использовании `tmpfs` секрет существует только в памяти запущенного контейнера.
- **Ограничение:** В отличие от Swarm, в Compose `uid`, `gid` и `mode` могут не применяться — используется `bind-mount`, для которого Linux не меняет права между источником и назначением.

### 3. Секреты Docker Swarm (SSoT)

Встроенное решение для кластеров. Секреты шифруются при хранении (AES-256 в Raft) и передаются только тем узлам, на которых запущены соответствующие сервисы.
- **Подробнее см. в [Секреты и конфигурации в Swarm](../../Docker_swarm/swarm_secrets_configs.md)**.

### 4. Безопасность сборки (BuildKit Secrets)

Механизм для передачи учетных данных во время сборки образа без их сохранения в истории слоев.

- **`--mount=type=secret`**: Монтирует файл секрета в контейнер сборки по пути `/run/secrets/<id>`. Опции: `id`, `target`/`dst`/`destination`, `env`, `required`, `mode` (по умолчанию `0400`), `uid` (по умолчанию `0`), `gid` (по умолчанию `0`).
- **`--mount=type=ssh`**: Пробрасывает SSH-агент хоста, позволяя использовать SSH-ключи для доступа к приватным Git-репозиториям без их копирования в образ.

## Практические сценарии

### 1. Реализация паттерна `_FILE` в Docker Compose

Это наиболее сбалансированный метод для большинства приложений.

```yaml
services:
  db:
    image: mariadb:11.4
    secrets:
      - mysql_root_password
    environment:
      # MariaDB нативно поддерживает суффикс _FILE
      - MYSQL_ROOT_PASSWORD_FILE=/run/secrets/mysql_root_password

secrets:
  mysql_root_password:
    file: ./secrets/db_pass.txt # Файл должен быть добавлен в .gitignore
```

**Валидация:**
```bash
docker compose up -d
docker exec <container> env | grep MYSQL
# → MYSQL_ROOT_PASSWORD_FILE=/run/secrets/mysql_root_password

docker exec <container> ls -l /run/secrets/
# → -r-------- 1 root root ... mysql_root_password
```

### 2. Сборка с использованием секретов и SSH-агента

Исключает утечку токенов NPM или приватных ключей в Docker-образ.

```dockerfile
# syntax=docker/dockerfile:1
FROM node:22-alpine

# 1. Использование секрета для NPM токена
RUN --mount=type=secret,id=npm_token \
    NPM_TOKEN=$(cat /run/secrets/npm_token) npm install

# 2. Использование SSH для клонирования приватного репозитория
RUN --mount=type=ssh \
    ssh -q -o StrictHostKeyChecking=no git@github.com:org/repo.git
```

**Команда сборки:**
```bash
docker build --secret id=npm_token,src=$HOME/.npm_token --ssh default -t my-app .
```

**Современный вариант через `buildx` с `type=env`:**
```bash
docker buildx build --secret id=API_KEY,src=$HOME/.npm_token -t my-app .
```

### 3. Интеграция с внешними менеджерами (1Password / Vault)

Для сред с высокими требованиями к безопасности (Zero-Disk-Secret policy).

- **1Password CLI:** Динамическая инъекция без сохранения на диск.
  ```bash
  op run -- docker compose up -d
  ```
- **Vault Agent:** Запускается как sidecar-контейнер или отдельный сервис, который пишет секреты в общую `tmpfs` директорию, доступную приложению.
  - **Подробнее см. в [Интеграция Vault с Docker](../../Vault/guides/vault_docker_integration.md)**.

### 4. Шифрование секретов в Git (SOPS + age)

Если необходимо хранить секреты в репозитории (GitOps), используйте **SOPS**.

```bash
# Шифрование секрета для конкретного окружения
sops --encrypt --age $(cat keys.txt) secrets.yaml > secrets.enc.yaml

# В CI/CD: расшифровка напрямую в tmpfs перед запуском
sops -d secrets.enc.yaml > /dev/shm/secrets.yaml
docker compose up -d
```

### 5. Использование переменных окружения через `environment` в Compose secrets (v2.6.0+)

Начиная с Compose v2.6.0, источником секрета может быть переменная окружения:

```yaml
services:
  app:
    image: my-app:latest
    environment:
      API_TOKEN: ${API_TOKEN}  # не секрет, а переменная окружения
    secrets:
      - api_token

secrets:
  api_token:
    environment: API_TOKEN    # значение берётся из env-переменной API_TOKEN
```

**Важно:** `environment`-источник работает только на этапе развёртывания (`docker compose up`), а не сборки.

### 6. Долговременное хранилище секретов на хосте (systemd + tmpfs)

Для standalone-развёртываний вне Docker Compose, секреты можно хранить в `tmpfs`-файле, управляемом systemd:

```bash
# /etc/systemd/system/secrets-mount.service
[Unit]
Description=Mount secrets tmpfs
After=local-fs.target

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/bin/sh -c 'mkdir -p /run/secrets && mount -t tmpfs -o size=1M,mode=0700 tmpfs /run/secrets'
ExecStartPost=/bin/cp /etc/docker/secrets/master.key /run/secrets/master.key

[Install]
WantedBy=multi-user.target
```

```bash
systemctl enable --now secrets-mount.service
```

## Операции и команды

### Управление секретами BuildKit

| Операция | Команда | Описание |
| :--- | :--- | :--- |
| **Передача секрета из файла** | `docker build --secret id=mysecret,src=./secret.txt .` | Секрет доступен в `/run/secrets/mysecret` внутри `RUN` |
| **Передача через env-переменную** | `docker build --secret type=env,id=MYVAR,src=SECRET .` | BuildKit считывает значение из env `SECRET` и монтирует как `MYVAR` |
| **Обязательный секрет** | `RUN --mount=type=secret,id=mysecret,required=true ...` | Сборка завершается ошибкой, если секрет недоступен |
| **Проверка содержимого** | `RUN --mount=type=secret,id=mysecret cat /run/secrets/mysecret` | Вывести содержимое секрета во время сборки |
| **Скрытие в логах сборки** | `RUN --mount=type=secret,id=npm_token NPM_TOKEN=$(cat /run/secrets/npm_token) npm install` | Секрет не попадает в слой образа и не отображается в выводе |

### Управление секретами Docker Compose

| Операция | Команда | Описание |
| :--- | :--- | :--- |
| **Создание секрета из файла** | `docker secret create my_secret ./secret.txt` | (только для Swarm) создать секрет в базе |
| **Запуск с локальным секретом** | `docker compose up -d` | Секрет из `file:` монтируется в `/run/secrets/<name>` |
| **Проверка монтирования** | `docker compose exec app ls -l /run/secrets/` | Просмотр прав и владельца файлов секретов |
| **Вывод содержимого** | `docker compose exec app cat /run/secrets/api_token` | Просмотр значения секрета внутри контейнера |
| **Валидация отсутствия секретов в образе** | `docker save <image> \| tar -t - | grep secret \|\| echo "Секреты не найдены"` | Проверка слоёв образа на наличие секретов |

### Аудит и обнаружение секретов

| Цель | Команда | Описание |
| :--- | :--- | :--- |
| **Сканировка образа** | `docker scout cves --output json <image>` | Поиск уязвимостей и секретов в слоях образа |
| **Поиск в истории образа** | `docker history <image> --no-trunc \| grep -iE 'pass\|secret\|token\|key'` | Проверка слоёв на утечки |
| **Сканирование слоёв на уровне файлов** | `docker save <image> > /tmp/image.tar && tar -xf /tmp/image.tar && grep -rn "secret\|password\|token" .` | Глубокая проверка содержимого всех слоёв |
| **Аудит переменных окружения** | `docker inspect --format='{{json .Config.Env}}' <container> \| jq -r '.[]' \| grep -iE 'pass\|secret\|key\|token'` | Проверка переменных окружения контейнера |
| **Аудит mount-опций** | `docker inspect --format '{{json .HostConfig.Mount'` ... | Проверка, что секреты не bind-mounted с диска |

## Устранение неполадок

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Secret not found в контейнере** | Путь к файлу секрета неверный или файл `.gitignore` не исключил | Проверить `secrets: file:` path в compose; убедиться что файл существует на хосте |
| **`docker-compose` игнорирует `uid`/`gid`/`mode`** | Docker Compose использует `bind-mount`, для которого Linux не меняет права | Использовать `tmpfs: /run/secrets` для контроля прав; или Swarm mode для корректного применения |
| **`required=true` секрет недоступен** | Секрет не передан в `docker build --secret` | Добавить флаг `--secret id=<name>,src=<file>` в команду сборки |
| **Секрет виден в `docker inspect`** | Передан через `ENV`, а не через `--mount=type=secret` или `secrets:` | Использовать BuildKit `--mount=type=secret` или паттерн `_FILE` |
| **`sops: no key found`** | Отсутствует master key (age, PGP) в окружении | Установить `SOPS_AGE_KEY_FILE` или передать `--age` флаг; подробнее в `[sops_overview.md](../../Security/Tools/sops_overview.md)` |
| **Секрет не обновляется после изменения файла** | Секрет передан через `file:` и закеширован Docker Compose | `docker compose up -d --force-recreate` или использовать `external: true` с менеджером секретов |
| **Windows: secret не монтируется** | На Windows секреты доставляются как bind-mount без `tmpfs` | Указать `target` с forward-slashes: `--mount=type=secret,id=mysecret,target=C:/path/to/secret` |

## Лучшие практики

### Общие принципы

1. **Никогда не храните секреты в `ENV`/`ARG`** — они видны в `docker inspect` и остаются в слое образа. Используйте `--mount=type=secret` на этапе сборки и паттерн `_FILE` на этапе запуска.
2. **Используйте минимальные права доступа** — для файлов секретов на хосте: `0400` или `0600`. Для смонтированных секретов в контейнере: `mode: 0400` (BuildKit) или `0440` (Compose/Swarm long syntax).
3. **Не коммитьте файлы секретов в Git** — используйте `.gitignore`, а для GitOps — SOPS + age/PGP для шифрования.
4. **Ротация без простоя** — в Swarm используйте versioning (`_v2`) для Rolling Update. В Compose применяйте `--force-recreate`.

### На этапе сборки

5. **Используйте BuildKit `--mount=type=secret`** — никогда не используйте `COPY` или `ARG` для передачи секретов в образ.
6. **Аудитируйте образ после сборки** — сканируйте слои (`docker save | tar`) на наличие секретов перед пушем в реестр.

### На этапе runtime

7. **Используйте `tmpfs` для `/run/secrets`** — гарантирует, что секреты не попадают на диск: `--tmpfs /run/secrets:rw,noexec,nosuid`.
8. **Не используйте Docker Volumes для секретов** — данные томов записываются на диск в открытом виде (см. **[Шифрование томов](../Docker_fs/volume_encryption.md)** для защиённых вариантов).
9. **Ограничьте время жизни контейнера** — используйте `--rm` для standalone-контейнеров, чтобы секреты удалялись из памяти после завершения.

## Граничные случаи и ограничения

- **Размер секретов:** Swarm накладывает лимит 500 КБ на секреты и конфиги. BuildKit и Compose не имеют жёсткого лимита, но файлы секретов должны помещаться в оперативную память (tmpfs).
- **Rootless Docker:** При запуске в rootless-режиме секреты в tmpfs работают корректно, но `uid`/`gid` монтирования могут требовать настройки user namespaces. Подробнее: **[SSH-agent в rootless Docker](./ssh-agent-rootless.md)**.
- **Docker-in-Docker (DinD):** Секреты BuildKit пробрасываются через `--secret` на хосте, но внутри DinD-контейнера требуется проброс `--secret` на вложенный `docker build` — используйте `--security-opt label=disable` при пробросе Docker socket.
- **SELinux и AppArmor:** При включённом SELinux монтирование в `/run/secrets` может потребовать корректировки контекста: `chcon -Rt container_file_t /run/secrets`.
- **Kernel Lockdown:** При включённом `lockdown=1` (ядро 5.4+) `docker build --secret type=ssh` может потребовать дополнительных разрешений.

## Дополнительная информация

**Связанные документы:**
- **[Секреты и конфигурации в Swarm](../../Docker_swarm/swarm_secrets_configs.md)** — кластерный режим (SSoT для Docker Swarm secrets).
- **[Интеграция Vault с Docker](../../Vault/guides/vault_docker_integration.md)** — архитектурные паттерны (Vault Agent sidecar, BuildKit secrets в CI/CD).
- **[Антипаттерны управления секретами](../../Vault/common_antipatterns.md)** — типичные ошибки и их исправление.
- **[SSH-agent в rootless Docker](./ssh-agent-rootless.md)** — передача сокета ssh-agent в контейнер без передачи самого ключа.
- **[Безопасность в Dockerfile](../Dockerfile/Docker_best_practices/security.md)** — лучшие практики на этапе написания Dockerfile (включая `--mount=type=secret`).
- **[Безопасность томов Docker](../Docker_fs/volume_encryption.md)** — почему тома не подходят для секретов и как использовать encrypted volume.
- **[Управление слоями образов](../Docker_fs/images/layer_management.md)** — whiteout-файлы и слой-утечки секретов.
- **[Сканирование образов на уязвимости и секреты](../Dockerfile/Docker_best_practices/security.md)** — `docker scout` и ручная проверка слоёв.

**Внешние ресурсы:**
- **Docker Documentation:** [Build secrets](https://docs.docker.com/build/building/secrets/).
- **Docker Documentation:** [Docker Compose Secrets](https://docs.docker.com/compose/how-tos/use-secrets/).
- **CIS Docker Benchmark:** Рекомендация 5.1 (Использование Docker Secrets вместо переменных окружения).
- **Docker Documentation:** [docs.docker.com/engine/swarm/secrets/](https://docs.docker.com/engine/swarm/secrets/).
- **SOPS GitHub:** [github.com/getsops/sops](https://github.com/getsops/sops).

**Инструменты:** `BuildKit` (сборка), `SOPS` (шифрование в Git), `Vault Agent` (динамические секреты), `1Password CLI` (удобство разработки), `age`/`GPG` (локальное шифрование файлов), `gitleaks`/`trufflehog` (обнаружение утечек в Git).
