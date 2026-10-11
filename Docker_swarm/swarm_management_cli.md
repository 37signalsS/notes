# Docker Swarm: Справочник CLI

**Актуально для:** Docker Swarm 29.x

## Определения

**CLI (Command Line Interface)** — основной инструмент Docker для управления Swarm-кластером. Все операции по оркестрации выполняются через подкоманды `docker`.

**Контекст исполнения** — область действия команд. Большинство операций по изменению состояния кластера (`node`, `service`, `stack`, `secret`, `config`) доступны только на узлах с ролью менеджера.

**Docker Context** — именованный профиль подключения к Docker-хосту (локальному или удаленному). Позволяет инкапсулировать параметры endpoint (mTLS-сертификаты, SSH-ключи) и переключаться между кластерами без изменения переменных окружения. Начиная с Docker CLI v23.0, поддержка Kubernetes в `docker context` удалена; для Swarm используется только тип endpoint `docker`.

## Базовые концепции

### Иерархия команд

| Уровень | Команда | Назначение |
|---|---|---|
| Кластер | `docker swarm` | Инициализация, присоединение и глобальные настройки (CA, автоблокировка, unlock-key) |
| Узлы | `docker node` | Управление жизненным циклом узлов, их ролями, метками и доступностью |
| Сервисы | `docker service` | Декларативное управление отдельными сервисами кластера |
| Стеки | `docker stack` | Оркестрация многоконтейнерных приложений через Compose-файлы |
| Сети | `docker network` | Управление оверлейными и bridge-сетями кластера |
| Секреты | `docker secret` | Безопасное хранение чувствительных данных в Raft |
| Конфигурации | `docker config` | Управление нечувствительными данными (nginx.conf и др.) |
| Тома | `docker volume` | Управление локальными и cluster-томами (начиная с Docker 23.0; cluster-флаги скрыты без Swarm-менеджера) |
| Контексты | `docker context` | Управление профилями подключения к локальным и удаленным менеджерам |

### Требования к правам доступа

- **Менеджеры:** Полный доступ ко всем командам управления кластером.
- **Рабочие узлы:** Могут выполнять локальные команды (например, `docker info`), но не имеют доступа к управлению сервисами или другими узлами.
- **Любой узел:** Команды `service ps` или `network inspect` технически могут быть выполнены на любом узле, если у пользователя есть права на Docker socket, но полный статус кластера виден только менеджерам.
- **Дистанционное управление:** Рекомендуется использовать `docker context` через SSH для безопасного доступа к API удаленного менеджера без открытия портов вовне.

## Предварительные требования

- **Docker Engine 29.x** на всех узлах кластера.
- **Открытые порты** между узлами:
  - `2377/TCP` — управление кластером (Raft/gossip management)
  - `7946/TCP` и `7946/UDP` — gossip-протокол (обнаружение узлов)
  - `4789/UDP` — VXLAN (трафик overlay-сетей)
  - ESP 50 (IP protocol 50) — для зашифрованных overlay-сетей (`--opt encrypted`)
- **NTP** — синхронизация времени на всех узлах (критично для mTLS и ротации сертификатов).
- **Ресурсы:** минимум 2 CPU и 4 GB RAM для менеджеров; рабочие узлы — по требованиям сервисов.
- **Labels:** для топологического планирования назначайте метки на узлы (`docker node update --label-add zone=rack-1 <node>`).

## Практические сценарии

### Управление кластером (docker swarm)

#### Инициализация и настройка

```bash
# Инициализация первого менеджера
docker swarm init \
  --advertise-addr 192.168.1.10 \
  --data-path-addr 10.0.0.1 \
  --listen-addr 0.0.0.0:2377
# → Swarm initialized: current node (abc123def) is now a manager.
```

**Валидация:**
```bash
docker info --format '{{json .Swarm}}'
# → {"NodeID":"abc123def...","NodeAddr":"192.168.1.10","LocalNodeState":"active","ControlAvailable":true,"Error":""}
```

**Ключевые параметры:**
- `--advertise-addr` — адрес, который узел сообщает другим участникам для связи (обязателен при наличии нескольких интерфейсов).
- `--data-path-addr` — IP-адрес для VXLAN-трафика (позволяет отделить трафик данных приложений от трафика управления Raft).
- `--listen-addr` — интерфейс и порт, на котором демон слушает входящие запросы Swarm.
- `--cert-expiry` — срок действия TLS-сертификатов (по умолчанию 2160h = 90 дней).

