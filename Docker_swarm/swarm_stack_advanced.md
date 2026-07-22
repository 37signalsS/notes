# Docker Swarm: Продвинутые стратегии развертывания стеков

## Определения

**[Rolling Update (Поэтапное обновление)](../../CI-CD/Deployment_Strategies/rolling_update.md)** — стратегия постепенного обновления реплик сервиса без полной остановки обслуживания.

**[Canary Deployment (Канареечное развертывание)](../../CI-CD/Deployment_Strategies/canary_deployment.md)** — метод выпуска, при котором новая версия приложения направляется на небольшую группу пользователей для тестирования перед полным развертыванием.

**[Blue-Green Deployment (Сине-зеленое развертывание)](../../CI-CD/Deployment_Strategies/blue_green_deployment.md)** — стратегия, предполагающая наличие двух идентичных сред (Blue и Green) с мгновенным переключением трафика.

**[Placement Preferences (Предпочтения размещения)](./swarm_stack_deployment.md)** — механизмы распределения задач по узлам на основе меток (labels) или характеристик, таких как зона доступности или стойка.

## Базовые концепции

### Управление процессом обновления

Docker Swarm позволяет декларативно описывать поведение сервисов при обновлении через секции `update_config` и `rollback_config`. Основные параметры этих секций (parallelism, delay, monitor) подробно описаны в разделе **[Базовое развертывание стеков](./swarm_stack_deployment.md)**.

В продвинутых сценариях критически важно сочетание `update_config` с проверками здоровья (**Healthchecks**). Если новый контейнер не проходит healthcheck в течение периода `monitor`, Swarm классифицирует обновление как неудачное и выполняет `failure_action`.

### Расширенное управление размещением

Помимо жестких ограничений (`constraints`), Swarm поддерживает гибкое распределение задач:

1. **`spread`**: Равномерное распределение реплик по значениям конкретной метки (например, по дата-центрам или зонам).
2. **`max_replicas_per_node`**: Ограничение максимального количества реплик одного сервиса на одном узле кластера.

```yaml
deploy:
  placement:
    constraints:
      - node.role == worker
    preferences:
      - spread: node.labels.zone
    max_replicas_per_node: 1
```

### Режимы публикации сервисов (Endpoint Mode)

- **VIP (Virtual IP)**: (По умолчанию) Swarm назначает сервису виртуальный IP, который балансирует трафик между репликами.
- **DNSRR (DNS Round Robin)**: Swarm возвращает список IP-адресов всех реплик через DNS. Используется, когда требуется внешняя балансировка (например, через Nginx или Traefik) без промежуточного VIP.

## Практические сценарии

### Настройка стратегии Rolling Update с Healthcheck

Для надежного обновления необходимо настроить `healthcheck` в самом сервисе. Swarm будет ждать успешного прохождения проверки перед тем, как считать реплику обновленной.

```yaml
services:
  app:
    image: myapp:v2.0
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost/health"]
      interval: 10s
      timeout: 5s
      retries: 3
      start_period: 40s
    deploy:
      replicas: 6
      update_config:
        parallelism: 2
        delay: 30s
        failure_action: rollback
        monitor: 20s          # Должен быть больше, чем интервал healthcheck
        order: start-first
```

### Реализация Canary-развертывания через Traefik

Использование Traefik позволяет динамически перераспределять веса трафика между основной и канареечной версиями.

```yaml
version: '3.8'

services:
  web-stable:
    image: myapp:v1.0
    deploy:
      replicas: 10
      labels:
        - "traefik.http.routers.app.rule=Host(`app.example.com`)`"
        - "traefik.http.services.app.loadbalancer.server.port=80"
  
  web-canary:
    image: myapp:v1.1
    deploy:
      replicas: 1
      labels:
        - "traefik.http.routers.app.rule=Host(`app.example.com`)`"
        - "traefik.http.services.app.loadbalancer.server.port=80"
```

Для тонкой настройки весов (например, 90/10) в Traefik v2+ используются дополнительные лейблы `weighted`. Подробнее — в **[swarm_ingress_traefik.md](./swarm_ingress_traefik.md)**.

### Реализация Blue-Green развертывания

Стратегия Blue-Green в Swarm реализуется через манипуляцию именами сервисов или лейблами балансировщика.

```bash
# 1. Запуск новой версии (Green) в отдельном стеке
docker stack deploy -c green.yml myapp-green
# → Создание сервисов стека myapp-green

# 2. Проверка работоспособности Green-версии
curl -H "Host: green.example.com" http://loadbalancer-ip
# → HTTP/1.1 200 OK

# 3. Переключение трафика: обновление лейблов Ingress-контроллера 
# или изменение DNS-записи на внешний балансировщик.

# 4. Удаление старой версии (Blue)
docker stack rm myapp-blue
# → Стек myapp-blue удален
```

### Ротация секретов и конфигураций

При обновлении `configs` или `secrets` в Swarm они не обновляются "на лету" в запущенных контейнерах (так как они монтируются в `tmpfs`). Для ротации необходимо создать новую версию ресурса и обновить сервис.

```yaml
services:
  db:
    image: postgres:16
    secrets:
      - source: db_password_v2
        target: db_password
secrets:
  db_password_v1:
    external: true
  db_password_v2:
    external: true
```

### Устранение неисправностей (Troubleshooting)

#### Диагностика состояния деплоя

```bash
# Проверка причин остановки обновления
docker service inspect --format '{{json .UpdateStatus}}' <service_name> | jq
# → { "State": "paused", "Message": "update paused due to failure or timeout" }

# Просмотр последних ошибок задач (tasks)
docker stack ps <stack_name> --no-trunc
# → ID: ... Error: "task: non-zero exit (1)"

# Проверка событий кластера
docker node ps self
# → Выводит задачи, запущенные на текущем узле
```

#### Частые проблемы и решения

| Проблема | Причина | Решение |
|---|---|---|
| Обновление зависло в `paused` | `failure_action: pause` при сбоях | Изучить логи `docker service logs` и возобновить через `docker service update --resume` |
| Реплики постоянно перезапускаются | Некорректный `healthcheck` | Увеличить `start_period` или исправить команду проверки |
| `no suitable node` | Несоблюдение `placement constraints` или `max_replicas_per_node` | Проверить метки узлов `docker node inspect` |

## Дополнительная информация

### Сравнение с Kubernetes

| Параметр | Docker Stack | Kubernetes |
|---|---|---|
| **Управление трафиком** | Базовое (VIP), внешние Ingress | Продвинутое (Ingress, Service Mesh) |
| **Placement** | Constraints, Spread, Max Replicas | Affinity, Taints, Tolerations, Topology Spread |
| **Обновления** | Rolling Update (встроено) | Deployments, Operators (ArgoCD, Flux) |

### Смотрите также

- **[Базовое развертывание стеков](./swarm_stack_deployment.md)**
- **[Секреты и конфигурации в Swarm](./swarm_secrets_configs.md)**
- **[Справочник CLI для Swarm](./swarm_management_cli.md)**
- **[Входящий трафик и Traefik](./swarm_ingress_traefik.md)**
