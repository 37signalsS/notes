# Канареечное развертывание (Canary Deployment)

> Стратегия поэтапного выпуска, при которой новая версия приложения выкатывается на контролируемую долю трафика или пользователей для оценки стабильности перед полным развертыванием. Детали по мониторингу и автоматическому гейтингу — в **[Мониторинг и оценка трафика при Canary](./canary_monitoring_and_gating.md)**; общее сравнение стратегий — в **[Сравнение стратегий развертывания](./comparison.md)**.

## Определения

**Канареечное развертывание (Canary Deployment)** — стратегия выпуска, при которой новая версия приложения (**Canary**) выкатывается для небольшой контролируемой группы пользователей или доли трафика, в то время как основная масса продолжает использовать стабильную версию (**Stable** / **Baseline**). Подход позволяет оценить влияние изменений в реальных условиях и минимизировать «радиус поражения» (blast radius) при обнаружении багов перед полным развертыванием.

- **Радиус поражения (Blast Radius)** — объем потенциального негативного воздействия на систему или пользователей в случае сбоя. Canary минимизирует этот показатель.
- **Прогрессивная поставка (Progressive Delivery)** — методология, развивающая Continuous Delivery, которая включает Canary-релизы и автоматизированное управление трафиком на основе метрик.
- **Анализ канарейки (Canary Analysis)** — процесс автоматического сравнения метрик новой версии с эталонной (Baseline) для принятия решения о продвижении или откате.
- **Гейтинг (Gating)** — механизм блокировки или разрешения перехода на следующий этап раскатки на основе результатов анализа.
- **Взвешенная маршрутизация (Weighted Routing)** — распределение трафика между версиями пропорционально заданным весам (например, 90/10). В Nginx/HAProxy задаётся через `weight` и `split_clients`; на традиционных средах это основной механизм Canary без оркестратора.
- **Сегментация по атрибутам (Attribute-based Routing)** — направление конкретных запросов на Canary по признакам: заголовок (`X-Canary: true`), cookie, query-параметр или источник (внутренний IP). Позволяет реализовать «opt-in canary» для внутренних пользователей без изменения доли случайного трафика.
- **Baseline (Контрольная группа)** — инстанс старой стабильной версии, запущенный параллельно с Canary в тех же условиях для максимально точного сравнения метрик. Заменяет сравнение с историческими средними.
- **Stable (Стабильная версия)** — текущая рабочая версия, несущая основной трафик. После успешного Canary-релиза она становится новой Baseline.
- **Traffic Splitting (Разделение трафика)** — механизм L7-маршрутизации, направляющий процент запросов на Canary, а остальные — на Stable. Реализуется через веса бэкендов, split_clients, Gateway API или Service Mesh.
- **Feature Flag (Флаг функциональности)** — механизм включения/выключения логики в рантайме без пересборки артефакта. Альтернативный подход к Canary: код деплоится выключенным, а флаг активирует его для целевой группы пользователей.
- **Автоматический откат (Auto-rollback)** — gate-механизм, автоматически возвращающий 100% трафика на Stable при превышении порогов ошибок, задержек или скорости расхода error budget.
- **Окно наблюдения (Observation Window)** — фиксированный интервал времени (обычно 60–300 с), в течение которого собираются метрики Canary перед принятием решения о продвижении веса.
- **Side-by-side Deployment** — параллельный запуск двух полных версий приложения (Stable и Canary) с разделением трафика на уровне балансировщика или Service Mesh.

## Основные концепции

### Цели и предпосылки

**Основная цель:** Снижение риска инцидентов путем раннего обнаружения технических и бизнес-регрессий на малой доле реального трафика.

**Принципы:**
- **Минимальное воздействие:** Новая версия сначала доступна лишь 1–5% пользователей.
- **Реальный трафик:** Тестирование происходит в боевых условиях с настоящими запросами.
- **Постепенность:** Поэтапное увеличение нагрузки или откат при обнаружении аномалий.

**Ключевые предпосылки:**
- **Разделение трафика (Traffic Splitting)** — возможность точно направлять процент трафика или сегментировать его по атрибутам (headers, cookies).
- **Продвинутая наблюдаемость** — раздельный сбор метрик для разных версий для их прямого сравнения.
- **Автоматизированное управление** — наличие контроллеров, способных принимать решения об увеличении веса или откате на основе анализа данных.

### Архитектура и компоненты

Реализация Canary требует взаимодействия нескольких уровней инфраструктуры:
1.  **Уровень маршрутизации (Traffic Routing):** Компонент, способный разделять входящий поток запросов (L7 Load Balancer, Ingress, Gateway API или Service Mesh).
2.  **Уровень управления (Controller):** Оркестратор или оператор, который управляет жизненным циклом ревизий и изменяет веса в маршрутизаторе (например, Argo Rollouts, Flagger).
3.  **Уровень наблюдаемости (Observability):** Система сбора метрик (Prometheus), обеспечивающая разделение данных по версиям для анализа.
4.  **Уровень принятия решений (Analysis Engine):** Алгоритм или сервис, выполняющий статистическое сравнение метрик (Golden Signals) Stable vs Canary.

### Этапы и жизненный цикл