#### Управление безопасностью и сертификатами

```bash
# Включение автоблокировки (защита данных Raft при перезагрузке)
docker swarm update --autolock=true
# → SMTKN-1-v3q... (этот ключ необходим для запуска демона после перезагрузки)

# Разблокировка узла после перезагрузки
docker swarm unlock
# → Please enter unlock key:

# Ротация ключа разблокировки (без изменения сертификатов)
docker swarm unlock-key --rotate
# → Swarm unlock key rotated successfully.

# Ротация сертификатов CA кластера (обновление всех TLS-сертификатов)
docker swarm ca --rotate --cert-expiry 2160h
# → (инициирует постепенное обновление сертификатов на всех узлах)
```

**Валидация:**
```bash
docker info --format '{{json .Swarm.CAStatus}}'
# → {"NodeID":"abc123def...","ExtensionCount":1,"Extensions":[{"ExtensionID":"primary","Data":"...","Err":""}]}
```

**Важно:** `docker swarm ca --rotate` инициирует асинхронное обновление. Проверьте статус через `docker node ls` — у менеджеров будет отображаться `Manager Status: Reachable` после успешной ротации.

#### Присоединение и выход узлов

```bash
# Получение токена для новых рабочих узлов
docker swarm join-token worker
# → docker swarm join --token SWMTKN-1-49nj1... 192.168.1.10:2377

# Получение токена для новых менеджеров
docker swarm join-token manager
# → docker swarm join --token SWMTKN-1-58mk2... 192.168.1.10:2377

# Присоединение (выполняется на целевом узле)
docker swarm join --token <TOKEN> 192.168.1.10:2377
# → This node joined a swarm as a worker.

# Выход из кластера (на целевом узле)
docker swarm leave
# → Node left the swarm.

# Принудительный выход менеджера (используется при восстановлении кворума)
docker swarm leave --force
# → Node left the swarm.
```

**Валидация:**
```bash
# На менеджере: проверка списка узлов
docker node ls
# → ушедший узел больше не отображается

# На вышедшем узле: проверка статуса Swarm
docker info --format '{{.Swarm.LocalNodeState}}'
# → inactive
```

#### Восстановление кворума

```bash
# На живом менеджере: принудительное создание нового кластера
docker swarm init --force-new-cluster --advertise-addr <IP>
# → Swarm initialized: current node (xyz789...) is now a manager.

# Повторное присоединение менеджеров
docker swarm join-token manager
# → docker swarm join --token SWMTKN-1-... <IP>:2377
```

**Валидация:**
```bash
docker node ls --filter role=manager
# → новый лидер активен
docker info --format '{{json .Swarm.RemoteManagers}}'
# → массив активных менеджеров
```

### Управление узлами (docker node)

#### Мониторинг и инспекция

```bash
# Список всех узлов с фильтрацией по статусу
docker node ls --filter "role=manager"
# → ID            HOSTNAME  STATUS  AVAILABILITY  MANAGER STATUS  ENGINE VERSION
# → abc123def *   node-1    Ready   Active        Leader          29.8.1

# Форматированный вывод (удобно для скриптов)
docker node ls --format "{{.Hostname}}: {{.Status}}"
# → node-1: Ready

# Детальная информация в читаемом виде
docker node inspect --pretty <NODE_ID>
# → ID: abc123def...
# → Hostname: node-1
# → Status: State: Ready, Availability: Active

# Просмотр ресурсов узла (CPU, Memory)
docker node inspect <NODE_ID> --format '{{json .Description.Resources}}'
# → {"NanoCPUs":4000000000,"MemoryBytes":17179869184}
```

**Валидация:**
```bash
docker node inspect <NODE_ID> --format '{{.Status.State}}'
# → Ready
docker node inspect <NODE_ID> --format '{{.Spec.Availability}}'
# → Active
```

#### Изменение состояния и ролей

