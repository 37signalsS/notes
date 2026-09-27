# Сине-зеленое развертывание (Blue-Green Deployment)

## Определения

**Сине-зеленое развертывание (Blue-Green Deployment)** — стратегия выпуска, при которой поддерживаются две идентичные и полностью функциональные среды: активная (**Blue**), обслуживающая текущих пользователей, и пассивная (**Green**), принимающая новую версию. После успешной валидации новой версии весь трафик мгновенно переключается с Blue на Green.

- **Zero Downtime (Нулевой простой)** — ключевая цель, достигаемая за счет мгновенного переключения маршрута трафика между полностью готовыми средами.
- **Cutover (Переключение)** — атомарный акт изменения конфигурации сетевого слоя, направляющий поток запросов с Blue на Green.
- **Warm-up (Прогрев)** — процесс подготовки Green-среды (заполнение кэшей, инициализация пулов соединений, JIT-компиляция) перед приемом продуктивной нагрузки.
- **Environment Parity (Паритет сред)** — принцип идентичности аппаратных и программных ресурсов обеих сред для исключения инфраструктурного дрифта.
- **Blast Radius (Радиус поражения)** — в данной стратегии составляет 100%, так как переключение происходит для всех пользователей одновременно.
- **Floating VIP (Плавающий IP)** — единая точка входа (виртуальный IP-адрес), которая в каждый момент времени принадлежит только активной среде; перемещение VIP между фермами и есть акт Cutover в on-prem.
- **Health Gate (Ворота здоровья)** — этап автоматической или ручной проверки готовности Green (smoke/integration/анализ метрик) *до* переключения трафика; аналог pre-promotion analysis в Argo Rollouts.
- **Decommissioning (Вывод из эксплуатации)** — остановка старой среды после подтверждения стабильности новой; до этого момента Blue остается «горячим» резервом для мгновенного отката.
- **Rollback (Откат)** — возврат трафика на предыдущую стабильную версию при обнаружении дефектов в Green.
- **Soak Window (Окно выдержки)** — период наблюдения за Green после Cutover, в течение которого принимается решение о decommissioning Blue.
- **Session Affinity (Привязка сессии)** — механизм балансировщика, направляющий повторные запросы одного клиента на тот же инстанс; при Blue-Green может привести к отправке пользователя на старую среду после переключения.

## Основные концепции

### Ключевые идеи

- **Идентичные среды** — поддерживаются две полностью одинаковые инфраструктуры: Blue (стабильная) и Green (новая). В любой момент времени «живой» является только одна из них.
- **Мгновенный откат (Rollback)** — если в Green-версии обнаружена ошибка, трафик мгновенно возвращается на Blue-среду, которая оставалась активной и прогретой.
- **Тестирование в производственных условиях** — Green-среда является зеркалом продакшена, что позволяет проводить финальные Smoke-тесты на реальных конфигурациях и реальных данных (read-only доступ к БД).

### Жизненный цикл релиза

1.  **Подготовка (Standby):** Развертывание новой версии в пассивной среде (Green) параллельно с работающей Blue.
2.  **Верификация (Smoke Testing):** Выполнение тестов здоровья и интеграционных тестов в среде Green (Health Gate).
3.  **Прогрев (Warm-up):** Инициализация пулов соединений, кэшей, JIT; прогон «искусственного» трафика, чтобы исключить холодный старт после Cutover.
4.  **Переключение (Cutover):** Атомарная перенастройка сетевого слоя (вес в балансировщике, VIP, selector) — направление 100% трафика на Green.
5.  **Наблюдение (Post-deployment Monitoring):** Мониторинг бизнес-метрик и технических сигналов (Golden Signals) в течение периода «просадки» (soak).
6.  **Завершение (Decommissioning):** После подтверждения стабильности Blue-среда останавливается или становится резервной (роли сред меняются местами к следующему релизу).

### Методы переключения трафика