1.  **Подготовка (Baseline):** Рекомендуется запустить "контрольную группу" (Baseline) — инстанс старой версии в тех же условиях, что и Canary, для максимально точного сравнения метрик.
2.  **Развертывание (Canary Deploy):** Запуск Canary-версии с 0% трафика. Проверка готовности (Readiness Probes).
3.  **Начальный сегмент (Initial Rollout):** Направление малой доли (1–5%) трафика на новую версию.
4.  **Анализ (Analysis Phase):** Сравнение ключевых показателей здоровья (SRE Golden Signals) между Stable (или Baseline) и Canary.
5.  **Прогрессивная раскатка (Step-by-step Rollout):** Поэтапное увеличение доли трафика (10% → 25% → 50%) при отсутствии аномалий.
6.  **Финальное продвижение (Promotion):** Перевод 100% трафика на новую версию, которая теперь становится основной.
7.  **Очистка (Cleanup):** Удаление старой версии ресурсов и ReplicaSet.

### Требования к инфраструктуре и инструменты

Для реализации Canary недостаточно простого балансировщика, требуется интеллектуальное управление L7-трафиком:
- **Ingress-контроллеры:** NGINX Ingress (через аннотации `canary-*`), Traefik, Emissary-ingress.
- **Gateway API:** Современный стандарт Kubernetes (2026) для управления трафиком (`HTTPRoute` веса).
- **Service Mesh:** Istio, Linkerd (TrafficSplit), Consul Connect.
- **Контроллеры прогрессивной доставки:**
  - **Argo Rollouts** — заменяет стандартный Deployment на объект `Rollout`, управляющий стратегиями.
  - **Flagger** — оператор, использующий Service Mesh или Ingress для автоматизации Canary.

Развёрнутое сравнение подходов — в **[обзоре стратегий развертывания](../Core_Concepts/deployment_strategies.md)**.

### Реализация в традиционной инфраструктуре (Bare Metal / VM)

Вне Kubernetes Canary базируется на L7-маршрутизаторе (Nginx, HAProxy, Traefik), стоящем перед пулом серверов. Ключевые отличия от облачных контроллеров:

1.  **Маршрутизатор — единая точка правды.** Веса и правила задаются в его конфиге; изменение веса = редактирование конфига + reload или сокет-команда (HAProxy), а не патч кастомного ресурса.
2.  **Метрики разделяются по лейблу версии.** Приложение должно отдавать метрики с лейблом `version` (через exposition или relabeling в Prometheus), чтобы Canary Analysis сравнивал `version="canary"` с `version="stable"`.
3.  **Graceful shutdown обязателен.** При смещении веса с узла он продолжает дожимать активные запросы; без корректного перехвата `SIGTERM` часть ответов обрывается (502/504).
4.  **Балансировщик как гейт.** Решение об увеличении веса принимается оператором или CI-скриптом на основе метрик, собранных из HAProxy stats / Prometheus / nginx-exporter.

**Минимальный набор компонентов в on-prem среде:**
- L7-маршрутизатор с поддержкой весов и health checks (Nginx / HAProxy / Traefik).
- Сборщик метрик (Prometheus + node_exporter + nginx/haproxy exporters).
- Механизм доставки артефакта на canary-узлы (rsync / Ansible).
- Health-эндпоинт, реально проверяющий зависимости (БД, кэш, внешние API).

Подробности по механике балансировки и health checks — в материале **[Балансировка нагрузки HTTP](../../Networking/Protocols/HTTP/http_load_balancing.md)** (в частности, «Сценарий 7: Traffic splitting (canary) в HAProxy»).

## Практические сценарии

### 1. Нативная реализация в Kubernetes (Standard)

В стандартном Kubernetes Canary реализуется через создание двух Deployment с общими метками для селектора одного Service. Распределение трафика в этом случае пропорционально количеству реплик.

1.  **Стабильная версия (90% трафика):**
    ```yaml
    apiVersion: apps/v1
    kind: Deployment
    metadata:
      name: app-stable
    spec:
      replicas: 9
      selector:
        matchLabels:
          app: my-app
      template:
        metadata:
          labels:
            app: my-app
            version: stable
        spec:
          containers:
          - name: app
            image: my-app:v5
    ```

2.  **Канареечная версия (10% трафика):**
    ```yaml
    apiVersion: apps/v1
    kind: Deployment
    metadata:
      name: app-canary
    spec:
      replicas: 1
      selector:
        matchLabels:
          app: my-app
      template:
        metadata:
          labels:
            app: my-app
            version: canary
        spec:
          containers:
          - name: app
            image: my-app:v6
    ```

3.  **Общий Service:**
    ```yaml
    apiVersion: v1
    kind: Service
    metadata:
      name: my-app-service
    spec:
      ports:
      - port: 80
      selector:
        app: my-app  # Выбирает поды обоих Deployment
    ```

**Управление трафиком:**
Распределение трафика можно динамически изменять, масштабируя количество реплик в каждом Deployment с помощью `kubectl`:
```bash
# Увеличение доли Canary до ~18% (2 из 11 подов)
kubectl scale deployment/app-canary --replicas=2
```

### 2. Реализация через Kubernetes Gateway API (Стандарт 2026)

Современный способ управления трафиком без использования проприетарных аннотаций. Используется ресурс `HTTPRoute`.

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: shop-api
spec:
  parentRefs:
  - name: internal-gateway
  rules:
  - backendRefs:
    - name: shop-api-stable
      port: 8080
      weight: 90
    - name: shop-api-canary
      port: 8080
      weight: 10
```

### 3. Реализация через Istio (Service Mesh)

Istio позволяет управлять весами трафика на уровне виртуальной сети, не изменяя физическое количество реплик. Подробнее про маршрутизацию в mesh — **[Управление трафиком в Service Mesh](../../Service_Mesh/traffic_management.md)**.

```yaml
# DestinationRule определяет подмножества на основе меток
apiVersion: networking.istio.io/v1alpha3
kind: DestinationRule
metadata:
  name: app-destination