```bash
# Повышение рабочего узла до менеджера
docker node promote worker-1
# → Node worker-1 promoted to a manager.

# Понижение менеджера до рабочего узла
docker node demote manager-1
# → Manager manager-1 demoted to a worker in the swarm.

# Перевод узла в режим обслуживания (Drain)
docker node update --availability drain worker-1
# → worker-1
# Пояснение: все задачи на этом узле будут остановлены и пересозданы на других доступных узлах.

# Возврат узла в активное состояние
docker node update --availability active worker-1
# → worker-1

# Добавление метки
docker node update --label-add rack=rack-3 worker-1
# → worker-1

# Удаление метки
docker node update --label-rm rack worker-1
# → worker-1
```

**Валидация:**
```bash
docker node inspect worker-1 --format '{{ .Spec.Availability }}'
# → drain
docker node ps web --filter node=worker-1
# → задачи пересозданы на других узлах
```

### Управление сервисами (docker service)

#### Создание и отладка

```bash
# Создание сервиса с лимитами и Health Check
docker service create --name api \
  --replicas 3 \
  --reserve-memory 256m --limit-memory 512m \
  --health-cmd "curl -f http://localhost/health || exit 1" \
  --health-interval 30s \
  myapp:v1
# → xyz789...

# Поиск причин падения задач (флаг --no-trunc показывает полную ошибку)
docker service ps --no-trunc api
# → (выводит детали, например: "non-zero exit code 139" или "No such image")

# Просмотр логов
# -f: следовать за логом (follow)
# --tail 100: показать последние 100 строк
docker service logs -f --tail 100 api
```

**Валидация:**
```bash
docker service ls
# → api    3/3  myapp:v1
docker service ps api --no-trunc
# → все задачи в статусе Running
```

#### Масштабирование и обновление

```bash
# Масштабирование (эквивалентно docker service update --replicas)
docker service scale web=10
# → web scaled to 10

# Инспекция статуса обновления (Go-template для JSON)
docker service inspect --format '{{json .UpdateStatus}}' api | jq
# → { "State": "completed", "StartedAt": "...", "CompletedAt": "..." }

# Обновление с контролем параллелизма и задержки
docker service update --image myapp:v2 --update-parallelism 2 --update-delay 10s api
# → api

# Обновление с политикой обработки ошибок
docker service update \
  --image myapp:v3 \
  --update-parallelism 2 \
  --update-failure-action rollback \
  --rollback-failure-action pause \
  api
# → api

# Принудительное обновление (пересоздание задач даже без изменений)
docker service update --force --image myapp:v2 api
# → api

# Откат к предыдущей версии
docker service rollback api
# → Rollback service api to previous image myapp:v1
```

**Валидация:**
```bash
docker service ps api --no-trunc
# → все задачи обновлены до новой версии
docker service inspect --format '{{.Spec.TaskTemplate.ContainerSpec.Image}}' api
# → myapp:v2
```

#### Управление секретами и конфигурациями сервиса

```bash
# Ротация секрета: добавление новой версии и удаление старой
docker service update \
  --secret-rm db_password \
  --secret-add source=db_pass_v2,target=db_password \
  web
# → web

# Добавление конфигурации
docker service update --config-add source=nginx_v2,target=/etc/nginx/nginx.conf web
# → web
```

**Валидация:**
```bash
docker service inspect web --format '{{json .Spec.TaskTemplate.ContainerSpec.Secrets}}'
# → новый secret смонтирован
docker service inspect web --format '{{json .Spec.TaskTemplate.ContainerSpec.Configs}}'
# → новый config смонтирован
```

#### Управление сетями сервиса

```bash
# Подключение сервиса к overlay-сети
docker service update --network-add backend-net api
# → api

# Отключение сервиса от сети
docker service update --network-rm frontend-net api
# → api
```

### Работа со стеками (docker stack)

