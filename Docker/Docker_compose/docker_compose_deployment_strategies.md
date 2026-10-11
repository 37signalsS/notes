# Стратегии развёртывания и откат в Docker Compose

**Актуально для:** Docker Compose v5.x / v2.20+ (Compose Specification). Compose v5 (с 2025) функционально идентичен v2 — отличие только в официальном Go SDK; все флаги и поведение ниже применимы к обеим линиям. Общая теория стратегий (blue-green, canary, rolling, recreate) — в SSoT-разделе [CI-CD/Deployment_Strategies](../../CI-CD/Deployment_Strategies/); здесь — реализация на compose.

## Определения

**Rolling update в compose** — постепенная замена контейнеров новой версией через масштабирование (`--scale` / `scale:`) и drain старых. Compose не имеет нативного контроллера rolling update (в отличие от Kubernetes Deployment): оркестрация выполняется вручную или через балансировщик.

**Blue-green в compose** — два независимых стека (проекта) одной конфигурации, развёрнутых параллельно с разными именами проектов (`-p blue` / `-p green`); переключение трафика — атомарная операция на сетевом слое (балансировщик, upstream, DNS).

**Canary в compose** — запуск новой версии как отдельного сервиса/стека с долей трафика, управляемой балансировщиком (веса в Traefik/Nginx), с автоматическим откатом по метрикам.

**Откат (rollback)** — возврат к предыдущей версии: в compose это повторный `up` с предыдущей конфигурацией или предыдущим тегом/digest образа.

**Health Gate** — этап проверки готовности нового стека (`docker compose up --wait`, smoke-тесты) *до* переключения трафика.

**Recreate в compose** — стратегия с кратковременным простоем: старый стек полностью останавливается и удаляется (`down`), затем создаётся и запускается новый (`up`). Простейшая в реализации, но единственная стратегия с гарантированным окном недоступности.

## Базовые концепции

### Почему compose требует ручной оркестрации

Compose — инструмент развёртывания на одном хосте, а не оркестратор: он не отслеживает desired state, не пересоздаёт контейнеры по событию и не делит трафик между версиями. Поэтому:

- **Rolling update** эмулируется масштабированием: поднять новые реплики, дождаться `healthy`, остановить старые.
- **Изоляция версий** достигается именем проекта: контейнеры, сети и тома двух проектов не конфликтуют. Приоритет имени проекта (по документации Docker): флаг `-p` > переменная `COMPOSE_PROJECT_NAME` > ключ `name:` в файле > имя директории.
- **Переключение трафика** всегда внешнее: Nginx `upstream`, Traefik weighted services, DNS или VIP.
- **Реконсиляция состояния (Compose v5.2+):** `up` вычисляет план реконсиляции между наблюдаемым (observed) и ожидаемым (expected) состоянием — контейнеры пересоздаются при изменении config-hash конфигурации или digest образа, неизменные ресурсы не трогаются (v5.4+ реконсилирует жизненный цикл сетей и томов, v5.5+ доработал digest-реконсиляцию, чтобы не пересоздавать контейнеры без необходимости). Для стратегий это значит: откат через возврат конфигурации в Git + `up` надёжно пересоздаёт контейнеры на старой версии, а повторный `up` без изменений работающий стек не нарушает.

### Жизненный цикл релиза на compose

1. **Подготовка:** новая конфигурация в Git, образы собраны и пропинкованы (тег или digest).
2. **Health Gate:** `docker compose -p <new> up -d --wait` — возврат только когда все сервисы `healthy`.
3. **Smoke-тесты:** `docker compose -p <new> run --rm test-runner <cmd>`.
4. **Cutover:** переключение балансировщика/upstream на новый стек.
5. **Soak:** наблюдение метрик; при регрессе — мгновенный возврат трафика на старый стек.
6. **Decommission:** `docker compose -p <old> down -v` после окна выдержки.

**Особенности Health Gate:** `--wait` сам переводит `up` в detached-режим (флаг `-d` при `--wait` избыточен) и несовместим с `--abort-on-container-exit`, `--attach` и `--attach-dependencies`. Одноразовые сервисы (миграции), объявленные в `depends_on` с `condition: service_completed_successfully`, `--wait` дожидает до успешного завершения, а не до `healthy`. Таймаут `--wait-timeout` по умолчанию равен `0` — ожидание без таймаута; в CI-скриптах задавайте его явно, чтобы пайплайн не завис навсегда.

## Практические сценарии

### Предварительные условия

- Docker Engine и Docker Compose v2.20+ или v5.x (`docker compose version`).
- Образы приложения в доступном реестре, пропинкованные тегом или digest — без этого откат невозможен.
- Балансировщик или обратный прокси (Nginx, Traefik) для переключения трафика — обязателен для blue-green, canary и rolling; для recreate не нужен.
- Конфигурация стека в Git — источник правды для воспроизводимого отката.
- `jq` для скриптовых проверок здоровья через `docker compose ps --format json` (фильтр `--filter` у `ps` поддерживает только `status`, см. Устранение неполадок).

