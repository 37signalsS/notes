# Docker Swarm: Секреты и конфигурации

## Определения

**Секреты (Secrets)** — встроенный механизм Docker Swarm для безопасного хранения чувствительных данных (пароли, токены, ключи **SSH (Secure Shell)**). Секреты шифруются при хранении в базе данных алгоритма консенсуса **Raft** и монтируются в контейнеры как файлы во временную файловую систему в оперативной памяти (**tmpfs — temporary file system**).

**Конфигурации (Configs)** — механизм, аналогичный секретам, предназначенный для управления нечувствительными данными (файлы настроек, параметры приложений). В отличие от секретов, конфигурации не шифруются при хранении.

## Базовые концепции

### Хранение и доступ

| Характеристика | Секреты (Secrets) | Конфигурации (Configs) |
| :--- | :--- | :--- |
| **Raft-лог** | Зашифровано (AES-256) | Не шифровано |
| **Путь в контейнере** | `/run/secrets/<имя>` | `/<имя>` (или `target:`) |
| **Тип хранилища** | tmpfs | tmpfs |
| **Изменяемость** | Неизменяемы | Неизменяемы |
| **Назначение** | Пароли, токены, ключи SSH, сертификаты (приватные) | nginx.conf, ca.crt (публичные), YAML/JSON-конфиги |

### Принцип работы

1. **Создание:** Объект создается через **CLI (Command Line Interface)** или файл стека.
2. **Назначение:** Секрет или конфигурация привязывается к конкретному сервису.
3. **Монтирование:** При запуске задачи Swarm передает объект узлу и монтирует его в память контейнера.
4. **Использование:** Приложение читает данные как обычный файл из файловой системы.

### Неизменяемость (Immutability)

После создания объект нельзя отредактировать. Для обновления данных необходимо:

1. Создать новую версию объекта с другим именем.
2. Обновить сервис, заменив старую версию на новую.
3. Удалить неиспользуемую старую версию.

Пример обновления через **CLI**:

```bash
# Создание новой версии секрета
docker secret create db_password_v2 ./new_password.txt

# Обновление сервиса
docker service update --secret-rm db_password --secret-add db_password_v2 my-service
```

## Практические сценарии

### Базовое управление (CLI)

#### Создание секретов и конфигураций

```bash
# Создание секрета из файла
docker secret create db_password ./password.txt

# Создание секрета из стандартного ввода (stdin)
echo "my_secret_token" | docker secret create api_token -

# Создание конфигурации
docker config create app_config ./app.yaml
```

#### Просмотр и удаление

```bash
# Список объектов
docker secret ls
docker config ls

# Детальная информация (включая метаданные)
docker secret inspect db_password

# Удаление (объект не должен использоваться сервисами)
docker secret rm db_password
```

### Использование в сервисах

#### Запуск сервиса с секретами через CLI

```bash
# Секрет по пути по умолчанию (/run/secrets/db_password)
docker service create --name my-app --secret db_password my-image

# Секрет по кастомному пути внутри контейнера
docker service create --name my-app \
  --secret source=db_password,target=/etc/app/db_pass \
  my-image
```

#### Использование в файлах стека (docker-compose.yml)

```yaml
version: '3.8'

services:
  app:
    image: my-app:latest
    secrets:
      - db_password
    configs:
      - source: app_config
        target: /etc/myapp/config.yaml

  db:
    image: postgres:16-alpine
    secrets:
      - db_password
    environment:
      # PostgreSQL поддерживает чтение пароля из файла через переменные _FILE
      POSTGRES_PASSWORD_FILE: /run/secrets/db_password

secrets:
  db_password:
    external: true  # Секрет должен быть создан заранее

configs:
  app_config:
    external: true  # Конфиг создан заранее через docker config create
```

#### Замена host- bind mount на Config для портируемости

Bind-монтирование файла с хоста (`volumes:`) привязывает сервис к конкретной ноде — файла на других нодах нет.

```yaml
# docker-compose.yml — сервис привязан к ноде, где лежит bookstack.conf
nginx:
  image: nginx:alpine
  volumes:
    - /opt/bookstack/nginx/conf.d:/etc/nginx/conf.d:ro
  deploy:
    placement:
      constraints:
        - node.labels.name == machine1
```

Docker Config — «файл внутри Swarm». Конфиг загружается один раз, Swarm хранит его в зашифрованном Raft-логе и доставляет на любую ноду при запуске задачи.

**Ansible (рекомендуемый способ):** модуль `community.docker.docker_config` с `data:` из lookup-плагина — файл на целевой ноде не нужен:

```yaml
# Шаблон (Jinja2) — файл на control node
- name: Создание Docker Config из шаблона
  community.docker.docker_config:
    name: nginx_bookstack_config
    data: "{{ lookup('template', 'bookstack-nginx-swarm.conf.j2') }}"
    state: present
    force: yes

# Статический файл — тоже на control node
- name: Создание Docker Config для CA-сертификата
  community.docker.docker_config:
    name: nginx_ca_crt
    data: "{{ lookup('file', '/etc/nginx/ca.crt') }}"
    state: present
```

`lookup('file', ...)` читает файл с **control node** (где запускается Ansible). `lookup('template', ...)` рендерит Jinja2-шаблон.

