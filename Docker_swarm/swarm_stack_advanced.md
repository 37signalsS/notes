# Docker Swarm: Продвинутые стратегии развертывания стеков

**Актуально для:** Docker Swarm 29.x

## Определения

**[Rolling Update (Поэтапное обновление)](../../CI-CD/Deployment_Strategies/rolling_update.md)** — стратегия постепенного обновления реплик сервиса, при которой новая версия заменяет старую без полной остановки системы. Является нативной для Docker Swarm и управляется через `deploy.update_config`.

**[Canary Deployment (Канареечное развертывание)](../../CI-CD/Deployment_Strategies/canary_deployment.md)** — метод выпуска, при котором новая версия приложения направляется на небольшую группу пользователей или долю трафика для тестирования перед полным развертыванием. В Swarm реализуется через параллельные сервисы и балансировщики трафика.

**[Blue-Green Deployment (Сине-зеленое развертывание)](../../CI-CD/Deployment_Strategies/blue_green_deployment.md)** — стратегия, предполагающая наличие двух идентичных сред (Blue и Green) с мгновенным переключением трафика. Обеспечивает минимальный риск и мгновенный откат.

**[Placement Preferences (Предпочтения размещения)](./swarm_stack_deployment.md#размещение-и-ограничения-placement) — механизмы мягкого (non-binding) распределения задач по узлам на основе меток (labels) или топологических характеристик. В отличие от `constraints`, позволяют оркестратору принимать гибкие решения при нехватке ресурсов.

**[Endpoint Mode (Режим публикации)](../swarm_core_concepts.md#сетевая-модель-и-балансировка) — способ маршрутизации трафика к репликам сервиса: VIP (виртуальный IP с IPVS) или DNSRR (DNS Round Robin).

## Предварительные требования

- Swarm-кластер инициализирован и доступен: `docker node ls` показывает менеджеров в статусе `Ready`/`Active`
- Docker Engine 29.x на всех менеджерах и воркерах
- Развернутый стек балансировщика (Traefik, Nginx, HAProxy) для сценариев с внешним трафиком
- Настроенные labels на узлах при использовании топологического размещения (`zone`, `datacenter`, `rack`, `node-type`)
- Для Canary/Blue-Green: поддержка внешнего балансировщика, который умеет менять backend-пулы без перезапуска
- Доступ к реестру контейнеров с необходимыми образами

## Базовые концепции

### Тонкая настройка обновления (`update_config`)

Секция `deploy.update_config` управляет поведением Swarm при изменении спецификации сервиса. Базовый синтаксис и параметры описаны в [Развертывании стеков](./swarm_stack_deployment.md#настройка-rolling-update-и-rollback) и [Управлении жизненным циклом приложения](./CI_CD/app_lifecycle.md#детальная-настройка-update_config).

**Параметры, важные для продвинутых сценариев:**

| Параметр | Влияние на продвинутые стратегии |
|---|---|
| `parallelism` | При `0` обновляются все реплики сразу — подходит для `rollback_config`, но создает даунтайм для обычного деплоя |
| `order: start-first` | Требует двойного количества ресурсов на время обновления (старая + новая реплика). Критично для Zero Downtime |
| `monitor` | Должен превышать время прогрева приложения (JIT, кэширование соединений). При `monitor < startup` происходит ложный rollback |
| `failure_action` | `rollback` — автоматический возврат к предыдущей версии; `pause` — ручное вмешательство |

### Настройка автоматического отката (`rollback_config`)

Часто игнорируется, но определяет поведение Swarm *во время* процесса отката. Должна быть максимально агрессивной для быстрого восстановления. Базовый синтаксис описан в [Развертывании стеков](./swarm_stack_deployment.md#настройка-rolling-update-и-rollback).

```yaml
deploy:
  rollback_config:
    parallelism: 0          # Откатить все реплики максимально быстро
    order: stop-first       # Очистить ресурсы от сбойной версии
    failure_action: pause   # Если откат упал — критический сбой
    monitor: 10s
```

### Режимы публикации сервисов (Endpoint Mode)

Swarm предлагает два способа маршрутизации трафика:

1. **VIP (Virtual IP)**: (По умолчанию). Каждому сервису назначается виртуальный IP внутри кластера. Балансировка на уровне ядра (IPVS). Удобно, прозрачно, но балансировщик не знает о реальных IP-адресах контейнеров.
2. **DNSRR (DNS Round Robin)**: Swarm возвращает список IP-адресов всех живых реплик при DNS-запросе к имени сервиса. Подходит для внешних балансировщиков (Traefik, Nginx, HAProxy), которые сами управляют списком бэкендов.

```yaml
services:
  api:
    image: myapp:stable
    deploy:
      endpoint_mode: dnsrr  # Вместо VIP возвращает список IP реплик
```

### Топологическое управление размещением (Placement Preferences)

Использование `spread` позволяет Swarm равномерно распределять реплики по различным категориям узлов (например, по дата-центрам или стойкам), обеспечивая высокую отказоустойчивость. Базовый синтаксис описан в [Развертывании стеков](./swarm_stack_deployment.md#размещение-и-ограничения-placement).

```yaml
deploy:
  placement:
    preferences:
      - spread: node.labels.datacenter
    max_replicas_per_node: 1
```

### Версионирование секретов в стеках

Поскольку секреты в Swarm неизменяемы, обновление чувствительных данных требует версионирования имен. При деплое стека Swarm выполнит Rolling Update, заменяя контейнеры, которые используют новый секрет.

## Практические сценарии

### Сценарий 1: Rolling Update с гарантией доступности

Комбинация `start-first`, длительного `monitor` и обработки сигналов завершения.

```yaml
services:
  web:
    image: myapp:v2.1
    stop_grace_period: 1m     # Даем приложению время закрыть коннекты
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8080/health"]
      interval: 10s
      timeout: 5s
      retries: 3
      start_period: 45s       # Время на прогрев (JIT, кэши)
    deploy:
      replicas: 5
      update_config:
        parallelism: 1
        delay: 30s
        order: start-first    # Zero Downtime
        monitor: 1m           # Долгая проверка после старта
        failure_action: rollback
```

**Валидация:**
```bash
docker service ps web --no-trunc
# → все задачи в статусе Running, новая реплика прошла healthcheck
docker service inspect --format '{{json .UpdateStatus}}' web | jq
# → { "State": "completed", "StartedAt": "...", "CompletedAt": "..." }
```

### Сценарий 2: Blue-Green развертывание через переключение стеков

В Swarm нет встроенного Blue-Green, но его можно реализовать через манипуляцию именами стеков или лейблами Traefik.

**Шаги реализации:**
1. Развернуть текущую версию (Blue): `docker stack deploy -c stack.yml myapp-blue`.
2. Развернуть новую версию (Green) параллельно: `docker stack deploy -c stack.yml myapp-green`.
3. Переключить трафик на внешнем балансировщике (например, изменить `Host` правило в Traefik).
4. После верификации удалить старый стек: `docker stack rm myapp-blue`.

**Валидация:**
```bash
docker stack ls
# → myapp-blue, myapp-green
docker service ls
# → сервисы из обоих стеков запущены
curl -H "Host: api.example.com" http://<traefik-ip>
# → отвечает новая версия (Green)
```

### Сценарий 3: Canary-развертывание (Weighted Traffic) с Traefik

Использование двух сервисов с разным количеством реплик или весами в Traefik.

```yaml
services:
  app:
    image: myapp:stable
    deploy:
      replicas: 10
      labels:
        - "traefik.http.routers.app.rule=Host(`api.example.com`)"
        - "traefik.http.services.app-svc.loadbalancer.server.port=80"

  app-canary:
    image: myapp:beta
    deploy:
      replicas: 1
      labels:
        - "traefik.http.routers.app.rule=Host(`api.example.com`)"
        - "traefik.http.services.app-svc.loadbalancer.server.port=80"
```

**Валидация:**
```bash
docker service ls
# → app 10/10, app-canary 1/1
curl -H "Host: api.example.com" http://<traefik-ip>
# → трафик распределяется пропорционально репликам (10:1)
```

### Сценарий 4: Безопасное обновление секретов (Versioning)

Поскольку секреты неизменяемы, используйте версионирование в именах. Подробнее: **[Секреты и конфигурации в Swarm](../swarm_secrets_configs.md)**.

```yaml
services:
  db:
    image: postgres:15
    secrets:
      - source: db_password_v2
        target: db_password   # Внутри контейнера путь остается неизменным
secrets:
  db_password_v2:
    external: true
```

**Процесс:**
1. `docker secret create db_password_v2 new_pass.txt`
2. Обновить YAML и запустить `docker stack deploy`.
3. Swarm выполнит Rolling Update, заменяя контейнеры на те, что используют новый секрет.

**Валидация:**
```bash
docker service ps db --no-trunc
# → все задачи обновлены, используют db_password_v2
docker secret ls
# → db_password_v2 (актуальный), db_password (старый, можно удалить)
```

### Сценарий 5: Очистка кластера от "сиротских" ресурсов

При удалении сервисов из Compose-файла они не удаляются из Swarm автоматически.

**Решение:**
```bash
# Флаг --prune удаляет сервисы, которые больше не описаны в конфиге
docker stack deploy --prune -c docker-compose.yml myapp
```

**Валидация:**
```bash
docker stack services myapp
# → только актуальные сервисы из docker-compose.yml
docker stack rm myapp
# → все ресурсы стека удалены
```

## Операции и команды

| Область | Команды | Назначение |
|:---|:---|:---|
| **Развертывание** | `docker stack deploy -c <file> <name>` | Деплой стека из Compose-файла |
| | `docker stack deploy --prune -c <file> <name>` | Деплой с удалением устаревших сервисов |
| | `docker stack deploy --with-registry-auth <name>` | Передача registry-авторизации воркерам |
| **Инспекция** | `docker stack ls` | Список всех стеков |
| | `docker stack services <name>` | Сервисы в стеке |
| | `docker stack ps <name> --no-trunc` | Задачи сервисов с деталями |
| **Управление** | `docker stack rm <name>` | Удаление стека и всех его ресурсов |
| | `docker stack config <file>` | Валидация и просмотр итогового Compose-конфига |

## Устранение неисправностей

### Диагностика процесса обновления

Если деплой "завис" или ведет себя странно:

```bash
# 1. Детальный статус обновления (показывает ошибки и текущую фазу)
docker service inspect --format '{{json .UpdateStatus}}' <service_name> | jq

# 2. Проверка ошибок размещения (например, "no suitable node found")
docker service ps --no-trunc <service_name>

# 3. Анализ логов только для задач новой версии
docker service logs --since 5m -f <service_name>
```

### Типичные ошибки и их решение

| Проблема | Возможная причина | Решение |
|---|---|---|
| Деплой висит в `Pending` | Нехватка ресурсов для `start-first` | Добавить ресурсов или сменить на `stop-first`. |
| Постоянный Rollback | `monitor` меньше времени старта приложения | Увеличить `monitor` или `start_period` в healthcheck. |
| Потеря Client IP | Используется `Ingress` режим (L4 VIP) | Переключить сервис в `mode: host` или использовать Proxy Protocol. |
| Секрет не обновился | Попытка изменить существующий секрет | Использовать новое имя секрета (версионирование). |
| `update_config` не срабатывает | Изменение только меток без изменения образа | Swarm игнорирует изменения labels в `update_config`; измените `image` или `args`. |

### Диагностика через CLI

| Задача | Команда |
|---|---|
| Статус Swarm на текущем узле | `docker info --format '{{json .Swarm}}'` |
| Детальный статус задачи | `docker service ps --no-trunc <SERVICE> --filter "desired-state=shutdown"` |
| Статус секретов сервиса | `docker service inspect <SERVICE> --format '{{json .Spec.TaskTemplate.ContainerSpec.Secrets}}'` |
| Статус конфигураций сервиса | `docker service inspect <SERVICE> --format '{{json .Spec.TaskTemplate.ContainerSpec.Configs}}'` |
| Проверка кворума Raft | `docker info --format '{{json .Swarm.RemoteManagers}}'` |

## Лучшие практики

1. **Агрессивный rollback:** настраивайте `rollback_config` с `parallelism: 0` и `order: stop-first` для быстрого возврата к стабильной версии.
2. **Достаточный monitor:** всегда превышайте время прогрева приложения в `monitor`; добавляйте `start_period` в healthcheck для JIT-компилируемых языков.
3. **Секреты:** используйте версионирование имен секретов и `docker service update --secret-rm/--secret-add` вместо удаления активных секретов.
4. **Placement:** комбинируйте `constraints` (hard) и `preferences` (soft) — constraints фильтруют узлы, preferences оптимизируют распределение.
5. **Endpoint mode:** для внешних балансировщиков используйте `dnsrr`, для простых случаев — `vip` (по умолчанию).
6. **Prune:** добавляйте `--prune` в CI/CD-пайплайны для автоматической очистки устаревших сервисов.
7. **Rollback config vs Update config:** настраивайте их независимо — rollback должен быть быстрее и агрессивнее обычного обновления.
8. **Глобальные сервисы (`mode: global`):** не поддерживают `replicas` и `update_config` в привычном виде; обновление происходит через изменение образа на всех узлах.

## Дополнительная информация

### Сравнение механизмов Swarm и Kubernetes

| Характеристика | Docker Swarm | Kubernetes |
|---|---|---|
| **Нативный Rolling Update** | Да (`update_config`) | Да (`strategy: RollingUpdate`) |
| **Авто-откат (Auto-Rollback)** | Встроенный | Требует внешних инструментов (ArgoCD/Rollouts) |
| **Сложные стратегии** | Через манипуляцию сервисами | Нативно (Canary, Blue-Green в Rollouts) |
| **Балансировка** | IPVS (VIP), DNS Round Robin | Services, Ingress, Service Mesh |

### Смотрите также

- **[Развертывание стеков (Stack Deployment)](./swarm_stack_deployment.md)** — основы `deploy`, `constraints` и базовый `update_config`.
- **[Управление жизненным циклом приложения](./CI_CD/app_lifecycle.md)** — детально про `stop_grace_period`, `update_config` и диагностику.
- **[Основные концепции Docker Swarm](../swarm_core_concepts.md)** — теория Raft, endpoint mode, балансировка.
- **[Справочник CLI для Swarm](../swarm_management_cli.md)** — команды управления сервисами и стеками.
- **[Traefik в Swarm](../swarm_ingress_traefik.md)** — настройка Ingress-контроллера для Blue-Green и Canary.
- **[Секреты и конфигурации в Swarm](../swarm_secrets_configs.md)** — управление данными, версионность и монтирование.