```bash
# Развертывание стека
# --with-registry-auth: передает данные аутентификации из локального Docker-клиента 
# на все узлы Swarm (необходимо для скачивания образов из частных реестров).
docker stack deploy -c docker-compose.yml --with-registry-auth prod_stack
# → Creating network prod_stack_default
# → Creating service prod_stack_web

# Развертывание с удалением устаревших сервисов
docker stack deploy --prune -c docker-compose.yml prod_stack
# → Removing service prod_stack_old_worker

# Список сервисов в стеке
docker stack services prod_stack
# → ID            NAME             MODE        REPLICAS  IMAGE
# → 123           prod_stack_web   replicated  2/2       nginx:latest

# Список задач в стеке
docker stack ps prod_stack
# → ID            NAME               IMAGE          NODE        DESIRED STATE
# → abc123        prod_stack_web.1   nginx:latest   node-1      Running

# Удаление стека
docker stack rm prod_stack
# → Removing service prod_stack_web
# → Removing network prod_stack_default
```

**Валидация:**
```bash
docker stack ls
# → prod_stack больше не отображается
docker network ls --filter "name=prod_stack"
# → сети удалены (если external: true не использовалось)
```

### Секреты и конфигурации (docker secret/config)

```bash
# Создание секрета из файла
docker secret create db_password ./password.txt
# → abc456...

# Создание из стандартного ввода (безопаснее, не оставляет следов в истории)
echo "my_secret_token" | docker secret create api_token -

# Создание конфигурации с метками
docker config create --label env=prod --label app=nginx nginx_v1 ./nginx.conf

# Список секретов с фильтром по метке
docker secret ls --filter "label=env=prod"

# Инспекция секрета (содержимое скрыто)
docker secret inspect db_password

# Удаление секрета (только если не используется)
docker secret rm db_password
```

**Валидация:**
```bash
docker secret ls
# → секрет присутствует
docker secret inspect db_password --format '{{.Spec.Name}}'
# → db_password
```

### Управление сетями (docker network)

```bash
# Создание overlay-сети
docker network create --driver overlay --attachable backend-net
# → abc123...

# Список overlay-сетей
docker network ls --filter driver=overlay

# Инспекция сети
docker network inspect backend-net

# Подключение сервиса к сети
docker service update --network-add backend-net api

# Отключение сервиса от сети
docker service update --network-rm backend-net api

# Удаление сети (только если нет сервисов)
docker network rm backend-net

# Очистка неиспользуемых сетей
docker network prune --filter "until=24h"
```

**Валидация:**
```bash
docker network ls --filter driver=overlay
# → сеть отображается
docker network inspect backend-net --format '{{.Scope}}'
# → swarm
```

### Управление томами (docker volume)

```bash
# Создание локального тома
docker volume create --driver local --opt type=nfs --opt opt=device=:/mnt/share pg_data

# Список томов
docker volume ls

# Инспекция тома
docker volume inspect pg_data

# Создание cluster-тома (начиная с Docker 23.0)
docker volume create --driver <csi-driver> --type mount --scope multi --sharing all pg_cluster

# Список cluster-томов
docker volume ls --cluster

# Инспекция cluster-тома (статус Published/Pending)
docker volume inspect pg_cluster

# Принудительное освобождение cluster-тома (опасно!)
docker volume update --availability drain pg_cluster
docker volume rm pg_cluster
```

**Валидация:**
```bash
docker volume inspect pg_data --format '{{.Mountpoint}}'
# → /var/lib/docker/volumes/pg_data/_data
docker volume inspect pg_cluster
# → Published: node-3, Pending: ""
```

## Устранение неполадок

### Потеря кворума менеджеров

Если кластер перешел в режим "только чтение" (нельзя создавать/обновлять сервисы):
1. Проверьте количество активных менеджеров: `docker node ls --filter role=manager`
2. Восстановите кворум до `(N/2) + 1` активных менеджеров.
3. Если невозможно восстановить кворум, принудительно создайте новый кластер на живом менеджере: `docker swarm init --force-new-cluster --advertise-addr <IP>`

### Задачи не запускаются (Pending/Rejected)

1. Проверьте ресурсы узла: `docker node inspect <node> --format '{{ .Description.Resources }}'`
2. Проверьте constraints: `docker service inspect <service> --format '{{ .Spec.TaskTemplate.Placement.Constraints }}'`
3. Проверьте статус задач: `docker service ps <service> --no-trunc`
4. Для rejected задач проверьте совместимость образа с архитектурой узла (`docker info --format '{{ .Architecture }}'`)

### Частые ошибки mTLS и сертификатов

