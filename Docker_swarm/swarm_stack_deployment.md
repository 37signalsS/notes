# Docker Swarm: Развертывание стеков (Stack Deployment)

## Определения

**Стек (Stack)** — группа взаимосвязанных сервисов, которые совместно образуют приложение в среде Docker Swarm. Стек описывается декларативно в YAML-файле и управляется как единая сущность через команду `docker stack deploy`.

**Docker Stack** — нативный инструмент оркестрации Docker для управления жизненным циклом многоконтейнерных приложений в кластере. Он транслирует инструкции из файла спецификации (обычно `docker-compose.yml`) в объекты Swarm: сервисы, сети, секреты и конфигурации.

## Базовые концепции

### Отличия от Docker Compose

Несмотря на использование идентичного формата файлов, механизмы работы инструментов принципиально различаются:

| Параметр | Docker Compose | Docker Stack |
|---|---|---|
| **Команда** | `docker compose up` | `docker stack deploy` |
| **Масштаб** | Одиночный хост | Весь Swarm-кластер |
| **Секция `deploy`** | Игнорировалась в v1, частично в v2 | Первостепенная значимость |
| **Имена контейнеров** | Задаются через `container_name` | Генерируются автоматически |
| **Порядок запуска** | Строгий через `depends_on` | Декларативный (через Healthchecks) |
| **Сборка образов** | Инструкция `build` | Не поддерживается (нужен Registry) |

**Важно:** Спецификация Compose v2 стремится к унификации, однако для промышленной эксплуатации в кластере `docker stack` остается предпочтительным из-за полной поддержки политик обновления и размещения.

### Параметры, игнорируемые в режиме Swarm

Оркестратор Swarm берет на себя управление жизненным циклом процессов, поэтому следующие инструкции из YAML-файла игнорируются:

- `container_name`: Swarm самостоятельно формирует имена вида `<stack>_<service>.<index>.<id>`.
- `restart`: Вместо этого используется `deploy.restart_policy`.
- `depends_on`: Swarm запускает сервисы параллельно. Зависимости должны обрабатываться на уровне приложения (например, через скрипты ожидания порта).
- `build`: Все образы должны быть предварительно собраны и загружены в Docker Registry.
- `links` и `network_mode`: Используются только оверлейные сети (`overlay`).

### Структура файла для Swarm

Типовая структура описания сервиса для кластерного режима:

```yaml
version: '3.8'

services:
  web:
    image: nginx:1.26.3
    deploy:
      replicas: 3
      resources:
        limits:
          cpus: '0.50'
          memory: 512M
      placement:
        constraints:
          - node.role == worker
      update_config:
        parallelism: 1
        delay: 10s
      restart_policy:
        condition: on-failure
    networks:
      - frontend

networks:
  frontend:
    driver: overlay
```

## Практические сценарии

### Базовое управление стеком

Команда `deploy` идемпотентна: она создает стек, если он не существует, или обновляет его конфигурацию до состояния, описанного в файле.

```bash
# Развертывание или обновление стека из файла
docker stack deploy -c docker-compose.yml myapp
# → Creating network myapp_default
# → Creating service myapp_web

# Развертывание с авторизацией в приватном Registry (обязательно для воркеров)
docker stack deploy --with-registry-auth -c docker-compose.yml myapp
# → Updating service myapp_web (id: ...)
```

#### Мониторинг состояния

```bash
# Список всех запущенных стеков
docker stack ls
# → NAME      SERVICES   ORCHESTRATOR
# → myapp     2          Swarm

# Просмотр задач (контейнеров) и причин их падения
docker stack ps myapp
# → ID            NAME          IMAGE          NODE      DESIRED STATE  CURRENT STATE
# → 123abc456def  myapp_web.1   nginx:1.26.3   node-2    Running        Running 2 hours ago

# Список сервисов в стеке с указанием реплик
docker stack services myapp
# → ID            NAME          MODE          REPLICAS  IMAGE          PORTS
# → xyz789012345  myapp_web     replicated    3/3       nginx:1.26.3   *:80->80/tcp
```