### Сценарий 1: Откат на предыдущую версию

```bash
# 1. Зафиксировать текущую конфигурацию в Git, вернуть предыдущую
git checkout <commit-рабочей-версии> -- compose.yml

# 2. Пересоздать стек с предыдущими образами
docker compose pull
docker compose up -d --wait --remove-orphans

# 3. Проверить готовность (ps --filter поддерживает только status; здоровье — через JSON)
docker compose ps --format json | jq -r 'select(.Health == "healthy") | .Service'
```

**Ожидаемый результат:** Стек возвращён к предыдущей версии, все сервисы `healthy`.

**Пининг образов:** для воспроизводимого отката пиньте образы тегом или digest (`image: app@sha256:...`), а не `latest` — иначе `docker compose pull` получит непредсказуемую версию.

### Сценарий 2: Blue-green через два проекта

Общая сеть объявлена как `external`, чтобы оба стека были доступны балансировщику:

```yaml
# compose.yml (общий для blue и green)
name: myapp-green   # или задаётся через -p
services:
  web:
    image: myapp:2.0.0
    networks: [frontend]
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8080/health"]
networks:
  frontend:
    external: true
```

```bash
# 1. Создать shared network (один раз)
docker network create frontend

# 2. Развернуть green параллельно с работающим blue
docker compose -p myapp-green up -d --wait

# 3. Smoke-тест на green (порт опубликован на хосте или доступен через сеть)
docker compose -p myapp-green run --rm test-runner npm test

# 4. Переключить трафик: nginx upstream → green-контейнеры, затем reload
#    (см. docker_compose_advanced_topics.md, Сценарий 5)

# 5. После окна выдержки — вывести blue
docker compose -p myapp-blue down -v
```

**Ожидаемый результат:** Два стека живут параллельно, переключение — операция на балансировщике, откат — обратное переключение за секунды.

**Риск DNS-метода:** при переключении через DNS/A-запись кэш TTL на клиенте может задержать cutover на часы — для compose на одном хосте предпочтительнее балансировщик или upstream.

### Сценарий 3: Canary с автоматическим откатом по SLO

Паттерн из [Глоссария пайплайнов CI/CD](../../CI-CD/Core_Concepts/pipeline_glossary.md): отдельный compose-файл для канарейки и gate по метрикам.

```yaml
# docker-compose.canary.yml
services:
  web:
    image: myapp:2.1.0-canary
    deploy:
      replicas: 1
    labels:
      - "traefik.http.routers.web-canary.rule=Host(`canary.example.com`)"
```

```bash
# 1. Запуск канарейки
docker compose -f docker-compose.canary.yml up -d

# 2. Наблюдение SLO в течение окна (10 мин)
check-slo --window 10m --threshold 99.9

# 3. Автооткат при нарушении SLO
docker compose -f docker-compose.canary.yml down
```

**Ожидаемый результат:** Канарейка получает контролируемую долю трафика; при превышении порогов ошибок — автоматический откат.

**Примечание:** `deploy.replicas` в compose-файле учитывается `docker compose up` и вне Swarm (флаг `--scale` переопределяет его) — число реплик канарейки можно задать прямо в файле.

**Разделение трафика:** веса между версиями задаются на балансировщике — в Traefik через weighted services (см. [Обзор Traefik](../../WebServers/Traefik/traefik_overview.md), раздел «Канареечные релизы»), в Nginx — через `weight` в `upstream`.

### Сценарий 4: Rolling update через масштабирование

```bash
# Поднять 2 новые реплики (Compose v2)
docker compose up -d --scale web=4 --wait

# Дождаться healthy, затем уменьшить до целевого числа
docker compose up -d --scale web=2
```

**Ожидаемый результат:** Новые контейнеры принимают трафик до остановки старых — при условии, что балансировщик опрашивает все контейнеры сервиса.

**Примечание:** `--scale` переопределяет значение `scale`/`deploy.replicas` из compose-файла на время команды.

**Ограничение:** compose не управляет порядком остановки старых реплик при scale-down — используйте `stop_grace_period` для graceful shutdown.

### Сценарий 5: Recreate — обновление с кратковременным простоем

Теория стратегии — в SSoT [Recreate Deployment](../../CI-CD/Deployment_Strategies/recreate_deployment.md); здесь — реализация на compose.

```bash
# 1. Полный recreate: старый стек останавливается и удаляется, затем создаётся новый
docker compose -p myapp down
docker compose -p myapp up -d --wait

# 2. Или пересоздание контейнеров без удаления проекта (тома сохраняются)
docker compose -p myapp up -d --force-recreate --wait
```

**Ожидаемый результат:** Короткое окно недоступности (длительность `down` + запуска), но гарантированно чистая конфигурация — никакого смешения версий.