**Важно про Vagrant:** `provision "ansible"` (не `ansible_local`) запускает Ansible на хосте, подключаясь к VM по SSH. `lookup('file')` ищет файл на хосте — если файл сгенерирован внутри VM, его там нет → ошибка. `ansible.builtin.shell` выполняет команду внутри VM через SSH, где файл существует → работает.

**CLI (вручную) или shell-модуль:** требуется файл на целевой ноде:

```bash
docker config create nginx-bookstack /opt/bookstack/nginx/conf.d/bookstack.conf
```

```yaml
# shell — для файлов, которые уже есть на целевой ноде
- name: Создание Docker Config для dhparam
  ansible.builtin.shell:
    cmd: docker config create nginx_dhparam /etc/nginx/dhparam.pem 2>/dev/null || true
```

**Compose (ссылка на существующий Config):**

```yaml
# docker-compose.yml — сервис работает на любой ноде
configs:
  nginx-bookstack:
    external: true            # конфиг уже создан (Ansible или CLI)

services:
  nginx:
    image: nginx:alpine
    configs:
      - source: nginx-bookstack
        target: /etc/nginx/conf.d/bookstack.conf
```

**Важно:** В режиме Swarm для `configs` и `secrets` не работает `file:` в compose-файле — только `external: true`. `file:` поддерживается только вне Swarm (`docker compose` без стека) как syntactic sugar.

**Ansible для Secrets (TLS-сертификаты):** приватные ключи — чувствительные данные. `community.docker.docker_secret` с `data:` принимает значение в открытом виде — оно попадёт в лог Ansible. Безопаснее `ansible.builtin.shell` с `no_log: true` — команда ссылается на файл, не раскрывая содержимое:

```yaml
- name: Создание Docker secret для приватного ключа
  ansible.builtin.shell:
    cmd: >
      docker secret create nginx_privkey
      /etc/letsencrypt/live/{{ nginx_domain }}/privkey.pem
      2>/dev/null || true
  no_log: true

- name: Создание Docker secret для полной цепочки
  ansible.builtin.shell:
    cmd: >
      docker secret create nginx_fullchain
      /etc/letsencrypt/live/{{ nginx_domain }}/fullchain.pem
      2>/dev/null || true
  no_log: true
```

Compose для Secrets работает аналогично Configs — `external: true`:

```yaml
secrets:
  nginx_privkey:
    external: true
  nginx_fullchain:
    external: true

services:
  nginx:
    secrets:
      - source: nginx_privkey
        target: /run/secrets/privkey.pem
      - source: nginx_fullchain
        target: /run/secrets/fullchain.pem
```

После перехода на Configs/Secrets ограничение `placement.constraints` можно убрать — nginx запустится на любой ноде кластера.

### Устранение неполадок (Troubleshooting)

#### Секрет не виден в контейнере

**Проверка:**

1. Убедитесь, что секрет назначен сервису:
   `docker service inspect --format='{{json .Spec.TaskTemplate.ContainerSpec.Secrets}}' <имя_сервиса>`
2. Проверьте содержимое директории в контейнере:
   `docker exec <ID_контейнера> ls -la /run/secrets/`

**Возможные причины:**

- Секрет не был добавлен в секцию `secrets` при создании сервиса.
- Контейнер запущен в режиме `--privileged` (может конфликтовать с монтированием **tmpfs** в некоторых версиях).
- Путь переопределен параметром `target`.

#### Ошибка "secret not found" при деплое стека

**Решение:** Если используется `external: true`, секрет должен существовать в кластере до выполнения команды `docker stack deploy`. Проверьте наличие объекта через `docker secret ls`.

## Дополнительная информация

### Рекомендации по безопасности

- **Минимальные привилегии:** Предоставляйте доступ к секретам только тем сервисам, которым они необходимы.
- **Ротация:** Регулярно обновляйте пароли и токены (минимум раз в 90 дней).
- **Внешние хранилища:** Для сложных сценариев (динамические секреты, аудит доступа) используйте специализированные системы.

### Сравнение с альтернативами

| Метод | Безопасность | Портабельность | Область применения |
| :--- | :--- | :--- | :--- |
| **Swarm Configs** | Средняя (Raft, без шифрования) | Любая нода Swarm | Конфиги nginx, приложений, публичные сертификаты (ca.crt, dhparam) |
| **Swarm Secrets** | Высокая (Шифрование + RAM) | Любая нода Swarm | Пароли, токены, приватные ключи TLS (privkey.pem)
| **Bind mount (volume)** | Низкая (файл на хосте) | Только одна нода | Legacy, однонодовые сценарии |
| **Переменные (ENV)** | Низкая (Видны в inspect/logs) | Любая нода | Разработка, нечувствительные данные |
| **HashiCorp Vault** | Максимальная | Любая нода | Крупные инфраструктуры |

### Смотрите также

- **[Управление секретами в Docker (SSoT)](../Docker/Docker_security/secrets_management.md)**
- **[Интеграция Vault с Docker](../Vault/guides/vault_docker_integration.md)**
- **[Ansible Vault: шаблоны и plaintext (сценарий 5)](../Ansible/Vault/best_practices.md)** — создание Docker Secrets из Vault минуя запись на диск
- **[Справочник CLI для Docker Swarm](./swarm_management_cli.md)**