spec:
  host: my-app-service
  subsets:
  - name: stable
    labels:
      version: stable
  - name: canary
    labels:
      version: canary

---
# VirtualService распределяет веса между подмножествами
apiVersion: networking.istio.io/v1alpha3
kind: VirtualService
metadata:
  name: app-virtualservice
spec:
  hosts:
  - my-app-service
  http:
  - route:
    - destination:
        host: my-app-service
        subset: stable
      weight: 90
    - destination:
        host: my-app-service
        subset: canary
      weight: 10
```

### 4. Автоматизация через Argo Rollouts

Декларативное описание шагов раскатки и анализа.

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Rollout
metadata:
  name: payment-service
spec:
  replicas: 10
  strategy:
    canary:
      steps:
      - setWeight: 10
      - pause: {duration: 5m}
      - analysis:
          templates:
          - templateName: success-rate-check
      - setWeight: 50
      - pause: {duration: 10m}
```

### 5. Docker Swarm + Traefik

Реализация через взвешенные сервисы в Traefik.

```yaml
services:
  app-stable:
    image: my-app:v1
    deploy:
      labels:
        - "traefik.http.services.app.loadbalancer.weighted.services.app-stable.weight=90"

  app-canary:
    image: my-app:v2
    deploy:
      replicas: 1
      labels:
        - "traefik.http.services.app.loadbalancer.weighted.services.app-canary.weight=10"
```

### 6. Использование флагов функций (Feature Toggles)

Альтернатива на уровне приложения — управление логикой через [флаги функций](../Testing/feature_toggles/scenarios.md). Позволяет реализовать Canary для конкретных пользователей (например, по ID или региону) даже без поддержки на уровне сети.

### 7. Canary через Nginx (open source, без оркестратора)

Nginx поддерживает Canary двумя способами: по доле трафика (`split_clients`) и по атрибуту запроса (`map` + заголовок/cookie).

**A. Долевой canary (`split_clients`):**
```nginx
upstream app_stable {
    server 10.0.1.10:8080;
    server 10.0.1.11:8080;
}
upstream app_canary {
    server 10.0.1.20:8080;
}

server {
    listen 80;
    # Детерминированное распределение по ключу (IP) → один клиент стабильно на одной версии
    split_clients "${remote_addr}AAA" $upstream_variant {
        10%     app_canary;
        *       app_stable;
    }
    location / {
        proxy_pass http://$upstream_variant;
        proxy_set_header Host $host;
    }
}
```
Сдвиг доли — изменение процента и `nginx -s reload` (предварительно `nginx -t`).

**B. Opt-in canary по заголовку/cookie (для внутренних тестов):**
```nginx
map $http_x_canary $canary_by_header {
    "true"   app_canary;
    default  app_stable;
}
map $cookie_canary $canary_backend {
    "1"      app_canary;
    default  $canary_by_header;
}
server {
    location / {
        proxy_pass http://$canary_backend;
    }
}
```

**Валидация:**
```bash
nginx -t && nginx -s reload   # → syntax is ok / configuration test passed
for i in $(seq 1 100); do curl -s -H "X-Canary: true" http://lb/version; done | sort | uniq -c
# → все запросы с заголовком попадают на canary-версию
```

### 8. Canary через HAProxy (weighted + opt-in cookie)

HAProxy позволяет задавать веса серверам и переключать их «на лету» через UNIX-сокет, а также реализовать opt-in canary по cookie.

```haproxy
backend app_servers
    balance roundrobin
    # Opt-in: запросы с cookie canary=1 идут сразу на canary-бэкенд
    acl opt_in_cookie cook(canary) -m found
    use_backend app_canary if opt_in_cookie

    server stable1 10.0.1.10:8080 check weight 90
    server stable2 10.0.1.11:8080 check weight 90

backend app_canary
    server canary1 10.0.1.20:8080 check weight 10
```

**Поэтапный сдвиг веса через сокет (без reload):**
```bash
for w in 5 10 25 50 100; do
  echo "set server app_servers/stable1 weight $((100-w))" | socat - UNIX-CONNECT:/var/run/haproxy.sock
  echo "set server app_servers/stable2 weight $((100-w))" | socat - UNIX-CONNECT:/var/run/haproxy.sock
  echo "set server app_canary/canary1 weight $w"          | socat - UNIX-CONNECT:/var/run/haproxy.sock
  sleep 60   # окно наблюдения за Golden Signals
done
```

**Валидация:**
```bash
echo "show stat" | socat - UNIX-CONNECT:/var/run/haproxy.sock | grep -E "app_servers|app_canary"
# → status=UP, колонка weight отражает текущие значения
```

### 9. Canary через Traefik (standalone / bare metal)

Вне Swarm/K8s Traefik настраивается через file provider. Взвешенная доставка реализуется `weighted` сервисом, а opt-in — отдельным router с middleware.

```yaml
http:
  services:
    app-stable:
      loadBalancer:
        servers:
          - url: "http://10.0.1.10:8080"
          - url: "http://10.0.1.11:8080"
    app-canary:
      loadBalancer:
        servers:
          - url: "http://10.0.1.20:8080"
    app-weighted:
      weighted:
        services:
          - name: app-stable
            weight: 90
          - name: app-canary
            weight: 10
  routers:
    app:
      rule: "Host(`api.example.com`)"
      service: app-weighted
    app-canary-optin:
      rule: "Host(`api.example.com`) && Headers(`X-Canary`, `true`)"
      service: app-canary
```
Сдвиг веса = правка `weight` в динамическом конфиге и перезагрузка/сигнал Traefik. Подробнее — в **[обзоре Traefik](../../WebServers/Traefik/traefik_overview.md)**.