| Метод | Механизм | Особенности и риски |
| :--- | :--- | :--- |
| **Балансировщик (L7/L4)** | Изменение целевой группы (Target Group) или веса сервера. | Самый быстрый и надежный способ; не требует простоя. |
| **Service Mesh (Istio / Linkerd)** | Изменение весов (0/100) в VirtualService или Gateway API. | Позволяет управлять трафиком на уровне микросервисов; поддержка Ambient-режима (без sidecar). |
| **DNS** | Изменение CNAME или A-записи. | **Риск TTL:** кэширование на стороне клиента может задержать переключение на часы. |
| **Kubernetes Service** | Смена селектора (Selector) в объекте Service. | Просто в реализации. **Риск потери сессий:** возможен обрыв соединений. |
| **Gateway API** | Обновление `backendRefs` в `HTTPRoute`. | Стандартный подход (абстракция от конкретного Ingress-контроллера). |
| **VRRP / Floating VIP (keepalived)** | Перенос виртуального IP между фермами через VRRP. | Переключение за доли секунды; классический on-prem подход, требует выделенного VIP и кворума. |
| **HAProxy (runtime API)** | `enable`/`disable server` через Unix-сокет управления. | Мгновенный вывод/ввод узла без перезагрузки балансировщика. |
| **systemd + symlink** | Атомарная смена символической ссылки на релиз + рестарт юнита. | Для монолитов без балансировщика; откат — просто переставка symlink. |

> Глубокое сравнение стратегий и канонические примеры переключения на уровне сети — в **[сравнении стратегий развертывания](./comparison.md)**. Механику балансировщика для Blue/Green см. в **[балансировке нагрузки HTTP](../../Networking/Protocols/HTTP/http_load_balancing.md)**.

### Способы изоляции сред

От того, насколько изолированы среды, зависят скорость отката и стоимость:

- **Полная изоляция (две фермы):** Blue и Green — разные пулы серверов за общим VIP/балансировщиком. Откат = мгновенный возврат VIP/веса, но требует 2x железа.
- **Общий балансировщик, разные бэкенды:** обе версии в одном upstream с весами (Nginx `weight`, HAProxy `enable/disable`). Дешевле, но обе версии видят один L7.
- **Один хост, symlink (для монолитов/статики):** `current -> release_vX`; переключение — атомарная смена ссылки + рестарт/релоад. Нулевая избыточность инфраструктуры, но простейший откат.

### Тепловой прогрев и Health Gate

Cutover не должен происходить «вслепую». Перед ним Green обязана пройти:

1.  **Локальные пробы** (`readinessProbe`, HAProxy `httpchk`, nginx `health_check`): приложение отвечает 200 на `/healthz`.
2.  **Прогрев ресурсов:** заполнение пула соединений к БД, прогрев кэшей (Redis/Memcached), JIT для JVM, разогрев thread-pool.
3.  **Интеграционные smoke-тесты извне:** реальные запросы к Green через preview-эндпоинт (Argo Rollouts `previewService`, отдельный `Host`/заголовок).
4.  **Анализ метрик (Judge):** сравнение latency/error-rate Green с базовой линией Blue. Механизмы автоматизации — в **[проверках здоровья и откате](./deployment_health_checks_and_rollback.md)**.

Без прогрева даже корректная версия выдаст всплеск 5xx сразу после Cutover (cold start), что ложно сработает как «ошибка релиза».

## Практические сценарии

### 1. Нативная реализация в Kubernetes (Label Switching)

В стандартном Kubernetes Blue-Green реализуется через создание двух Deployment и одного Service.

**Настройка Service:**
```yaml
apiVersion: v1
kind: Service
metadata:
  name: my-app-service
spec:
  selector:
    app: my-app
    version: blue # Переключатель: меняем на green после проверки
  ports:
    - port: 80
      targetPort: 8080
```

**Алгоритм переключения:**
```bash
# Развертывание green версии (app-green.yaml)
kubectl apply -f deployment-green.yaml
# После успешных тестов через preview-сервис:
kubectl patch service my-app-service -p '{"spec":{"selector":{"version":"green"}}}'
```

### 2. Реализация через Argo Rollouts

Argo Rollouts автоматизирует процесс, предоставляя объект `Rollout`.

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Rollout
metadata:
  name: my-app
spec:
  replicas: 4
  strategy:
    blueGreen:
      activeService: my-app-active    # Продакшн сервис
      previewService: my-app-preview  # Сервис для тестов
      autoPromotionEnabled: false     # Ручное подтверждение или Analysis
      prePromotionAnalysis:
        templates:
        - templateName: smoke-tests