**Когда выбирать:** некритичные сервисы, миграции схемы БД, требующие эксклюзивного доступа, или когда сложность blue-green не оправдана. `--force-recreate` пересоздаёт контейнеры даже при неизменной конфигурации и образе; `--no-recreate` наоборот, оставляет существующие контейнеры нетронутыми — флаги несовместимы друг с другом.

## Операции и команды

| Команда | Назначение |
| :--- | :--- |
| `docker compose -p <name> up -d --wait` | Запуск именованного проекта с ожиданием `healthy` (`--wait` сам включает detached-режим) |
| `docker compose -p <name> ps --format json \| jq -r 'select(.Health == "healthy") \| .Service'` | Список готовых сервисов (Health Gate); `--filter` у `ps` поддерживает только `status` |
| `docker compose -p <name> run --rm <svc> <cmd>` | Smoke-тест в изоляции проекта |
| `docker compose up -d --scale <svc>=N` | Масштабирование сервиса (rolling-эмуляция); переопределяет `deploy.replicas` из файла |
| `docker compose up -d --force-recreate` / `--no-recreate` | Принудительная пересоздание / запуск без пересоздания контейнеров (recreate-стратегия; флаги несовместимы) |
| `docker compose -p <old> down -v` | Вывод старого стека после soak-окна |
| `docker compose wait <svc>` | Блокировка до остановки контейнеров сервиса (одноразовые сервисы, миграции); не является health-gate |
| `docker compose ls [-a]` | Список compose-проектов на хосте (`-a` — включая остановленные) |

## Устранение неполадок

| Ошибка / Симптом | Причина | Решение |
| :--- | :--- | :--- |
| Конфликт имён контейнеров при двух стеках | Одинаковое имя проекта | Изолируйте проекты через `-p` или `COMPOSE_PROJECT_NAME` |
| `up --wait` таймаут | Сервис не переходит в `healthy` | Проверьте `healthcheck` и `start_period`; увеличьте `--wait-timeout` (по умолчанию `0` — без таймаута, в CI задавайте явно) |
| `unknown filter health` при `ps --filter` | `--filter` у `ps` поддерживает только `status` | Проверяйте здоровье через `ps --format json` + `jq` или используйте `up --wait` |
| `up` пересоздаёт контейнеры без видимых изменений | Реконсиляция v5.2+: изменился config-hash конфигурации или digest образа | Штатное поведение; проверьте diff конфигурации и тег образа |
| Трафик после cutover идёт на старую версию | Балансировщик не перечитал upstream | Проверьте `nginx -s reload` / веса Traefik; кэш DNS при DNS-методе |
| Откат не воспроизводит старое поведение | Образы не пропинкованы (`latest`) | Пиньте теги/digest в compose-файле |
| Порт занят при параллельном запуске | Оба стека публикуют один хост-порт | Публикуйте порты только у активного стека или используйте `expose` + сеть балансировщика |

## Рекомендации

1. **Всегда прогоняйте Health Gate** — `up -d --wait` + smoke-тесты до переключения трафика; это единственная автоматическая проверка готовности в compose.
2. **Изолируйте проекты именем** (`-p`) — это механизм, делающий blue-green и canary возможными на одном хосте.
3. **Пиньте образы** — откат возможен только при воспроизводимых образах.
4. **Держите старый стек «горячим»** до конца soak-окна — мгновенный откат требует работающей предыдущей версии.
5. **Для сложной оркестрации** (автоматический progressive delivery, анализ метрик) используйте Argo Rollouts/Flagger в Kubernetes или CI/CD gate — compose не заменяет контроллер.
6. **Выбирайте recreate осознанно** — это единственная стратегия с гарантированным окном недоступности; все остальные стратегии на compose требуют внешнего балансировщика.

## Дополнительная информация

- **[Blue-Green Deployment](../../CI-CD/Deployment_Strategies/blue_green_deployment.md)** — SSoT: cutover, warm-up, floating VIP, session affinity.
- **[Canary Deployment](../../CI-CD/Deployment_Strategies/canary_deployment.md)** — SSoT: weighted routing, attribute-based routing, auto-rollback.
- **[Rolling Update](../../CI-CD/Deployment_Strategies/rolling_update.md)** — SSoT: постепенная замена инстансов.
- **[Проверки здоровья и откат](../../CI-CD/Deployment_Strategies/deployment_health_checks_and_rollback.md)** — SSoT: health gate и процедуры отката.
- **[Сравнение стратегий](../../CI-CD/Deployment_Strategies/comparison.md)** — выбор стратегии по критериям.
- **[Recreate Deployment](../../CI-CD/Deployment_Strategies/recreate_deployment.md)** — SSoT: стратегия с простоем, команды recreate для compose.
- **[Canary-релиз с автооткатом (пример)](../../CI-CD/Core_Concepts/pipeline_glossary.md)** — compose-файл канарейки и gate по SLO.
- **[Traefik: канареечные релизы](../../WebServers/Traefik/traefik_overview.md)** — разделение трафика весами.
- **[Сценарий 5: валидация перед переключением](./docker_compose_advanced_topics.md)** — smoke-тесты и переключение upstream.