### 10. Canary через Ansible (управление весами Nginx)

Ansible может держать canary-вес в переменной и пересобирать upstream Nginx через шаблон с последующим reload (проверка конфига встроенным `validate`).

```yaml
- name: Shift canary weight
  hosts: lb
  vars:
    canary_weight: 10
  tasks:
    - name: Render nginx upstream
      ansible.builtin.template:
        src: app_upstreams.j2
        dest: /etc/nginx/conf.d/app_upstreams.conf
        validate: "nginx -t -c /etc/nginx/nginx.conf"
      notify: reload nginx
  handlers:
    - name: reload nginx
      ansible.builtin.service:
        name: nginx
        state: reloaded
```
Шаблон `app_upstreams.j2`:
```jinja
upstream app_stable { server 10.0.1.10:8080; server 10.0.1.11:8080; }
upstream app_canary { server 10.0.1.20:8080; }
# split_clients использует {{ canary_weight }}% → app_canary
split_clients "${remote_addr}AAA" $variant {
    {{ canary_weight }}%  app_canary;
    *                    app_stable;
}
```
Полный паттерн с `block`/`rescue` автооткатом — в профильном материале: **[Стратегии деплоя и rolling updates в Ansible](../../Ansible/ansible_deployment_strategies.md)**.

### 11. Доставка артефакта на canary-узлы (rsync)

Новую версию доставляют на выделенный canary-хост инкрементально, после чего он уже находится в отдельном upstream с малым весом:

```bash
rsync -av --checksum-choice=xxh3 --compress-choice=zstd \
  deploy@repo:/opt/app/2.4.0/ /opt/app/2.4.0/
# canary-хост уже прописан в upstream app_canary с весом 10
curl -sf http://10.0.1.20:8080/healthz   # → OK, затем увеличиваем вес
```
Детали флагов и `--link-dest` для истории — в профильном материале: **[rsync — синхронизация файлов](../../Linux/SystemAdministration/rsync.md)**.

### 12. Canary через DNS (взвешенные записи) — ограниченно

Некоторые DNS-серверы (PowerDNS с `weighted-round-robin`) позволяют отдавать разные A-записи с весами. Это простейший, но грубый canary.

**Ограничения (критично):**
- **TTL и кэши:** клиенты и резолверы кэшируют ответ на всё время TTL, мгновенного отката нет.
- **Нет per-request контроля:** нельзя направить конкретного пользователя.
- **Смешивание версий в пуле:** health checks на уровне DNS отсутствуют.

Предпочтительны L7-веса (Nginx/HAProxy) или Anycast/VRRP, а не DNS-switch, для настоящего Canary.

### 13. Автоматизация трафика в CI-пайплайнах (Push-метод)

В 2026 году, если не используются специализированные операторы (ArgoCD/Flagger), управление трафиком в Push-модели (например, через GitLab CI или GitHub Actions) реализуется путем императивного обновления манифестов управления трафиком (`VirtualService` в Istio или `HTTPRoute` в Gateway API/Cilium) напрямую из пайплайна.

#### Логика взаимодействия пайплайна

1.  **Деплой Canary:** CI-пайплайн разворачивает новую версию Deployment (v2) с `replicas: 1`.
2.  **Инициализация весов:** Пайплайн устанавливает начальный вес (например, 5%) для v2 в ресурсе маршрутизации.
3.  **Итеративная раскатка:** Цикл в скрипте увеличивает вес с шагом N%, ожидая стабилизации метрик на каждой итерации.
4.  **Валидация (Gating):** Выполнение HTTP-запроса к API мониторинга (Prometheus) для проверки SRE Golden Signals.
5.  **Завершение:** Если 100% достигнуто — v2 становится Stable, старый Deployment удаляется.

#### Практический пример: Использование kubectl patch

Для автоматизации без правки YAML-файлов в репозитории используется команда `kubectl patch`, которая позволяет изменять веса "на лету" прямо из CI-раннера.

**Сценарий для Istio (VirtualService):**
```bash
# Установка веса 20% для canary подмножества
kubectl patch virtualservice my-app --type=json -p='[
  {"op": "replace", "path": "/spec/http/0/route/0/weight", "value": 80},
  {"op": "replace", "path": "/spec/http/0/route/1/weight", "value": 20}
]'
```

**Сценарий для Cilium / Gateway API (HTTPRoute):**
```bash
# Установка веса 10% для новой версии (второй backendRef)
kubectl patch httproute shop-api --type=json -p='[
  {"op": "replace", "path": "/spec/rules/0/backendRefs/0/weight", "value": 90},
  {"op": "replace", "path": "/spec/rules/0/backendRefs/1/weight", "value": 10}
]'
```

#### Пример bash-скрипта для пайплайна (Canary Loop)

Этот скрипт можно использовать в `step` пайплайна для постепенной раскатки с проверкой ошибок.

