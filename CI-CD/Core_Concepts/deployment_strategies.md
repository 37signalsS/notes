# Стратегии и модели развертывания

## Определения

- **Модель развертывания (Deployment Model)** — архитектурный подход, определяющий способ доставки изменений в целевую среду. На практике различают Push-модель (CI-центричную) и Pull-модель (GitOps-центричную).
- **Стратегия развертывания (Rollout Strategy)** — технический метод обновления работающего приложения, определяющий порядок замены старой версии (v1) на новую (v2) с целью минимизации рисков и простоя.
- **Развертывание (Deployment) vs Выпуск (Release)** — фундаментальное разделение процессов. **Deployment** — это технический акт установки кода в среду. **Release** — это бизнес-акт открытия доступа пользователям к новому функционалу (часто через Feature Flags).
- **Прогрессивная поставка (Progressive Delivery)** — развитие Continuous Delivery, при котором раскатка функционала происходит постепенно с использованием инструментов управления трафиком и автоматизированного анализа метрик.
- **Автономная (автоматизированная) доставка (Autonomous Delivery)** — уровень зрелости CI/CD, при котором раскатка управляется политиками и метриками: продвижение по этапам Canary и откат инициируются автоматически на основе критериев SLO/Error Budget, без участия человека на рутинных шагах. Критические границы (например, выкатка в продуктив) по-прежнему могут требовать ручного подтверждения.
- **Откат (Rollback)** — процедура возврата работающей версии приложения к предыдущему стабильному состоянию. Бывает явным (переключение трафика/версии) и неявным (автоматический `abort` прогрессивной раскатки).
- **Радиус поражения (Blast Radius)** — объём пользователей и инфраструктуры, на который влияет потенциальная ошибка релиза. Стратегии развертывания призваны минимизировать этот радиус.

## Основные концепции

### Модели развертывания: Push vs Pull