### Стратегия обновления (Rolling Update)

Блок `update_config` определяет поведение Swarm при смене версии образа или изменении параметров сервиса.

| Параметр | Описание | Значение по умолчанию |
|---|---|---|
| `parallelism` | Кол-во реплик, обновляемых одновременно | `1` |
| `delay` | Пауза между обновлением групп реплик | `0s` |
| `failure_action` | Действие при ошибке (`pause`, `continue`, `rollback`) | `pause` |
| `monitor` | Время наблюдения за новой репликой после запуска | `0s` |
| `max_failure_ratio` | Допустимая доля неудачных обновлений (0.0–1.0) | `0` |
| `order` | Порядок остановки и запуска (`start-first`, `stop-first`) | `stop-first` |

**Рекомендация по `order`:**
- `start-first`: Сначала запускается новая реплика, затем удаляется старая. Требует временно больше ресурсов, но обеспечивает Zero Downtime.
- `stop-first`: Сначала останавливается старая реплика, затем запускается новая. Экономит ресурсы, но возможен кратковременный простой.

### Сетевые режимы и балансировка (Endpoint Mode)

Swarm поддерживает два режима публикации портов:

- **VIP (Virtual IP)**: (По умолчанию) Сервис получает виртуальный IP. Трафик балансируется между репликами через Routing Mesh.
- **DNSRR (DNS Round Robin)**: Swarm не создает VIP. DNS-запрос по имени сервиса возвращает список IP-адресов всех реплик. Полезно, если клиент (например, Nginx) сам управляет балансировкой.

```yaml
deploy:
  endpoint_mode: dnsrr
```

### Тонкая настройка размещения (Placement)

Помимо ролей (`node.role`), можно использовать пользовательские метки (labels) для привязки сервисов к конкретному оборудованию.

```bash
# Добавление метки на узел
docker node update --label-add zone=dmz node-1
# → node-1
```

В YAML-файле:
```yaml
deploy:
  placement:
    constraints:
      - node.labels.zone == dmz
```

### Ограничение ресурсов

Всегда указывайте лимиты для предотвращения деградации производительности узлов:

```yaml
deploy:
  resources:
    reservations:
      cpus: '0.25'
      memory: 256M
    limits:
      cpus: '0.50'
      memory: 512M
```

## Миграция: С systemd на Swarm-сервис

При переходе от традиционного управления к Swarm-сервису важно учитывать смену парадигмы управления состоянием.

```yaml
nginx:
  image: nginx:alpine
  ports:
    - target: 443
      published: 443
      protocol: tcp
      mode: host  # Режим host позволяет сохранить реальный IP клиента
  volumes:
    - /etc/letsencrypt/live/{{ nginx_domain }}:/etc/nginx/ssl/certs:ro
```

**Ключевые отличия:**
- `systemctl restart` → `docker stack deploy` (декларативное обновление).
- Локальные пути → Использование **Docker Configs/Secrets** для портируемости.
- Прямой доступ по IP → Внутренний Service Discovery через Swarm DNS.

Подробнее о миграции конфигов — в **[Секреты и конфигурации в Swarm](./swarm_secrets_configs.md)**.

## Дополнительная информация

### Лучшие практики

- **Фиксация версий**: Всегда указывайте конкретный тег образа вместо `latest`.
- **Registry Auth**: Всегда используйте флаг `--with-registry-auth` в CI/CD пайплайнах.
- **Healthchecks**: Используйте инструкцию `healthcheck` для автоматического перезапуска неисправных контейнеров.
- **Внешние сети**: Создавайте сети управления трафиком (Ingress) отдельно от жизненного цикла приложения.

### Смотрите также

- **[Справочник CLI для Swarm](./swarm_management_cli.md)**
- **[Продвинутые стратегии развертывания](./swarm_stack_advanced.md)**
- **[Секреты и конфигурации в Swarm](./swarm_secrets_configs.md)**