```bash
#!/bin/bash
set -e

APP_NAME="shop-api"
STEP=10
PAUSE=60 # секунд между шагами
MAX_ERROR_RATE=5 # % ошибок для отката

for weight in $(seq $STEP $STEP 100); do
  echo "--- Step: Canary Weight $weight% ---"
  
  # 1. Применяем веса (Gateway API / Cilium)
  kubectl patch httproute $APP_NAME --type=json -p="[
    {\"op\": \"replace\", \"path\": \"/spec/rules/0/backendRefs/0/weight\", \"value\": $((100 - weight))},
    {\"op\": \"replace\", \"path\": \"/spec/rules/0/backendRefs/1/weight\", \"value\": $weight}
  ]"

  if [ "$weight" -lt 100 ]; then
    echo "Waiting $PAUSE seconds for metrics collection..."
    sleep $PAUSE

    # 2. Проверка метрик через Prometheus API
    ERRORS=$(curl -s "http://prometheus:9090/api/v1/query?query=sum(rate(http_requests_total{status=~'5..',app='$APP_NAME-canary'}[1m]))/sum(rate(http_requests_total{app='$APP_NAME-canary'}[1m]))*100" | jq -r '.data.result[0].value[1]')
    
    if (( $(echo "$ERRORS > $MAX_ERROR_RATE" | bc -l) )); then
      echo "CRITICAL: Error rate is $ERRORS%. Rolling back to 0%!"
      kubectl patch httproute $APP_NAME --type=json -p='[{"op": "replace", "path": "/spec/rules/0/backendRefs/0/weight", "value": 100}, {"op": "replace", "path": "/spec/rules/0/backendRefs/1/weight", "value": 0}]'
      exit 1
    fi
  fi
done

echo "Canary deployment successful!"
```

#### Особенности для Cilium

При использовании Cilium в качестве Service Mesh (через Gateway API), пайплайн взаимодействует с теми же ресурсами `HTTPRoute`. Cilium на базе eBPF обеспечивает мгновенное применение новых весов без перезагрузки прокси-серверов, что делает Push-модель очень отзывчивой.

## Операции и команды

### Kubernetes — управление трафиком Canary

```bash
# Масштабирование canary Deployment (реplica-based splitting)
kubectl scale deployment/app-canary --replicas=2
# → deployment.apps/app-canary scaled

# Патчинг весов в Gateway API (HTTPRoute)
kubectl patch httproute shop-api --type=json -p='[
  {"op": "replace", "path": "/spec/rules/0/backendRefs/0/weight", "value": 80},
  {"op": "replace", "path": "/spec/rules/0/backendRefs/1/weight", "value": 20}
]'
# → httproute.gateway.networking.k8s.io/shop-api patched

# Патчинг весов в Istio (VirtualService)
kubectl patch virtualservice my-app --type=json -p='[
  {"op": "replace", "path": "/spec/http/0/route/0/weight", "value": 90},
  {"op": "replace", "path": "/spec/http/0/route/1/weight", "value": 10}
]'

# Проверка статуса rollout
kubectl rollout status deployment/app-canary --timeout=10m
# → deployment "app-canary" successfully rolled out

# Откат canary к 0% трафика
kubectl scale deployment/app-canary --replicas=0
```

### HAProxy — управление весами через UNIX-сокет

```bash
# Текущий статус бэкендов и веса
echo "show stat" | socat - UNIX-CONNECT:/var/run/haproxy.sock | grep -E "app_servers|app_canary"
# → pxname,svname,status,weight,act,...

# Сдвиг веса stable→canary без reload
echo "set server app_servers/stable1 weight 70" | socat - UNIX-CONNECT:/var/run/haproxy.sock
echo "set server app_canary/canary1 weight 30" | socat - UNIX-CONNECT:/var/run/haproxy.sock

# Вывод canary-узла в drain (для отката)
echo "set server app_canary/canary1 state drain" | socat - UNIX-CONNECT:/var/run/haproxy.sock

# Возврат в ready
echo "set server app_canary/canary1 state ready" | socat - UNIX-CONNECT:/var/run/haproxy.sock
```

### Nginx — управление canary через upstream и reload

```bash
# Проверка конфигурации перед применением
nginx -t
# → nginx: configuration file /etc/nginx/nginx.conf test is successful

# Graceful reload (старые воркеры дожидают запросов)
nginx -s reload

# Проверка upstream через stub_status или prometheus-exporter
curl -s http://localhost:9113/metrics | grep -E "nginx_upstream|http_requests_total"
```

### Ansible — управление canary весом и откатом

```yaml
---
- name: Canary weight shift with auto-rollback
  hosts: lb
  serial: 1
  max_fail_percentage: 0
  vars:
    canary_weight: 10
  tasks:
    - name: Update canary weight in template
      ansible.builtin.template:
        src: app_upstreams.j2
        dest: /etc/nginx/conf.d/app_upstreams.conf
        validate: "nginx -t -c /etc/nginx/nginx.conf"
      notify: reload nginx

    - name: Wait for metrics observation window
      ansible.builtin.pause:
        minutes: 5

    - name: Check canary error rate via Prometheus
      ansible.builtin.uri:
        url: "http://prometheus:9090/api/v1/query?query=sum(rate(http_requests_total{status=~'5..',version='canary'}[5m]))/sum(rate(http_requests_total{version='canary'}[5m]))*100"
      register: error_rate
      failed_when: error_rate.json.data.result[0].value[1] | float > 5
```

### systemd — управление версией canary хоста

```bash
# Атомарный переключатель версии на canary-хосте
ln -sfn /opt/app/2.4.0 /opt/app/current
systemctl restart myapp

# Проверка активности
systemctl is-active myapp   # → active
curl -sf http://localhost:8080/healthz   # → OK
readlink /opt/app/current   # → /opt/app/2.4.0
```

### Prometheus — проверка Golden Signals Canary

