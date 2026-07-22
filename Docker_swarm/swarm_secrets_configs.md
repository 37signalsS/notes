# Docker Swarm: Секреты и конфигурации

## Определения

**Секреты (Secrets)** — встроенный механизм Docker Swarm для безопасного хранения чувствительных данных (пароли, токены, ключи **SSH (Secure Shell)**). Секреты шифруются при хранении в базе данных алгоритма консенсуса **Raft** (AES-256) и монтируются в контейнеры как файлы во временную файловую систему в оперативной памяти (**tmpfs**).

**Конфигурации (Configs)** — механизм, аналогичный секретам, предназначенный для управления нечувствительными данными (файлы настроек, параметры приложений). В отличие от секретов, конфигурации не шифруются при хранении в Raft-логе.

## Базовые концепции

### Хранение и доступ

| Характеристика | Секреты (Secrets) | Конфигурации (Configs) |
| :--- | :--- | :--- |
| **Raft-лог** | Зашифровано (AES-256) | Не шифровано |
| **Путь в контейнере** | По умолчанию `/run/secrets/<имя>` | Любой путь (через `target`) |
| **Тип хранилища** | tmpfs (в оперативной памяти) | tmpfs (в оперативной памяти) |
| **Изменяемость** | Неизменяемы (требуют пересоздания) | Неизменяемы (требуют пересоздания) |
| **Лимит размера** | 500 КБ на один объект | 500 КБ на один объект |

### Принцип работы

1. **Создание:** Объект создается через **CLI (Command Line Interface)** или API менеджера. При создании можно добавить метки (labels) для классификации.
2. **Назначение:** Секрет или конфигурация привязывается к сервису. Только авторизованные узлы (те, где запущены задачи сервиса) получают доступ к данным.
3. **Монтирование:** Swarm доставляет данные на узел в зашифрованном виде (для секретов), расшифровывает их в памяти и монтирует в контейнер.
4. **Изоляция:** Секреты Swarm доступны только внутри Swarm-сервисов. Автономные контейнеры на том же узле не имеют доступа к этим данным в `/run/secrets/`.

### Неизменяемость и версионность

Поскольку объекты неизменяемы, стандартным паттерном является добавление версии или хеша к имени (например, `app_config_v1`). Для обновления данных необходимо:

1. Создать новую версию объекта.
2. Обновить сервис, указав новый источник.
3. Дождаться успешного завершения **Rolling Update**.
4. Удалить старую версию объекта.

Пример обновления через **CLI**:

```bash
# Создание новой версии секрета с меткой
docker secret create --label version=2.0 db_password_v2 ./new_password.txt

# Обновление сервиса (атомарная замена)
docker service update --secret-rm db_password_v1 --secret-add db_password_v2 my-service
```

## Практические сценарии

### Базовое управление (CLI)

#### Создание секретов и конфигураций

```bash
# Создание секрета из файла
docker secret create db_password ./password.txt

# Создание из стандартного ввода (stdin) — содержимое не сохраняется в истории shell
echo "my_secret_token" | docker secret create api_token -

# Создание конфигурации с метаданными
docker config create --label env=prod --label app=nginx nginx_conf ./nginx.conf
```

#### Просмотр и диагностика

```bash
# Список объектов с фильтрацией по меткам
docker secret ls --filter label=app=nginx

# Просмотр метаданных (содержимое секрета НЕ отображается)
docker secret inspect db_password

# Удаление (объект не должен использоваться ни одним активным сервисом)
docker secret rm db_password
```

### Использование в сервисах

#### Управление правами доступа при монтировании

В Swarm можно точно настроить права доступа, владельца и группу для монтируемого файла:

```bash
docker service create --name web \
  --secret source=ssl_cert,target=/etc/nginx/certs/server.crt,uid=101,gid=101,mode=0400 \
  nginx:alpine
```

#### Использование в файлах стека (docker-compose.yml)

Пример использования расширенного синтаксиса для управления путями и правами:

```yaml
version: '3.8'

services:
  app:
    image: my-app:latest
    secrets:
      - source: db_password
        target: db_password_file
        uid: '1000'
        gid: '1000'
        mode: 0400
    configs:
      - source: app_config
        target: /etc/myapp/config.yaml
        mode: 0444

  db:
    image: postgres:16-alpine
    secrets:
      - db_password
    environment:
      # Использование паттерна _FILE для безопасности
      POSTGRES_PASSWORD_FILE: /run/secrets/db_password

secrets:
  db_password:
    external: true

configs:
  app_config:
    external: true
```

#### Замена host-bind mount на Docker Config

Bind-монтирование (`volumes:`) ограничивает мобильность сервиса, привязывая его к конкретному узлу. Docker Config позволяет сделать сервис портируемым.

**Автоматизация через Ansible:**

Использование модуля `community.docker.docker_config` позволяет загружать данные напрямую с управляющей машины (control node), не сохраняя их на целевых узлах:

```yaml
- name: Создание Docker Config из шаблона
  community.docker.docker_config:
    name: nginx_bookstack_config
    data: "{{ lookup('template', 'bookstack-nginx-swarm.conf.j2') }}"
    state: present
    force: yes

- name: Создание Docker secret для приватного ключа (безопасный метод)
  ansible.builtin.shell:
    cmd: >
      docker secret create nginx_privkey
      /etc/letsencrypt/live/{{ nginx_domain }}/privkey.pem
      2>/dev/null || true
  no_log: true  # Скрывает вывод в логах Ansible
```

## Устранение неполадок

### Секрет не виден в контейнере

1. **Проверка назначения:**
   `docker service inspect --format='{{json .Spec.TaskTemplate.ContainerSpec.Secrets}}' <имя_сервиса>`
2. **Проверка файловой системы:**
   Внутри контейнера выполните `ls -la /run/secrets/`. Помните, что это **tmpfs**, данные не сохраняются на диске.
3. **Пути монтирования:**
   Если указан `target`, файл будет находиться по этому пути, а не в `/run/secrets/`.

### Ошибка "secret not found" при деплое стека

Если в YAML указано `external: true`, Swarm требует наличия объекта в кластере **до** запуска `docker stack deploy`. В Swarm Mode инструкция `file:` в секции `secrets/configs` игнорируется (она работает только в автономном Docker Compose).

## Дополнительная информация

### Сравнение методов передачи данных

| Метод | Безопасность | Портируемость | Применение |
| :--- | :--- | :--- | :--- |
| **Swarm Secrets** | Высокая (Raft + RAM) | Полная | Пароли, ключи TLS, токены |
| **Swarm Configs** | Средняя (Raft) | Полная | nginx.conf, параметры окружения |
| **Volumes (bind)** | Низкая (диск хоста) | Нет (привязка к ноде) | Большие файлы, legacy-решения |
| **Env (переменные)** | Низкая (видны везде) | Полная | Нечувствительные флаги запуска |

### Смотрите также

- **[Управление секретами в Docker](../../Docker/Docker_security/secrets_management.md)** — общие принципы и методы (Compose, BuildKit).
- **[Интеграция Vault с Docker](../../Vault/guides/vault_docker_integration.md)** — использование HashiCorp Vault как центрального источника.
- **[Ansible Vault и Docker Secrets](../../Ansible/Vault/best_practices.md)** — создание секретов из Vault без записи на диск.