#### Push-модель (CI-ориентированная)
Система сборки (CI) активно инициирует соединение с целевым кластером/сервером для применения изменений.
- **Применение:** Классические среды, автоматизация через **[Ansible](../../Ansible/ansible_introduction.md)**, пайплайны GitLab CI или GitHub Actions.
- **Автоматизация трафика:** В Push-модели пайплайн может императивно управлять весами в Gateway API или Service Mesh через CLI оркестратора (например, `kubectl patch`) для реализации Canary-релизов без внешних операторов. Подробнее: **[Автоматизация трафика в CI](../Deployment_Strategies/canary_deployment.md#автоматизация-трафика-в-ci-пайплайнах-push-метод)**.
- **Безопасность:** Рекомендуется использование **OIDC (OpenID Connect)** для получения временных токенов доступа, что исключает хранение статических секретов в настройках CI. Подробнее: **[Безопасность в CI/CD](../DevSecOps/devsecops_overview.md)**.

#### Pull-модель (GitOps)
Оператор (контроллер) внутри целевой среды (кластера) отслеживает состояние Git-репозитория и самостоятельно синхронизирует фактическое состояние с желаемым.
- **Применение:** Кластеры оркестратора с использованием **[ArgoCD](../../GitOps/ArgoCD/argocd_overview.md)** или **[Flux](../../GitOps/flux.md)**.
- **Преимущества:** Автоматическое исправление дрейфа конфигурации (Self-healing) и отсутствие необходимости открывать API кластера для внешних систем. Подробнее: **[Обзор GitOps](../../GitOps/GitOps_overview.md)**.

### Обзор стратегий развертывания

Выбор стратегии зависит от критичности сервиса, доступных ресурсов и архитектуры приложения.

| Стратегия | Метод раскатки | Простой | Ресурсы | Основная ниша |
| :--- | :--- | :--- | :--- | :--- |
| **Recreate** | Удалить v1 -> Создать v2. | Есть | 1x | Dev-среды, тяжелые миграции БД. |
| **Rolling Update** | Постепенная замена инстансов. | Нет | 1x + surge | Стандартный оркестратор (Deployment). |
| **Blue/Green** | Запуск v2 рядом с v1 (100% switch). | Нет | 2x | Быстрый откат, критичные сервисы. |
| **Canary** | Раскатка на часть трафика (1% -> 100%). | Нет | 1x+ | Проверка гипотез, минимизация рисков. |
| **Shadow (Mirroring)** | Дублирование трафика на v2 без ответа. | Нет | 2x | Тестирование нагрузки на реальном трафике. |

Детальное сравнение всех подходов: **[Сравнение стратегий развертывания](../Deployment_Strategies/comparison.md)**.

### Управление трафиком: Gateway API и Service Mesh

Современная реализация сложных стратегий (Canary, Blue/Green) переместилась с уровня приложения на уровень инфраструктуры:

1.  **Gateway API (стандарт маршрутизации для кластеров оркестратора):** Современный стандарт маршрутизации трафика (L7), позволяющий декларативно описывать веса для Canary-выпусков без использования Service Mesh.
2.  **Service Mesh (Istio, Cilium):** Предоставляет глубокую наблюдаемость и тонкое управление трафиком (маршрутизация по заголовкам, A/B тесты на основе Cookie). Подробнее: **[Управление трафиком в Service Mesh](../../Service_Mesh/traffic_management.md)**.
3.  **Feature Flags:** Позволяют выполнять «темные запуски» (Dark Launches), когда код деплоится в Prod, но активируется только для определенных сегментов пользователей.

### Автоматизированная верификация и откат

Процесс Rollout включает обязательную фазу автоматизированного анализа:
- **Analysis Templates (Argo Rollouts):** Описание критериев успеха (Error Rate, Latency) для каждого шага Canary.
- **Анализ на основе метрик (Metric-driven verification):** Системы мониторинга (на базе SLO/Error Budget и Analysis Templates) анализируют метрики и логи, выявляя деградацию (аномалии Latency/Error Rate), которую могут пропустить простые пороговые алерты.
- **Автономный откат:** Если система фиксирует деградацию по SLO, она немедленно инициирует `abort` раскатки и возвращает трафик на стабильную версию (Auto-Rollback).

### Роли и зоны ответственности

| Аспект | DevOps | SRE | Sysadmin |
| :--- | :--- | :--- | :--- |
| **Модель доставки** | Push-модель, пайплайны GitLab CI/GitHub Actions, OIDC, автоматизация через Ansible | GitOps (ArgoCD/Flux), SLA/SLO/Error Budget, autonomous delivery | Провижининг железа/VM, управление образами (Packer), артефактори (Nexus/Artifactory) |
| **Стратегии раскатки** | Canary/Blue-Green через пайплайн, Feature Flags, автоматический откат | Judge/ Analysis Engine, SLO-гейтинг, burn rate, автономный откат | Rolling Update через Ansible/serial, drain в HAProxy/Nginx, symlink-деплой |
| **Управление трафиком** | Gateway API, Service Mesh (Istio/Cilium), веса в L7-балансировщике | Traffic splitting, circuit breaking, observability трафика | HAProxy/Nginx runtime API, keepalived/VRRP, TCP/UDP балансировка |
| **Наблюдаемость** | Pipeline Observability, DORA-метрики, OpenTelemetry | Golden Signals, Error Budget, SLO-окна, автоматический Judge | node_exporter, journald, syslog, мониторинг железа/сети/БД |
| **Базы данных** | Миграции через CI/CD, Expand-Contract, обратная совместимость | Схемная миграция без даунтайма, репликация, откат без потери данных | Бэкапы, восстановление, репликация (PostgreSQL/MySQL), VACUUM/ANALYZE |
| **Безопасность** | SBOM, подпись артефактов (Cosign), SAST/SCA в пайплайне | Policy-as-Code, гейты безопасности, аудит изменений | Харденинг ОС, firewall, SSH/JIT-доступ, Secure Boot, TPM |

## Практические сценарии

### Выбор стратегии для различных типов приложений

1.  **Stateless API (Высокая нагрузка):**
    - **Рекомендация:** **Canary Deployment** с использованием **Argo Rollouts**.
    - **Почему:** Минимизация «радиуса поражения» (Blast Radius) при ошибках в логике.
2.  **Приложения с миграциями БД (Breaking Changes):**
    - **Рекомендация:** **Blue/Green** совместно с паттерном **Expand and Contract** (двухэтапное изменение схемы БД).
    - **Почему:** Позволяет мгновенно вернуться к старой версии приложения, если миграция прошла успешно, но логика v2 работает некорректно.
3.  **Высоконагруженные системы (Legacy Refactoring):**
    - **Рекомендация:** **Shadow Deployment** (Mirroring).
    - **Почему:** Проверка производительности нового движка на реальном профиле трафика без риска для пользователей.

### Принципы надежного развертывания

- **Zero Downtime Deployment (ZDD):** Достигается правильной настройкой `Readiness` и `Liveness` проб. Подробнее: **[Проверки здоровья и откаты](../Deployment_Strategies/deployment_health_checks_and_rollback.md)**.
- **Иммутабельность:** Запрещено изменять конфигурацию работающих инстансов. Любое изменение — это новая версия артефакта и новый цикл развертывания.
- **Anti-Affinity:** Настройка правил планировщика оркестратора, чтобы поды разных версий (v1 и v2) распределялись по разным узлам кластера для исключения единой точки отказа.

### Практические примеры конфигураций

#### Recreate (простейшая)
Полная остановка старой версии перед запуском новой. Применимо для некритичных и фоновых сервисов, допускающих простой:
```bash
# systemd-юнит или docker compose
docker compose down && docker compose up -d app
# → app restarted (новый контейнер поднят, старый остановлен)
```

#### Rolling Update (через обратный прокси)
Постепенная замена инстансов при наличии healthcheck; балансировщик (nginx/Traefik/HAProxy) отправляет трафик только на здоровые:
```yaml
# docker-compose.override.yml (фрагмент)
services:
  app:
    image: registry.internal/app:${TAG}
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8080/healthz"]
      interval: 10s
      retries: 5
```
Новые инстансы добавляются в пул только после прохождения `healthz`, старые выводятся из пула (connection draining) перед остановкой.

#### Blue/Green (переключение весов)
Две идентичные среды за общим балансировщиком; переключение — атомарная смена upstream:
```nginx
# Конфигурация upstream (nginx)
upstream app {
  server 10.0.0.11:8080;   # Blue (v1)
  # server 10.0.0.12:8080; # Green (v2) — активируется при выкатке
}
```
После проверки Green трафик перенаправляется на него; при аномалиях — мгновенный возврат на Blue. Требует **2x ресурсов** (SysAdmin-планирование ёмкости).

#### Canary (через Argo Rollouts + анализ метрик)
Пример автоматизированной прогрессивной раскатки с метрикой Error Rate из Prometheus:
```yaml
apiVersion: argoproj.io/v1alpha1
kind: Rollout
metadata:
  name: app
spec:
  replicas: 10
  strategy:
    canary:
      steps:
        - setWeight: 10
        - analysis:
            templates: [ { templateName: error-rate } ]
        - setWeight: 50
        - pause: { duration: 5m }
      analysisTemplates:
        - name: error-rate
          spec:
            metrics:
              - name: error-rate
                successCondition: result < 0.01
                provider:
                  prometheus:
                    query: >-
                      sum(rate(http_requests_total{status=~"5.."}[5m]))
                      / sum(rate(http_requests_total[5m]))
```
При превышении порога ошибок раскатка автоматически прерывается и трафик возвращается на стабильную версию. Подробнее: **[Канареечное развертывание](../Deployment_Strategies/canary_deployment.md)**.

#### Shadow / Mirroring (Service Mesh)
Дублирование живого трафика на теневую версию без отправки ей ответа клиенту (Envoy/Istio `mirror`):
```yaml
# VirtualService (фрагмент)
http:
  - route:
      - destination: { host: app-v1 }
    mirror:
      host: app-v2   # копия трафика для нагрузочного теста
    mirrorPercentage: { value: 100 }
```

### Миграции баз данных: паттерн Expand/Contract

Для Breaking Changes схемы применяется двухэтапный паттерн, исключающий простой:

1.  **Expand:** Добавить новую колонку/таблицу (аддитивно, обратно совместимо). Старая и новая версии приложения работают с расширенной схемой.
2.  **Dual-write / Backfill:** Приложение v1 и v2 пишут в обе структуры; выполняется фоновая миграция исторических данных.
3.  **Switch reads:** Переключение чтения на новую структуру (через Feature Flag).
4.  **Contract:** Удаление старой колонки/таблицы после подтверждения стабильности v2.

Этот паттерн критичен при **Blue/Green** и **Canary**, чтобы старая версия не падала от несовместимой схемы.

### SysAdmin-чеклист надежного развертывания (runbook)

- **Ёмкость:** резервирование ресурсов под Blue/Green (2x) или surge при Rolling.
- **Graceful shutdown:** корректное завершение соединений (SIGTERM + `preStop`/connection draining).
- **Health-эндпоинты:** `/healthz` (Liveness) и `/readyz` (Readiness) реально проверяют зависимости (БД, кэш).
- **План отката:** заранее подготовленная процедура (переключение веса / тег образа / `kubectl rollout undo`).
- **Мониторинг:** дашборды Error Rate / Latency / Saturation и алерты по SLO на время окна раскатки.
- **Коммуникация:** уведомление дежурной смены (on-call) и канал статуса перед прод-выкаткой.

### SRE-метрики и наблюдаемость развертывания

- **Что мониторить в окне раскатки:** Error Rate, p95/p99 Latency, Saturation (CPU/память/очереди), трафик.
- **SLO / Error Budget:** раскатка считается успешной, если за окно наблюдения не исчерпан Error Budget; иначе — автооткат.
- **MTTR:** короткие обратимые деплои и готовый план отката снижают время восстановления.
- **Связь со стратегией:** Canary сужает радиус поражения и улучшает DORA-метрики (Change Failure Rate, Time to Restore). См. **[Метрики DORA](./dora_metrics.md)**, **[Концепции SRE](../../Concepts/sre_concepts_main.md)**, **[Наблюдаемость пайплайнов](./pipeline_observability.md)**.

## Операции и команды

### Kubernetes — управление стратегией Rolling Update

```bash
# Просмотр текущей стратегии Deployment
kubectl get deployment myapp -o jsonpath='{.spec.strategy.type}{.spec.strategy.rollingUpdate}'
# → RollingUpdate{"maxSurge":"25%","maxUnavailable":"25%"}

# Принудительный откат к предыдущей ревизии (kubectl rollback)
kubectl rollout undo deployment/myapp
# → deployment.apps/myapp rolled back

# Пауза раскатки для ручной валидации (Pause)
kubectl rollout pause deployment/myapp
# → deployment.apps/myapp paused

# Возобновление после паузы (Resume)
kubectl rollout resume deployment/myapp
# → deployment.apps/myapp resumed

# Мониторинг статуса раскатки в реальном времени
kubectl rollout status deployment/myapp --timeout=10m
# → deployment "myapp" successfully rolled out
```

### HAProxy — оперативное управление пулом при Rolling Update

```bash
# Просмотр состояния серверов
echo "show stat" | socat /var/run/haproxy.sock stdio | grep app_servers
# → app1,FRONTEND,...,UP,...
# → app2,FRONTEND,...,UP,...

# Вывод узла в drain (остановка приема новых соединений)
echo "set server app_servers/app1 state drain" | socat /var/run/haproxy.sock stdio
# → (пустой вывод, статус меняется на DRY)

# Проверка, что узел закончил обработку текущих запросов
echo "show stat" | socat /var/run/haproxy.sock stdio | grep app1
# → status=DRY (drain mode, graceful shutdown завершен)

# Полное отключение узла (MAINT)
echo "set server app_servers/app1 state maint" | socat /var/run/haproxy.sock stdio
# → node выведен из пула полностью

# Возврат узла в пул
echo "set server app_servers/app1 state ready" | socat /var/run/haproxy.sock stdio
# → status=UP

# Перезагрузка конфигурации без потери соединений
systemctl reload haproxy
# → (служебный вывод systemd)
```

### Nginx — оперативное управление весами (Blue-Green / Canary)

```bash
# Проверка конфигурации
nginx -t
# → nginx: the configuration file /etc/nginx/nginx.conf syntax is ok
# → nginx: configuration file /etc/nginx/nginx.conf test is successful

# Применение изменений (перезагрузка без потерь)
systemctl reload nginx
# → (служебный вывод systemd)

# Принудительная перезагрузка (разрывает существующие соединения)
systemctl restart nginx

# Просмотр upstream и активных соединений
curl http://localhost/status  # (если включен stub_status)
# → Active connections: 42
# → server accepts handled requests: 12345 12345 56789
```

### Ansible — паттерн Rolling Update с автооткатом

```bash
# Rolling Update с ограничением на 1 узел и автоматическим откатом при ошибке
ansible-playbook deploy.yml \
  --limit "tag_env_production:&tag_role_app" \
  --serial 1 \
  --forks 2 \
  --extra-vars "app_version=2.3.1 max_fail_percentage=0"
# → Если узел падает, playbook останавливается, остальные не трогаются.

# Проверка конфигурации перед применением (dry-run)
ansible-playbook deploy.yml --check --diff
# → changed=0, unreachable=0, failed=0 (проверка пройдена)
```

### systemd — атомарная смена версии и управление ресурсами

```bash
# Проверка статуса сервиса
systemctl status myapp
# → Active: active (running) since ...

# Смена версии через symlink (immutable artifacts)
ln -sfn /opt/app/2.3.1 /opt/app/current
systemctl restart myapp

# Живое изменение лимита ресурсов (аналог In-Place Resize)
systemctl set-property myapp.service MemoryMax=2G CPUQuota=150%
# → применяется мгновенно, без рестарта

# Просмотр примененных лимитов
systemctl show myapp.service | grep -E 'MemoryMax|CPUQuota'
# → MemoryMax=2G
# → CPUQuota=150%

# Быстрый откат
ln -sfn /opt/app/2.3.0 /opt/app/current
systemctl restart myapp
```

### Управление весами Canary через HAProxy runtime API

```bash
# Поэтапный сдвиг веса Canary (5% → 10% → 25% → 50% → 100%)
for w in 5 10 25 50 100; do
  echo "set server app_servers/stable1 weight $((100-w))" | socat - UNIX-CONNECT:/var/run/haproxy.sock
  echo "set server app_servers/stable2 weight $((100-w))" | socat - UNIX-CONNECT:/var/run/haproxy.sock
  echo "set server app_canary/canary1 weight $w"          | socat - UNIX-CONNECT:/var/run/haproxy.sock
  sleep 60   # окно наблюдения за Golden Signals
done

# Валидация
echo "show stat" | socat - UNIX-CONNECT:/var/run/haproxy.sock | grep -E "app_servers|app_canary"
# → status=UP, колонка weight отражает текущие значения
```

### Верификация Expand/Contract миграции

```bash
# Проверка, что обе версии приложения работают с расширенной схемой
psql -c "SELECT column_name FROM information_schema.columns WHERE table_name='orders' AND column_name='total_net';"
# → total_net (колонка присутствует, обе версии видят её)

# После отката и Contract: убедиться, что старая колонка удалена
psql -c "SELECT column_name FROM information_schema.columns WHERE table_name='orders' AND column_name='total';"
# → (0 rows, старая колонка удалена)
```

## Типичные ошибки и решения

| Симптом | Причина | Решение | Роль |
| :--- | :--- | :--- | :--- |
| **Node OOM во время Rollout** | Слишком большой `maxSurge`. | Уменьшить `maxSurge` или добавить узлы в кластер. | Sysadmin / DevOps |
| **Canary Analysis Timeout** | Недостаточно трафика для сбора статистики. | Увеличить время анализа или долю Canary. | SRE / DevOps |
| **Stuck in Pending** | Нехватка ресурсов (CPU/RAM/PVC) для новых подов. | Проверить `kubectl describe pod` и квоты в Namespace. | Sysadmin / DevOps |
| **Sticky Session Break** | Неверная настройка балансировщика при Canary. | Использовать `Cookie-based affinity` в Gateway API / Service Mesh. | DevOps / SRE |
| **Shadow Side Effects** | Зеркальный трафик вызвал запись в Prod БД. | Использовать Mock-сервисы или Read-only режим для Shadow. | DevOps / SRE |
| **VIP не мигрирует (keepalived)** | Firewall блокирует VRRP (протокол 112) или равный priority. | Разрешить `proto 112` между узлами; задать разный `priority`. | Sysadmin |
| **Nginx upstream «flapping»** | Слишком агрессивные `inter`/`fall` или нестабильный health-эндпоинт. | Увеличить `rise`/`fall` до 2–3; проверить, что `/healthz` не ложноположителен. | Sysadmin / DevOps |
| **Canary не получает трафик (Nginx)** | `split_clients` привязан к `$remote_addr` за NAT → все на stable. | Использовать `$request_id` для случайной раскатки или ACL по заголовку. | DevOps |
| **DNS TTL ломает Zero-Downtime** | Клиенты кэшируют старый IP при DNS-switch. | Использовать L7-веса/VRRP вместо DNS; снизить TTL только как крайняя мера. | Sysadmin |
| **Clock Drift** | Уплывание времени на VM ломает TLS/лидерство. | `chrony` с несколькими stratum-1/PTP источниками; `chronyc tracking`. | Sysadmin |
| **Config Drift (Bare Metal)** | Сервер «накопил» ручные изменения. | Ежедневный `ansible-playbook --check --diff`; переход на Immutable Images. | Sysadmin / DevOps |
| **Readiness Probe «проваливается» на холодном старте** | Приложение еще не прогрелось (JIT, подключение к БД), а LB уже слает трафик. | Увеличить `initialDelaySeconds` и `failureThreshold` в readiness probe; добавить прогревочный эндпоинт (`/readyz` отдельно от `/healthz`). | DevOps / SRE |
| **Rollback оставляет артефакт на диске** | При Recreate/Rolling старая версия не удаляется из `/opt/app/<version>`. | Добавить post-rollback cleanup hook в CI (удаление версий старше N последних). | DevOps |
| **Canary «съедает» Error Budget за секунды** | Дефект в v2 проявляется сразу, burn rate превышает порог, но раскатка продолжается из-за слишком длинного окна анализа. | Уменьшить окно анализа (5m → 1m) и добавить Fail-Closed: при недоступности метрик — остановка, а не продолжение. | SRE |
| **Graceful Shutdown не работает** | Приложение не перехватывает `SIGTERM` или ждет слишком долого (`TimeoutStopSec=30` мало). | Добавить явный обработчик сигнала в код; увеличить `TimeoutStopSec` до 60–120 с; проверить `KillSignal=SIGTERM` в systemd-юните. | DevOps / Sysadmin |
| **Connection Draining зависает** | Некоторые балансировщики (старая версия HAProxy) не ждут завершения long-polling/WebSocket. | Переключиться на HTTP/2 или TCP-drain с увеличенным `timeout`; отключить sticky для drain-периода. | Sysadmin |
| **Старая версия не удаляется из LB после Rolling** | Узел остался в состоянии `UP`, но должен быть в `drain`/`maint`. | Проверить, что health-check возвращает `503` или статус сменен через `socat`; убедиться, что `httpchk` проверяет реальный эндпоинт приложения. | Sysadmin |
| **Recreate падает с ошибкой «address already in use»** | Старый процесс не успел освободить порт за `TimeoutStopSec`. | Увеличить `TimeoutStopSec` или использовать `ExecStopPost` с проверкой `ss -tlnp`; перейти на `Type=notify` или `Type=exec` для точного контроля. | Sysadmin / DevOps |
| **Атомарный symlink не атомарен на NFS** | `ln -sfn` на сетевой файловой системе не является атомарной операцией, возможна гонка. | Перенести артефакты на локальный диск или использовать lock-файл (`flock`) вокруг смены symlink. | Sysadmin |

## Лучшие практики

### Архитектура и проектирование

1. **Одна стратегия на сервис:** Не смешивайте Blue/Green и Canary в одном пайплайне без явной необходимости. Каждая стратегия имеет свою модель риска и стоимость.
2. **Separation of Concerns:** Разделите три оси — доставку артефакта, управление трафиком и валидацию. Связка `CI → артефактори → реестр` не должна жестко зависеть от `балансировщик → веса`.
3. **Иммутабельность артефактов:** Никогда не используйте тег `:latest`. Обновление должно инициироваться сменой конкретной версии образа или хеша конфигурации.
4. **Expand and Contract:** При обновлении работают две версии приложения. База данных должна поддерживать обе схемы одновременно. Подробнее: **[Expand-Contract](../../Databases/Concepts/migrations/expand_contract.md)**.
5. **Feature Flags отдельно от стратегии:** Canary управляет *трафиком между версиями*, флаг — *видимостью функции внутри одной версии*. Разные оси риска.

### Надёжность и безопасность

6. **Health-эндпоинт проверяет зависимости**, а не только `200 OK`. Иначе балансировщик пустит трафик в «живой, но мертвый» экземпляр.
7. **Graceful shutdown обязателен** для Rolling/Canary — иначе активные запросы получат 502 при выводе узла из пула.
8. **Автоматический откат (Auto-Rollback):** Judge должен не только блокировать продвижение, но и инициировать откат при превышении порога ошибок. В on-prem — шаг в Ansible/CI, в K8s — Argo Rollouts/Flagger.
9. **Fail-Closed:** при недоступности мониторинга или ошибке «судьи» раскатка останавливается, а не продолжается автоматически.
10. **OIDC-First:** отказ от статических секретов в CI/CD в пользу временных токенов (OIDC, Vault dynamic secrets).

### Производительность и наблюдаемость

11. **Wave-подход (Progressifve Rolling):** Делите узлы на волны (10% → 25% → 50% → 100%) с паузой и проверкой Golden Signals между ними. Это превращает Rolling в Progressive Delivery даже без Kubernetes.
12. **Golden Signals в окне раскатки:** После каждой волны фиксируются Error Rate, P95 Latency и Saturation. Продолжение раскатки допустимо, только если Error Budget не исчерпан.
13. **MTTR через короткие обратимые шаги:** Короткие обратимые деплои и готовый план отката (смена симлинка / тег образа / `kubectl rollout undo` / возврат узла в пул) снижают время восстановления.
14. **Связь с DORA:** Rolling с health-проверками и автооткатом улучшает Change Failure Rate и Time to Restore. См. **[Метрики DORA](./dora_metrics.md)**.

### Организация процессов

15. **Runbook на каждый откат** — оператор должен за ≤5 минут выполнить откат по письменной инструкции, без разбора причин в моменте.
16. **Postmortem после каждого failed release** — без поиска виноватого, с action-items по предотвращению рецидива.
17. **Capacity planning:** Blue/Green и Shadow требуют 2x ресурсов; планируйте квоты/серверы заранее. Для Rolling убедитесь в наличии N+1 узла для surge.
18. **Ежедневный `ansible-playbook --check --diff`** для Bare Metal/VM — предотвращает Config Drift, который делает откат ненадежным.
19. **Атомарность операций:** L7-веса (HAProxy runtime API), симлинки (`ln -sfn`), VIP (VRRP) — все эти примитивы должны быть атомарными и проверяемыми.
20. **Синтетический трафик при низкой нагрузке:** ночью/в выходные анализ недостоверен без генератора нагрузки для поддержания Baseline.

## Дополнительная информация

- **[Сравнение стратегий развертывания](../Deployment_Strategies/comparison.md)** — детальная матрица выбора, архитектура трафика, техническое обоснование.
- **[Rolling Update — поэтапное обновление](../Deployment_Strategies/rolling_update.md)** — параметры, StatefulSet, systemd, Ansible, rsync.
- **[Канареечное развертывание](../Deployment_Strategies/canary_deployment.md)** — Nginx/HAProxy/Traefik, Argo Rollouts, CI-автоматизация.
- **[Сине-зеленое развертывание](../Deployment_Strategies/blue_green_deployment.md)** — keepalived/VRRP, Gateway API, Docker Compose.
- **[Теневое развертывание](../Deployment_Strategies/shadow_deployment.md)** — GoReplay, Envoy, Nginx mirror, eBPF/tc mirred.
- **[Проверки здоровья и откат](../Deployment_Strategies/deployment_health_checks_and_rollback.md)** — пробы, архитектура отката, артефакты RCA.
- **[Развертывание в традиционной инфраструктуре](../Deployment_Strategies/traditional_infrastructure.md)** — Bare Metal/VM, ZTP, Packer, Ansible, Immutable Infrastructure.
- **[Метрики DORA](./dora_metrics.md)** — измерение эффективности процессов поставки.
- **[Концепции SRE](../../Concepts/sre_concepts_main.md)** — обеспечение надежности эксплуатации.
- **[Наблюдаемость пайплайнов](./pipeline_observability.md)** — метрики для решений о breaker.
- **[Оптимизация затрат в CI/CD](./cost-optimization.md)** — управление стоимостью инфраструктуры при раскатке.
- **[Expand-Contract](../../Databases/Concepts/migrations/expand_contract.md)** — обратно-совместимые миграции баз данных.

### GitHub Actions: конкретная реализация стратегий развертывания

Для GitHub Actions развертывание реализуется через `environment` с защитными правилами и job'ы, управляемые триггерами.

**Environment protection rules:**
- **`environment: production`** — именованная среда с настройками защиты.
- **`deployment_branch_policy`** — ограничение веток, которые могут деплоить в environment.
- **`deployment_review`** — требование approval перед деплоем (для production).
- **Секреты и переменные environment'ов** — изолированы от других сред.

**Пример: Canary через GitHub Actions + HAProxy runtime API:**
```yaml
# .github/workflows/deploy-canary.yml
name: Deploy Canary
on:
  workflow_dispatch:
    inputs:
      canary_weight:
        description: 'Canary weight (%)'
        required: true
        default: 10
        type: number

jobs:
  canary:
    runs-on: self-hosted
    environment: production
    steps:
      - name: Set canary weight
        run: |
          echo "set server app_servers/stable1 weight $((100-${{ inputs.canary_weight }}))" \
            | socat - UNIX-CONNECT:/var/run/haproxy.sock
          echo "set server app_servers/canary1 weight ${{ inputs.canary_weight }}" \
            | socat - UNIX-CONNECT:/var/run/haproxy.sock
      - name: Wait for observation window
        run: sleep 300   # 5 мин окна наблюдения
      - name: Check SLO
        run: |
          ERROR_RATE=$(curl -s "http://prometheus.internal:9090/api/v1/query" \
            --data-urlencode 'query=sum(rate(http_errors_total[5m])) / sum(rate(http_requests_total[5m]))' \
            | jq -r '.data.result[0].value[1]')
          if (( $(echo "$ERROR_RATE > 0.02" | bc -l) )); then
            echo "::error::Error rate $ERROR_RATE exceeds SLO. Aborting..."
            exit 1
          fi
```

**Пример: Blue/Green через переключение environment'ов:**
```yaml
# .github/workflows/deploy-blue-green.yml
name: Deploy Blue-Green
on:
  push:
    tags: ['v*']

jobs:
  deploy-green:
    runs-on: self-hosted
    environment: green   # активная среда — blue, неактивная — green
    steps:
      - name: Deploy to Green
        run: ./deploy.sh green ${{ github.ref_name }}
      - name: Health check
        run: curl -fsS https://green.internal/healthz
      - name: Switch traffic (manual approval)
        if: success
        uses: appleboy/ssh-action@v1.0.0
        with:
          host: lb.internal
          script: |
            echo "set server app_servers/blue weight 0" | socat - UNIX-CONNECT:/var/run/haproxy.sock
            echo "set server app_servers/green weight 100" | socat - UNIX-CONNECT:/var/run/haproxy.sock
```

**Пример: Rollback через workflow_dispatch:**
```yaml
# .github/workflows/rollback.yml
name: Rollback
on:
  workflow_dispatch:
    inputs:
      target_version:
        description: 'Версия для отката'
        required: true
        type: string

jobs:
  rollback:
    runs-on: self-hosted
    environment: production
    steps:
      - name: Execute rollback
        run: |
          echo "Rolling back to ${{ inputs.target_version }}"
          ./rollback.sh ${{ inputs.target_version }}
      - name: Verify rollback
        run: |
          curl -fsS https://app.internal/healthz
          echo "Rollback verified"
```

**Особенности GitHub Actions для deployment:**
- **`GITHUB_TOKEN` с `permissions: contents: write`** — нужен для обновления манифестов в GitOps-репозитории.
- **`id-token: write`** — необходим для OIDC-аутентификации в облаке (AWS, GCP, Azure) без статических секретов.
- **`environment` approval** — добавляет время в Lead Time, но является критической защитой для production.
- **`concurrency` с `cancel-in-progress`** — предотвращает одновременные деплои одной среды.
- **Self-hosted runner'ы** — требуются для доступа к внутренним сетям, которые недоступны из GitHub-hosted runner'ов.
- **[Capacity Planning для CI/CD](./capacity_planning.md)** — расчёт мощностей раннеров, реестров и CI-серверов.
- **[Балансировка нагрузки HTTP](../../Networking/Protocols/HTTP/http_load_balancing.md)** — механика весов, health checks и traffic splitting на Nginx/HAProxy.