```bash
# Ошибки 5xx на canary
curl -s "http://prometheus:9090/api/v1/query?query=sum(rate(http_requests_total{version=\"canary\",status=~\"5..\"}[5m]))/sum(rate(http_requests_total{version=\"canary\"}[5m]))*100"
# → значение < 0.01 (1%) при норме

# P99 latency сравнение canary vs stable
curl -s "http://prometheus:9090/api/v1/query?query=histogram_quantile(0.99,sum(rate(http_request_duration_seconds_bucket{version=~\"canary|stable\"}[5m]))by(le,version))"
```

## Устранение неполадок (Troubleshooting)

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Недостаточно трафика для анализа** | Слишком малый процент Canary (1%) при низкой нагрузке. | Увеличить вес до 5–10% или продлить время анализа. |
| **Ложные срабатывания (False Positives)** | Сравнение Canary с общим пулом Stable, а не с Baseline. | Запустить Baseline-инстанс одновременно с Canary. |
| **"Отравление" данных (Data Poisoning)** | Canary пишет несовместимые данные в общую БД. | Использовать обратно-совместимые миграции ([Expand-Contract](../../Databases/Concepts/migrations/expand_contract.md)). |
| **Sticky Session Issues** | Пользователи "прыгают" между версиями при ротации. | Использовать `Session Affinity` на уровне балансировщика. |
| **Лаг метрик (Metrics Lag)** | Prometheus собирает метрики раз в 60с, а анализ идет каждые 30с. | Согласовать интервал анализа с интервалом сбора метрик. |
| **Canary не получает трафик (Nginx)** | `split_clients` не применён или reload не прошёл. | `nginx -t && nginx -s reload`; проверить ключ в `split_clients`. |
| **Вес HAProxy не применился** | UNIX-сокет недоступен или имя сервера указано неверно. | `ls -l /var/run/haproxy.sock`; `echo "show servers state" \| socat - UNIX-CONNECT:/var/run/haproxy.sock`. |
| **Cookie affinity крадёт canary** | Пользователи с session cookie попадают на stable из общего пула. | Отдельный canary-хост + opt-in cookie, внешнее хранилище сессий. |
| **Метрики не разделены по версии** | Отсутствует лейбл `version` в экспозиции метрик. | Добавить `version` в метрики приложения или relabeling Prometheus. |
| **Split-brain после reload Nginx** | Некорректный конфиг принят частично. | Всегда `nginx -t` перед `reload`; откат конфига из VCS. |
| **Canary узел в CrashLoopBackOff** | Недостаточно ресурсов или ошибка инициализации. | `kubectl describe pod` и `kubectl logs`; проверить `resources.limits` и образ. |
| **Нет Baseline — сравнение с историей некорректно** | Время суток/дня недели меняет нагрузку и профиль ошибок. | Запускать Baseline-под параллельно с Canary в том же namespace. |
| **Canary сжирает error budget до полной раскатки** | Доля 50% при высокой частоте ошибок быстро исчерпывает бюджет. | Уменьшить шаг веса (5% → 10%); включить fail-fast при burn rate > порога. |
| **Утечка памяти/CPU только на canary** | Ресурсы не ограничены или новая версия имеет regression. | Настроить `resources.limits` и `requests` в canary Deployment; сравнивать с baseline по `container_memory_usage_bytes`. |
| **DNS кэш мешает мгновенному откату** | При переключении через DNS клиенты держат старый IP до TTL. | Использовать L7-веса (Nginx/HAProxy) или снизить TTL заранее. |
| **Долгие соединения обрываются при сдвиге веса** | WebSocket/gRPC каналы не поддерживают Connection Draining. | Настроить `proxy_read_timeout` / `grpc_send_headers_timeout`; использовать external session store. |
| **Canary пишет в shared cache несовместимые ключи** | Новая версия изменяет формат сериализации в Redis/Memcached. | Expand-Contract для формата ключей; изолировать canary-сессию в отдельный namespace/ключ. |
| **Canary хост обновлен, но старая версия работает** | Symlink не переключен или systemd не перечитал бинарь. | `readlink /opt/app/current`; использовать `restart`, а не `reload`. |
| **HPA масштабирует canary отдельно от stable** | Автоскейлер смотрит только на метрики canary Deployment. | HPA должен управлять стабильным Deployment; canary масштабировать вручную или отдельным HPA с меньшими лимитами. |
| **Один пользователь скачет между версиями** | Sticky Session на LB привязал его к узлу, который перешел между пулами. | Отключить sticky на период Canary; использовать external session store (Redis). |

## Лучшие практики