- **"Certificate has expired or is not yet valid"**: проверьте синхронизацию времени (NTP) на всех узлах.
- **"swarm daemon is locked"**: разблокируйте менеджер: `docker swarm unlock`
- **Ротация сертификатов**: измените срок действия: `docker swarm update --cert-expiry 2160h` (90 дней по умолчанию)

### Перегрузка Control Plane (Gossip)

При большом количестве сервисов (>1000) или сетей (>500) протокол gossip создает нагрузку:
1. Группируйте сервисы в общие overlay-сети.
2. Используйте выделенные менеджеры без воркер-нагрузок (`docker node update --availability drain <manager>`).

### Ошибки планировщика

- **No suitable node**: убедитесь, что есть узлы с достаточными ресурсами и удовлетворяющие constraints.
- **Image not found**: проверьте доступность реестра на рабочих узлах (`docker service inspect <service> --format '{{.Spec.TaskTemplate.ContainerSpec.Image}}'`).
- **Conntrack table overflow**: при очень высокой нагрузке увеличьте размер таблицы `conntrack` в ядре Linux.

## Лучшие практики

1. **Количество менеджеров:** используйте 3 или 5 менеджеров. 7 — максимальный предел для эффективного Raft.
2. **Выделенные менеджеры:** для кластеров >10 узлов настраивайте менеджеров без воркер-задач (`drain`).
3. **Мониторинг кворума:** настройте алерты при потери менеджеров (`docker node ls --filter role=manager`).
4. **Ротация секретов:** используйте версионирование имен секретов и `docker service update --secret-rm/--secret-add` вместо удаления активных секретов.
5. **Backup Raft:** регулярно копируйте директорию `/var/lib/docker/swarm/raft` на менеджерах.
6. **NTP:** синхронизируйте время на всех узлах — это критично для mTLS.
7. **Labels:** используйте метки для топологического планирования (`zone`, `rack`, `node-type`).
8. **Update Config:** настраивайте `--update-parallelism`, `--update-delay`, `--rollback` для безопасных обновлений.

## Дополнительная информация

### Продвинутая диагностика через CLI

| Задача | Команда |
|:---|:---|
| Статус Swarm на текущем узле | `docker info --format '{{json .Swarm}}'` |
| Проверка кворума Raft | `docker info --format '{{json .Swarm.RemoteManagers}}'` |
| Детальный аудит узла | `docker node inspect <NODE_ID> --format '{{json .Status}}'` |
| Ошибки планировщика | `docker service ps --no-trunc <SERVICE> --filter "desired-state=shutdown"` |
| Статус секретов сервиса | `docker service inspect <SERVICE> --format '{{json .Spec.TaskTemplate.ContainerSpec.Secrets}}'` |
| Статус конфигураций сервиса | `docker service inspect <SERVICE> --format '{{json .Spec.TaskTemplate.ContainerSpec.Configs}}'` |

### Полезные флаги фильтрации (`--filter`)

- `id`: Поиск по точному ID или префиксу.
- `label`: Поиск по метаданным (например, `label=app=web`).
- `name`: Поиск по части имени.
- `role`: Фильтрация узлов по роли (`manager` или `worker`).
- `desired-state`: Фильтрация задач по состоянию (`running`, `shutdown`, `accepted`, `ready`, `pending`, `assigned`).
- `driver`: Фильтрация сетей по драйверу (`overlay`, `bridge`, `host`).

### Смотрите также

- **[Основные концепции Docker Swarm](./swarm_core_concepts.md)** — теория Raft, кворум и жизненный цикл задач.
- **[Сетевое взаимодействие в Swarm](./swarm_networking.md)** — управление через `docker network`, overlay, IPVS и VXLAN.
- **[Секреты и конфигурации](./swarm_secrets_configs.md)** — подробности управления данными, версионность и монтирование.
- **[Развертывание стеков](./swarm_stack_deployment.md)** — детальное использование `docker stack`, Compose vs Stack.
- **[Продвинутые темы](./swarm_advanced_topics.md)** — глубокие детали Raft, mTLS, autolock и восстановление кворума.
- **[Управление томами](./swarm_volumes.md)** — локальные и cluster-томы, CSI-драйверы.
- **[Использование Docker Context в CI/CD](./CI_CD/docker_context_setup.md)** — настройка контекстов для автоматизации.