```

### 3. Kubernetes Gateway API

Использование `HTTPRoute` для атомарного переключения на уровне инфраструктуры.

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: shop-route
spec:
  parentRefs: [{name: main-gateway}]
  rules:
  - backendRefs:
    - {name: app-v1-blue, port: 8080, weight: 0}
    - {name: app-v2-green, port: 8080, weight: 100}
```

### 4. Работа с базой данных: Паттерн Expand-Contract

Совместимость схемы БД — критический фактор. Деструктивная миграция в Green сломает Blue и сделает откат невозможным.

**Решение:**
1. Использование **[Expand-Contract](../../Databases/Concepts/migrations/expand_contract.md)** для обеспечения обратной совместимости.
2. Применение **[архитектурных сценариев миграции](../../Databases/Concepts/migrations/scenarios.md#практические-сценарии-архитектурные-переходы)** (Сценарий 6: Blue-Green Deployment базы данных — логическая репликация новой версии СУБД) для минимизации простоя при значительных изменениях.

### 5. Управление состоянием (Session Stickiness)

- **Проблема:** При атомарном переключении сессии в памяти приложения (In-memory) будут потеряны.
- **Решение:**
    - Вынос состояния во внешние хранилища (**Redis**, **Memcached**).
    - Использование **Sticky Sessions** на балансировщике (с учетом, что это может замедлить переход всех пользователей на новую версию).

### 6. Blue-Green через keepalived (VRRP + Floating VIP) — Bare Metal

Классический on-prem вариант: две фермы (Blue и Green) за одним плавающим VIP. Активная ферма владеет VIP благодаря более высокому приоритету VRRP. Cutover — это повышение приоритета на Green (или понижение на Blue), после чего VIP мигрирует за доли секунды.

**Конфигурация на узлах Blue (`/etc/keepalived/keepalived.conf`):**
```conf
vrrp_instance VI_1 {
    state BACKUP                 # оба в BACKUP — выбор по priority
    interface eth0
    virtual_router_id 51
    priority 150                 # Blue владеет VIP (выше Green)
    advert_int 1
    virtual_ipaddress {
        10.0.1.100/24            # Floating VIP (точка входа фронта)
    }
}
```

**Конфигурация на узлах Green (зеркальная, но с меньшим приоритетом):**
```conf
vrrp_instance VI_1 {
    state BACKUP
    interface eth0
    virtual_router_id 51
    priority 100                 # ниже Blue => VIP сейчас у Blue
    advert_int 1
    virtual_ipaddress {
        10.0.1.100/24
    }
}
```

**Cutover (мгновенный switch):**
```bash
# На Green поднимаем приоритет выше Blue
sed -i 's/priority 100/priority 200/' /etc/keepalived/keepalived.conf
systemctl reload keepalived
# → через ~1с VIP 10.0.1.100 переезжает на Green (VRRP transition)
```

**Валидация:**
```bash
# На узле Green (после switch):
ip addr show eth0 | grep -q 10.0.1.100 && echo "VIP на Green"
journalctl -u keepalived -n 20 | grep -i "ENTERING MASTER"
# Откат: вернуть priority 100 на Green и 150 на Blue, reload.
```

> Нюанс: VRRP переносит только IP, не соединения. In-flight TCP/WebSocket к старой среде разорвутся — для долгих соединений нужен connection draining на уровне приложения/балансировщика или кратковременный сброс принимается как допустимый.

### 7. Blue-Green через HAProxy (runtime API)

Переключение без перезагрузки балансировщика — через Unix-сокет управления. Серверы обеих версий уже в пуле; Green изначально `disabled`.

**`haproxy.cfg`:**
```haproxy
backend app
    balance roundrobin
    option httpchk GET /healthz
    http-check expect status 200
    server blue   10.0.1.10:8080 check
    server green  10.0.1.20:8080 check disabled   # выведен из пула
```

**Cutover (миллисекунды, без reload):**
```bash
SOCK=/var/run/haproxy.sock
echo "enable server app/green"  | socat stdio $SOCK   # Green принимает трафик
echo "disable server app/blue"  | socat stdio $SOCK   # Blue выведен
# Откат — обратные команды.
```

**Валидация:**
```bash
echo "show servers state app" | socat stdio $SOCK
# → app blue 10.0.1.10:8080 DOWN ... ; app green 10.0.1.20:8080 UP ...
```

> Детали health-чеков и балансировки — в **[балансировке нагрузки HTTP](../../Networking/Protocols/HTTP/http_load_balancing.md)**.

### 8. Blue-Green через Nginx (операционный аспект)

Каноническая конфигурация — две версии в одном upstream с весами `weight=0/1` — описана в **[сравнении стратегий](./comparison.md)** (раздел «Blue-Green через смену весов в Nginx»). Здесь — операционная сторона переключения и его автоматизация.

```nginx
# /etc/nginx/conf.d/blue_green.conf (шаблон)
upstream app {
    server 10.0.1.10:8080 weight=1;   # Blue (активна)
    server 10.0.1.20:8080 weight=0;   # Green (выведена)
}
server {
    listen 80;
    location / { proxy_pass http://app; }
}
```

**Переключение (требует reload, т.к. в OSS Nginx нет runtime-disable сервера):**
```bash
# Смена весов через шаблон/SED и плавный релоад
sed -i 's/weight=1;.*# Blue/weight=0;  # Blue/; s/weight=0;.*# Green/weight=1;  # Green/' /etc/nginx/conf.d/blue_green.conf
nginx -t && systemctl reload nginx
```

**Автоматизация через Ansible** (полный плейбук — в **[Ansible: Blue-Green Deployment](../../Ansible/ansible_deployment_strategies.md)**): переключение весов, pre-flight health check и POST-switch probe выполняются одним плейбуком с `retries/until`.

### 9. Blue-Green для статического фронтенда (symlink flip)

Для SPA/статики точка входа — симлинк `current`, который nginx отдает как root. Новая версия раскладывается рядом; переключение — атомарная смена ссылки. Этот примитив (symlink + рестарт) описан в **[сравнении стратегий](./comparison.md)** для монолитов; для фронта добавляется инвалидация кэша.

```bash
# Релизы лежат изолированно
ln -sfn /srv/www/releases/v1.3.0 /srv/www/current   # атомарная смена
nginx -s reload                                      # подхватить (при server-rendered)
# При SPA с хэшированными ассетами достаточно отдать новый index.html (flip symlink).

# Мгновенный откат:
ln -sfn /srv/www/releases/v1.2.3 /srv/www/current
```

**Валидация:**
```bash
readlink /srv/www/current        # → /srv/www/releases/v1.3.0
curl -s localhost | grep -o '<title>.*</title>'
```

> Если статика кэшируется на CDN/браузере, после flip выполняется purge кэша HTML (ассеты по хэшу инвалидации не требуют).

### 10. Blue-Green через Docker Compose (nginx + две версии приложения)

Практический кейс миграции стека между хостами без простоя — в **[миграции Docker Compose VPS](../../Docker/Docker_compose/vps_migration_zero_downtime.md)**. Ниже — схема Blue-Green внутри одного хоста: две версии приложения и nginx, чья конфигурация переключает активный upstream.

**`docker-compose.yml`:**
```yaml
services:
  app_blue:
    image: myapp:1.2.3
    expose: ["8080"]
  app_green:
    image: myapp:1.3.0
    expose: ["8080"]
  nginx:
    image: nginx:1.27
    ports: ["80:80"]
    volumes: ["./nginx.conf:/etc/nginx/nginx.conf:ro"]
    depends_on: [app_blue, app_green]
```

**`nginx.conf`:**
```nginx
upstream active { server app_blue:8080; }   # при switch меняем на app_green
server { listen 80; location / { proxy_pass http://active; } }
```

**Cutover:** замена `app_blue` на `app_green` в `nginx.conf` и пересоздание только nginx:
```bash
sed -i 's/app_blue:8080/app_green:8080/' nginx.conf
docker compose up -d nginx
```

**Валидация:**
```bash
curl -sI localhost | head -1
docker compose exec nginx wget -qO- http://app_green:8080/healthz   # 200 => Green готов
```

### 11. Автоматизация переключения в CI/CD (Health Gate)

Сам Cutover выносится в отдельный ручной (manual) этап пайплайна — это и есть Health Gate: автоматизированный deploy Green, но switch трафика требует подтверждения после проверок.

```yaml
# .gitlab-ci.yml (фрагмент)
stages: [deploy, cutover]

deploy_green:
  stage: deploy
  script:
    - kubectl apply -f deployment-green.yaml
    - kubectl wait --for=condition=Available rollout/my-app --timeout=300s

blue_green_cutover:
  stage: cutover
  when: manual            # требует подтверждения инженера (Health Gate)
  environment: production
  script:
    - kubectl patch service my-app-service -p '{"spec":{"selector":{"version":"green"}}}'
```

Для bare-metal аналогом служит SSH-шаг, выполняющий flip VIP (keepalived) или `enable/disable server` в HAProxy из пайплайна. Ключевое требование: шаг отката должен быть симметричным и одной командой.

### 12. Наблюдаемость после переключения (SRE Golden Signals)

Сразу после Cutover в течение периода soak необходимо сравнивать Green с базовой линией Blue по четырём золотым сигналам: **Latency, Traffic, Errors, Saturation**.

```promql
# Доля 5xx по активной (green) версии
sum(rate(http_requests_total{code=~"5..",env="green"}[5m]))
  / sum(rate(http_requests_total{env="green"}[5m]))

# P95 латентности green vs blue (до switch)
histogram_quantile(0.95,
  sum(rate(http_request_duration_seconds_bucket{env="green"}[5m])) by (le))
```

**Критерии решения:**
- Резкий рост Error Rate или Latency выше порога → немедленный откат (см. **[проверки здоровья и откат](./deployment_health_checks_and_rollback.md)**).
- Стабильность в течение soak-окна (например, 1–24ч в зависимости от нагрузки) → Decommissioning Blue.
- Guardrail-метрики (нагрузка на БД, очереди) не должны деградировать.

## Операции и команды

Быстрый справочник CLI для типовых действий в Blue-Green.

| Действие | Инструмент | Команда / фрагмент |
| :--- | :--- | :--- |
| **Переключение трафика в K8s** | `kubectl` | `kubectl patch svc/my-app -p '{"spec":{"selector":{"version":"green"}}}'` |
| **Проверка статуса rollout** | `kubectl` | `kubectl rollout status deployment/my-app-green --timeout=300s` |
| **Переключение HTTPRoute** | `kubectl` | `kubectl patch httproute/shop-route -p '{"spec":{"rules":[{"backendRefs":[{"name":"app-v2-green","port":8080,"weight":100}]}]}'` |
| **Flip VIP (keepalived)** | `ssh` + `sed` + `systemd` | `sed -i 's/priority 100/priority 200/' /etc/keepalived/keepalived.conf && systemctl reload keepalived` |
| **Включить Green в HAProxy** | `socat` + Unix-сокет | `echo "enable server app/green" \| socat stdio /var/run/haproxy.sock` |
| **Отключить Blue в HAProxy** | `socat` + Unix-сокет | `echo "disable server app/blue" \| socat stdio /var/run/haproxy.sock` |
| **Состояние серверов HAProxy** | `socat` + Unix-сокет | `echo "show servers state app" \| socat stdio /var/run/haproxy.sock` |
| **Переключение весов Nginx** | `sed` + `systemd` | `sed -i 's/weight=1;/weight=0;/' /etc/nginx/conf.d/blue_green.conf && nginx -t && systemctl reload nginx` |
| **Проверка конфигурации Nginx** | `nginx` | `nginx -t` |
| **Переключение systemd-сервиса** | `systemd` | `ln -sfn /srv/www/releases/v1.3.0 /srv/www/current && systemctl reload nginx` |
| **Промоушен Argo Rollouts** | `argocd` / `kubectl` | `kubectl argo rollouts promote my-app` |
| **Аварийный откат Argo Rollouts** | `argocd` / `kubectl` | `kubectl argo rollouts abort my-app` |
| **Переключение в Traefik** | `traefik` | Изменение `serversTransport`/`servers` в middleware или флагом в IngressRoute. |
| **Валидация VIP после switch** | `ip` + `journalctl` | `ip addr show eth0 \| grep 10.0.1.100 && journalctl -u keepalived -n 20 \| grep ENTERING MASTER` |

## Устранение неполадок (Troubleshooting)

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Сплит-брейн (Split Brain)** | Длительный TTL в DNS или кэш прокси-серверов. | Использовать L7 переключение; уменьшить TTL до < 60с. |
| **Database Lock** | Миграция Green заблокировала таблицы для Blue. | Использовать инструменты онлайн-миграций (gh-ost, pt-osc). |
| **OOMKilled при раскатке** | Нехватка ресурсов для запуска 200% реплик. | Проверить квоты Namespace; временно увеличить ёмкость кластера. |
| **Разлогин пользователей** | Отсутствие синхронизации сессий между средами. | Использовать распределенное хранилище сессий. |
| **Зависшие TCP / WebSocket соединения** | При переносе VIP или весов in-flight долгие соединения к старой среде разрываются. | Connection draining (HAProxy `drain`, nginx graceful shutdown); для WebSocket — sticky + короткий reconnect timeout. |
| **Расхождение данных при откате** | Green успела записать в общую БД новые данные. | Обратно-совместимые миграции (Expand-Contract); компенсирующие транзакции; запрет деструктивных DDL до decommission. |
| **Холодный старт (всплеск 5xx)** | Прогрев не завершён (JIT, пулы, кэши). | `startupProbe`/`readinessProbe` + прогон warm-up трафика перед Cutover. |
| **Частичная маршрутизация** | Балансировщик закэшировал состояние или switch применён не на всех узлах. | Проверить применение правила на всех L7-нодах; `show servers state` / `nginx -T`. |
| **Keepalived не переключает VIP** | Одинаковый или перекрывающийся `virtual_router_id` в разных инстансах; разделенная сеть без multicast. | Уникальный `virtual_router_id` на каждый VRRP-инстанс; `nopreempt` для предотвращения флэппинга; проверка `advert_int`. |
| **HAProxy socket permission denied** | Юнит `haproxy` запускается не от того пользователя, или сокет отсутствует. | `chmod 660 /var/run/haproxy.sock`, добавить пользователя в группу `haproxy`, проверить `stats socket` в конфиге. |
| **Статические ассеты устарели после flip** | Браузер/CDN кэширует старый `index.html` или CSS/JS. | Purge HTML через CDN API; для SPA с хэшированными ассетами инвалидация не требуется, но корневой HTML должен быть без кэша. |
| **Green не проходит Health Gate** | Привязка к внутренней БД, отсутствие прав, неверный секрет. | Проверить сетевую политику (NetworkPolicy/security group), логи приложения, переменные окружения в Deployment/Pod. |
| **Ошибка лицензий при 2x capacity** | Blue и Green вместе превышают лимит лицензий ПО (например, JBoss, WebLogic). | Планировать capacity с запасом под одну среду +burst; использовать лицензии с гранулярной (per-core) моделью. |
| **Время переключения > SLA** | Многопоточный релоад Nginx без `--with-http_v3` или медленный health-check. | Использовать HAProxy runtime API или keepalived для переключения < 1с; уменьшить `inter`/`fastinter` в HAProxy health-check. |
| **Rollback не работает (старая версия не стартует)** | Образ Blue удален из registry или конфиг изменен несовместимо. | Хранить теги immutable (v1.2.3, не `latest`); never mutate running configs; dry-run rollback в staging перед релизом. |
| **Разные конфиги Blue и Green** | Config Drift: ручные правки на Blue не попали в Green. | Immutable Images + Configuration as Code (Ansible/Terraform); ни одной ручной правки на горячую среду. |

## Лучшие практики

1. **Паритет сред:** Blue и Green должны быть идентичны во избежание специфичных для окружения ошибок.
2. **Автоматизированное тестирование:** Запуск Smoke и Regression тестов в Green-среде перед Cutover обязателен (Health Gate).
3. **Комплексный мониторинг:** Отслеживайте не только 5xx ошибки, но и бизнес-метрики (конверсия, доход) сразу после переключения.
4. **Разделение компонентов (Decoupling):** Изоляция сервисов минимизирует влияние обновлений на систему.
5. **Пред-cutover верификация извне:** smoke-тесты должны идти с реального клиентского пути (не только локально в кластере).
6. **Soak-период:** держите Blue в резерве (не выключайте) минимум до завершения пика нагрузки после switch.
7. **Cleanup по завершении:** остановка/удаление Green после подтверждения стабильности, чтобы не платить за 2x постоянно.
8. **Резервирование ёмкости (2x):** планируйте квоты/серверы под обе среды заранее.
9. **Immutable Images:** каждый релиз имеет уникальный тег образа; откат = переключение на предыдущий тег, а не `docker pull :latest`.
10. **Симметричный откат:** шаг rollback должен быть одной командой, обратной к cutover, и протестированной в DR-тренировках.
11. **Sticky Sessions по желанию:** используйте их только при необходимости; предпочтительнее внешнее хранилище сессий для универсальности.
12. **Graceful shutdown:** приложение должно завершать in-flight запросы перед SIGTERM, иначе Cutover даст всплеск 5xx.
13. **Kill Switch:** готовьте аварийный runbook и роль ответственного инженера; при массовом инциденте откат должен занимать < 60 секунд.
14. **Guardrail-метрики:** задайте пороги не только на ошибки, но и на латентность P95/P99, saturation очередей, лимиты соединений к БД.

## Граничные случаи и ограничения

- **Долгие транзакции и потоковые соединения:** при атомарном switch SQL-транзакции в момент Cutover могут прерваться; для WebSocket/SSE требуется клиентский reconnect и server-side draining.
- **Stateful-сервисы (очереди, фоновые воркеры):** переключение только L7-трафика не затрагивает консьюмеров; воркеры должны быть совместимы с обеими версиями схемы или перезапускаются синхронно с Green.
- **Общая база данных — узел боли:** Blue и Green почти всегда делят БД; поэтому N-1 совместимость обязательна, иначе откат невозможен.
- **Стоимость 2x ресурсов:** требуется резервировать ёмкость под обе среды (capacity planning), иначе Green задушит Blue при совместной работе.
- **Прогрев не репрезентативен:** Green до Cutover не видела продакшен-нагрузку, поэтому реальные бенчмарки появляются только после switch — держите soak-окно.
- **DNS TTL / клиентское кэширование:** даже при корректном L7-switch клиенты с агрессивным кэшем могут ходить на старую среду часами; предпочтительны L7-веса или VRRP/VIP.
- **Частичный кэш статики (CDN/браузер):** пользователь видит устаревшую версию фронта; решение — purge кэша HTML после symlink-flip.
- **Compliance и лицензии:** удвоение инстансов ПО может нарушать лицензионные лимиты; учитывайте при планировании.

## Дополнительная информация

### Преимущества и недостатки

| Преимущества | Недостатки |
| :--- | :--- |
| **Нулевой простой** при корректной настройке. | **Высокая стоимость** — требует 2x ресурсов. |
| **Безопасный откат** — Blue-среда всегда готова. | **Риск «всё или ничего»** — ошибка аффектит 100% трафика. |
| **Отсутствие дрейфа версий** — активна только одна версия. | **Сложность данных** — риск рассинхронизации при откате. |

### Советы для собеседования

**Вопрос:** Вы переключили трафик на Green, и посыпались ошибки. Какова процедура отката и в чем ее преимущество?
**Ответ:** Процедура — немедленный возврат конфигурации сетевого слоя (например, селектора Service, VIP или веса в балансировщике) на Blue. Преимущество — скорость: откат занимает секунды, так как Blue-среда все это время была запущена и прогрета.

**Вопрос:** В чем разница между Blue-Green и Canary?
**Ответ:** Blue-Green переключает 100% трафика атомарно, а Canary — постепенно (1%, 5%, ...). Blue-Green дороже (нужно 2x ресурсов), но проще в логике отката.

**Вопрос:** Почему Blue-Green дороже Canary и когда всё-таки выбирать его?
**Ответ:** Требует удвоения инфраструктуры (2x), но даёт мгновенный, предсказуемый откат и простую логику. Выбирается для критичных сервисов, мажорных апгрейдов БД (логическая репликация) и состояний, где постепенный rollout технически сложен (тяжелые in-process состояния, лицензионные ограничения).

### См. также

- **[Сравнение стратегий развертывания](./comparison.md)** — матрица выбора стратегий, канонические примеры переключения (Nginx/keepalived/Ansible).
- **[Проверки здоровья и откат](./deployment_health_checks_and_rollback.md)** — механизмы автоматизации Health Gate и автоотката.
- **[Обратно-совместимые миграции (Expand-Contract)](../../Databases/Concepts/migrations/expand_contract.md)** — работа со слоем данных при сосуществовании версий.
- **[Балансировка нагрузки HTTP](../../Networking/Protocols/HTTP/http_load_balancing.md)** — механики L7/L4 переключения и health checks.
- **[Keepalived (VRRP)](../../Networking/ServicesAndTools/keepalived_overview.md)** — детали реализации Floating VIP в традиционной инфраструктуре.

## Интеграция с GitLab CI/CD

### Полный пайплайн Blue-Green с approval gate

```yaml
stages:
  - build
  - deploy_green
  - verify_green
  - cutover
  - monitor

build_image:
  stage: build
  image: docker:29.8
  services:
    - docker:29.8-dind
  script:
    - docker login -u $CI_REGISTRY_USER -p $CI_JOB_TOKEN $CI_REGISTRY
    - docker build -t $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA .
    - docker push $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH

deploy_green:
  stage: deploy_green
  image: bitnami/kubectl:1.37
  needs:
    - build_image
  script:
    - kubectl apply -f k8s/deployment-green.yaml
    - kubectl rollout status deployment/my-app-green --timeout=300s
  environment:
    name: production-green
    url: https://green.example.com
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH

verify_green:
  stage: verify_green
  image: curlimages/curl:8.22.0
  needs:
    - deploy_green
  script:
    - |
      curl -sf https://green.example.com/healthz || exit 1
      curl -sf https://green.example.com/readyz || exit 1
      # Проверка метрик Golden Signals
      ERROR_RATE=$(curl -s "http://prometheus:9090/api/v1/query?query=sum(rate(http_requests_total{env='green',status=~'5..'}[5m]))/sum(rate(http_requests_total{env='green'}[5m]))" | jq '.data.result[0].value[1]')
      if (( $(echo "$ERROR_RATE > 0.01" | bc -l) )); then
        echo "Green failed: error rate $ERROR_RATE"
        exit 1
      fi
  environment:
    name: production-green

blue_green_cutover:
  stage: cutover
  image: bitnami/kubectl:1.37
  needs:
    - verify_green
  script:
    - kubectl patch service/my-app-service -p '{"spec":{"selector":{"version":"green"}}}'
    - kubectl rollout status deployment/my-app-green --timeout=60s
  environment:
    name: production
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: manual
      allow_failure: false

post_cutover_monitor:
  stage: monitor
  image: curlimages/curl:8.22.0
  needs:
    - blue_green_cutover
  script:
    - |
      sleep 60  # soak window
      ERROR_RATE=$(curl -s "http://prometheus:9090/api/v1/query?query=sum(rate(http_requests_total{env='green',status=~'5..'}[5m]))/sum(rate(http_requests_total{env='green'}[5m]))" | jq '.data.result[0].value[1]')
      if (( $(echo "$ERROR_RATE > 0.01" | bc -l) )); then
        echo "Post-cutover degradation detected. Initiating rollback..."
        kubectl patch service/my-app-service -p '{"spec":{"selector":{"version":"blue"}}}'
        exit 1
      fi
  environment:
    name: production
```

### Blue-Green с keepalived (VRRP) в GitLab CI

```yaml
blue_green_vrrp:
  stage: cutover
  image: alpine:3.24
  needs:
    - verify_green
  script:
    - apk add --no-cache openssh-client
    - ssh deploy@green-lb "sed -i 's/priority 100/priority 200/' /etc/keepalived/keepalived.conf"
    - ssh deploy@green-lb "systemctl reload keepalived"
    - sleep 5
    - ssh deploy@green-lb "ip addr show eth0 | grep -q 10.0.1.100 && echo 'VIP на Green'"
  environment:
    name: production
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: manual
```

### Автоматический откат Blue-Green через GitLab API

```yaml
emergency_rollback:
  stage: rollback
  image: bitnami/kubectl:1.37
  script:
    - kubectl patch service/my-app-service -p '{"spec":{"selector":{"version":"blue"}}}'
    - echo "Rollback executed at $(date)" >> rollback.log
  environment:
    name: production
  rules:
    - if: $CI_PIPELINE_SOURCE == "schedule"
```

### Blue-Green через Argo Rollouts + GitLab CI

```yaml
deploy_argo_rollout:
  stage: deploy
  image: bitnami/kubectl:1.37
  needs:
    - build_image
  script:
    - kubectl apply -f k8s/rollout-bluegreen.yaml
    - kubectl argo rollouts promote my-app --timeout 300s
  environment:
    name: production
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: manual
```