1.  **Начинайте с малого:** 1%–2% трафика достаточно для выявления критических ошибок.
2.  **Определите Baseline:** Сравнивайте Canary не с абсолютными числами, а с текущим поведением Stable версии в тот же момент времени.
3.  **Graceful Shutdown:** Убедитесь, что приложение корректно завершает запросы при удалении подов.
4.  **Автоматизируйте откат:** Ручное вмешательство при сбое Canary нивелирует преимущества скорости; используйте автоматические пороги.
5.  **Проверка на "отравление" кэша:** Если Canary пишет в БД или кэш несовместимые данные, это может аффектить Stable версию.
6.  **Долгоживущие соединения:** Настраивайте `Connection Draining` для WebSocket и gRPC при переключении трафика.
7.  **Изолируйте состояние:** внешнее хранилище сессий (Redis) вместо sticky sessions, чтобы переключения весов не рвали сессии.
8.  **Собственный health endpoint:** `/healthz` должен проверять БД/кэш/внешние API, а не только факт запуска процесса.
9.  **Всегда проверяйте конфиг перед reload:** `nginx -t` / валидация HAProxy перед применением — некорректный конфиг даст 502 на всех версиях сразу.
10. **Синтетический трафик при низкой нагрузке:** ночью/в выходные анализ недостоверен без генератора нагрузки для поддержания Baseline.
11. **Expand and Contract для БД:** При обновлении работают две версии приложения. База данных должна поддерживать обе схемы одновременно. Подробнее: **[Expand-Contract](../../Databases/Concepts/migrations/expand_contract.md)**.
12. **Иммутабельность артефактов:** Canary-узел должен получать конкретную версию артефакта (хеш/тег), а не тег `:latest`. Откат = переключение на предыдущий хеш.
13. **Четкое разделение version label:** Метрики приложения должны содержать лейбл `version="canary"` / `version="stable"` для корректного анализа.
14. **Observation window:** Между шагами (5% → 10% → 25%) фиксируйте Error Rate, P95 Latency и Saturation за окно 60–300 с.
15. **Fail-closed при недоступности мониторинга:** Если Prometheus/Alertmanager недоступен — раскатка останавливается, а не продолжается вслепую.
16. **Отдельный canary пул:** Не смешивайте canary-узлы с stable в одном upstream без явных весов; отделите их физически или логически.
17. **Ограничение ресурсов (QoS):** Canary Deployment должен иметь `resources.limits`, сравнимые с stable, чтобы утечка памяти на canary не влияла на общий пул нод.

## Дополнительная информация

### Мониторинг и корректировка

Поскольку при Canary-развертывании новая версия обрабатывает реальный пользовательский трафик (даже малую его часть), наличие надежного мониторинга является критическим условием.

-   **Инструменты:** Основной стек для наблюдения — **Prometheus** (сбор метрик), **Grafana** (визуализация) и нативные метрики Kubernetes.
-   **Процесс:**
    1.  **Наблюдение:** Отслеживание ошибок, задержек и потребления ресурсов сразу после подачи трафика на Canary.
    2.  **Анализ:** Сравнение показателей Canary с Baseline.
    3.  **Решение:** На основе данных принимается решение:
        *   **Scale-up:** Увеличение веса Canary (продвижение релиза).
        *   **Rollback:** Немедленный откат при обнаружении всплеска ошибок или деградации производительности.

Подробные примеры настройки и ключевые показатели описаны в разделе **[Мониторинг Kubernetes — обзор](../../Prometheus/kubernetes/overview.md)**.

### Анализ метрик и автоматическое принятие решений (Gating)

Ключевым элементом является **Analysis Stage** — автоматическая проверка метрик перед переходом к следующему шагу. Подробные примеры запросов описаны в **[Мониторингу и оценке трафика при Canary](./canary_monitoring_and_gating.md)**.

**Критичные метрики:**
- **HTTP Error Rate** — рост 5xx ошибок.
- **Latency (p99)** — замедление ответов.
- **Resource Usage** — утечки памяти или аномальное потребление CPU на новой версии.

### Методы Canary Analysis (SRE) — статистика и пороги

Глубокие PromQL-запросы и паттерн Baseline описаны в профильном материале **[Мониторинг и оценка трафика при Canary](./canary_monitoring_and_gating.md)**. Здесь — принципы, применимые вне облака:

- **Относительное сравнение (Ratio), а не абсолютные пороги.** Сравнивайте `error_rate(canary) / error_rate(baseline)`; абсолютный «ошибок < 1%» некорректен при плавающей нагрузке.
- **Минимальный объём выборки.** При < 50–100 RPS за окно анализа выводы недостоверны: продлите окно или запустите синтетические smoke-тесты для поддержания Baseline-уровня трафика.
- **Error Budget gate.** Canary продолжается, только если burn rate (скорость расхода бюджета ошибок) ниже порога; превышение — остановка и откат.
- **Последовательный гейтинг.** Между шагами (10% → 25% → 50%) — пауза на сбор метрик; решение принимается по итогам окна, а не мгновенно.

**Команды проверки в традиционной среде (без облака):**
```bash
# HAProxy: число ответов и ошибок по бэкендам
echo "show stat" | socat - UNIX-CONNECT:/var/run/haproxy.sock \
  | awk -F, '/app_canary/{print $1, $2, "resp="$9, "err="$36}'

# Nginx Prometheus exporter
curl -s http://localhost:9113/metrics | grep -E "nginx_upstream_responses_total|nginx_http_requests_total"

# Prometheus: доля 5xx canary по лейблу version
curl -s "http://prometheus:9090/api/v1/query?query=\
sum(rate(http_requests_total{version=\"canary\",status=~\"5..\"}[5m]))\
/sum(rate(http_requests_total{version=\"canary\"}[5m]))"
# → значение < 0.01 (1%) при норме
```

### Сравнение Canary и A/B тестирования

| Характеристика | Canary Deployment | A/B Testing |
| :--- | :--- | :--- |
| **Цель** | Техническая стабильность и безопасность | Проверка бизнес-гипотез и UX |
| **Аудитория** | Случайная доля трафика (или внутренние пользователи) | Специфические бизнес-сегменты |
| **Метрики** | Ошибки, задержки, потребление ресурсов | Конверсия, клики, время на странице |
| **Управление** | Обычно через инфраструктуру (L7 Routing) | Обычно через код или SaaS-платформы |

### Граничные случаи и ограничения (традиционная среда)

- **TTL DNS/кэш CDN:** переключения на L7-уровне предпочтительнее DNS-switch.
- **Cookie/Session Affinity крадёт canary:** пользователи с session cookie могут «застрять» на stable; используйте отдельный canary-хост + opt-in cookie, а не общий пул.
- **Метрики не размечены по версии:** без лейбла `version` Canary Analysis невозможен; добавьте его в экспозицию/relabeling.
- **Долгоживущие соединения (WebSocket/gRPC):** при смещении веса настраивайте connection draining, иначе активные каналы обрываются.
- **Нехватка canary-мощности:** при малом пуле canary (1 узел) его падение = 100% потери для canary-сегмента; держите ≥2 узла.
- **Config Drift на Bare Metal:** canary-хост «стареет» после ручных правок; без immutable-образов неизбежны расхождения между stable и canary узлами в одном батче.
- **Симлинк на NFS:** при использовании NFS для обмена артефактами атомарность `ln -sfn` не гарантирована; используйте `rename(2)` через `mv -T` на локальных ФС.
- **Clock Drift:** Уплывание времени между canary и stable узлами ломает корреляцию логов и TLS-валидацию; обязательна синхронизация времени (chrony/NTP) перед раскаткой.

## Интеграция с GitLab CI/CD

### Полный пайплайн Canary с автоматическим гейтингом

```yaml
stages:
  - build
  - deploy_canary
  - analyze
  - promote
  - rollback

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

deploy_canary_5:
  stage: deploy_canary
  image: bitnami/kubectl:1.37
  needs:
    - build_image
  script:
    - kubectl apply -f k8s/deployment-canary.yaml
    - kubectl scale deployment/my-app-canary --replicas=1
    - kubectl rollout status deployment/my-app-canary --timeout=300s
  environment:
    name: canary
    url: https://canary.example.com
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH

analyze_canary:
  stage: analyze
  image: curlimages/curl:8.22.0
  needs:
    - deploy_canary_5
  script:
    - |
      sleep 120  # observation window
      ERRORS=$(curl -s "http://prometheus:9090/api/v1/query?query=sum(rate(http_requests_total{version='canary',status=~'5..'}[5m]))/sum(rate(http_requests_total{version='canary'}[5m]))*100" | jq '.data.result[0].value[1]')
      LATENCY=$(curl -s "http://prometheus:9090/api/v1/query?query=histogram_quantile(0.95,sum(rate(http_request_duration_seconds_bucket{version='canary'}[5m]))by(le))" | jq '.data.result[0].value[1]')
      echo "Canary errors: $ERRORS%, latency p95: $LATENCY"
      if (( $(echo "$ERRORS > 1" | bc -l) )) || (( $(echo "$LATENCY > 0.5" | bc -l) )); then
        echo "FAIL: canary metrics exceeded threshold"
        exit 1
      fi
  environment:
    name: canary

promote_canary_25:
  stage: promote
  image: bitnami/kubectl:1.37
  needs:
    - analyze_canary
  script:
    - kubectl scale deployment/my-app-canary --replicas=2
    - sleep 180
    - kubectl scale deployment/my-app-canary --replicas=4
  environment:
    name: canary
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH

auto_rollback:
  stage: rollback
  image: bitnami/kubectl:1.37
  needs:
    - promote_canary_25
  script:
    - kubectl scale deployment/my-app-canary --replicas=0
  environment:
    name: canary
  rules:
    - if: $CI_PIPELINE_SOURCE == "schedule"
```

### Canary через Gateway API (HTTPRoute) из GitLab CI

```yaml
canary_gateway_api:
  stage: deploy_canary
  image: bitnami/kubectl:1.37
  needs:
    - build_image
  script:
    - kubectl apply -f k8s/httproute-canary-5.yaml
    - sleep 120
    - kubectl patch httproute/my-app --type=json -p='[
        {"op": "replace", "path": "/spec/rules/0/backendRefs/0/weight", "value": 95},
        {"op": "replace", "path": "/spec/rules/0/backendRefs/1/weight", "value": 5}
      ]'
  environment:
    name: canary
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
```

### Canary через Istio VirtualService из GitLab CI

```yaml
canary_istio:
  stage: deploy_canary
  image: bitnami/kubectl:1.37
  needs:
    - build_image
  script:
    - kubectl apply -f k8s/virtualservice-canary.yaml
    - istioctl proxy-status | grep my-app
  environment:
    name: canary
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
```

### Отмена пайплайна через Alertmanager webhook

```yaml
# alertmanager.yml (ресивер)
route:
  receiver: canary-gate-webhook
receivers:
  - name: canary-gate-webhook
    webhook_configs:
      - url: http://gate-listener.internal:9099/canary-abort

# canary-abort.sh
#!/bin/bash
read -r json
pipeline=$(echo "$json" | jq -r '.commonLabels.gate // empty')
if [ "$pipeline" = "canary" ]; then
  curl -s -X POST "https://gitlab.example.com/api/v4/projects/$CI_PROJECT_ID/pipelines/$CI_PIPELINE_ID/cancel" \
    --header "PRIVATE-TOKEN: $GITLAB_API_TOKEN"
fi
```

## Рекомендованные ссылки

- **[Мониторинг и оценка трафика при Canary](./canary_monitoring_and_gating.md)** — глубокий анализ метрик, PromQL и паттерн Baseline.
- **[Сравнение стратегий развертывания](./comparison.md)** — матрица выбора стратегий.
- **[Балансировка нагрузки HTTP](../../Networking/Protocols/HTTP/http_load_balancing.md)** — механика весов, health checks и traffic splitting на Nginx/HAProxy.
