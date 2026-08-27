# Сравнение стратегий развертывания

> Документ является обзорной матрицей выбора стратегии (Single Source of Truth для сравнения). Детальные реализации по каждой стратегии вынесены в специализированные файлы (см. «См. также»). Практические сценарии разделены на два трека: **облачная оркестрация (Kubernetes)** — для существующих Kubernetes-окружений, и **традиционная инфраструктура (Bare Metal / VM)** — для on-prem и self-hosted сред без облачных зависимостей. Оба трека описаны, поскольку стратегии развертывания являются над-технологичными паттернами и применимы в любой среде.

## Определения

Выбор стратегии развертывания (Rollout Strategy) определяет способ доставки кода в среду эксплуатации, напрямую влияя на управление рисками, время простоя системы (Downtime) и требования к инфраструктуре.

- **Радиус поражения (Blast Radius)** — объем трафика или количество пользователей, которые пострадают в случае сбоя новой версии. Минимизация этого показателя — ключевая задача современных стратегий.
- **Золотые сигналы (Golden Signals)** — четыре ключевые метрики (Latency, Traffic, Errors, Saturation), используемые для оценки здоровья системы во время раскатки. Введены в методологии Google SRE как минимально достаточный набор для понимания состояния сервиса.
- **Прогрессивная поставка (Progressive Delivery)** — методология, объединяющая стратегии развертывания с автоматизированным анализом метрик для принятия решений о продолжении или откате релиза. Отличается от «простой раскатки» тем, что продвижение по этапам (stages) жестко привязано к проверке качества, а не к таймеру.
- **Автоматический судья (Judge / Analysis Engine)** — программный компонент, который в реальном времени сравнивает метрики новой и старой версий и блокирует раскатку при отклонениях. В облачной среде это Argo Rollouts Analysis / Flagger; в традиционной — скрипт на базе Prometheus + отдельный gate-шаг в Ansible/CI.
- **Graceful Shutdown (Бережное отключение)** и **Connection Draining** — процесс остановки экземпляра, при котором он перестает принимать новые соединения, дожидается завершения текущих (обычно 10–30 с) и только затем завершается. Критично для стратегий Rolling Update и Canary, чтобы не обрывать активные запросы пользователей.
- **Health Check (Проверка здоровья)** — активный или пассивный механизм определения работоспособности экземпляра. Активный: балансировщик/оркестратор периодически опрашивает эндп. `GET /healthz`. Пассивный: анализ ошибок в реальном трафике (5xx, таймауты). Корректный health-эндпоинт должен проверять критичные зависимости (БД, кэш, очередь), а не только факт «процесс жив».
- **SLO / SLI / Error Budget (SRE)** — Service Level Objective (целевой уровень сервиса, например 99.9% успешных запросов), Service Level Indicator (измеряемая метрика), и Error Budget (допустимая доля ошибок = 100% − SLO). Error Budget используется как объективный критерий для Judge: если скорость «прожигания» бюджета (burn rate) превышает порог, продвижение Canary блокируется.
- **Feature Flag (Флаг функциональности)** — механизм скрытия/показа новой логики внутри уже развернутой версии кода через конфигурацию, без перевыпуска артефакта. Дополняет стратегии развертывания: Canary управляет *трафиком между версиями*, флаг — *видимостью функции внутри одной версии*. Разные оси риска.
- **Схемная миграция (Schema Migration) / Expand-Contract** — паттерн изменения структуры БД так, чтобы старая и новая версии приложения могли работать одновременно. Обязателен для всех стратегий, кроме Recreate.
- **In-Place Resize (Kubernetes, 2026)** — механизм обновления ресурсов контейнера (CPU/RAM) без перезапуска пода, что меняет подход к Rolling Update для ресурсоемких приложений.
  - *Аналог в традиционной среде:* в systemd (cgroup v2) лимиты можно изменить на живом процессе без рестарта через `systemctl set-property myapp.service MemoryMax=2G CPUQuota=150%`. Это дает тот же эффект «прогрев кэшей не теряется» для долго инициализирующихся приложений (Java/Spring).

## Основные концепции

### Критерии оценки

| Критерий | Описание |
| :--- | :--- |
| **Downtime** | Период недоступности сервиса для пользователей. |
| **Blast Radius** | Доля трафика, подверженная риску при дефекте в v2. |
| **Rollback Speed** | Время, необходимое для возврата к стабильному состоянию v1. |
| **DB Compatibility** | Требования к обратной совместимости схемы базы данных. |
| **Observability Effort** | Сложность настройки мониторинга для валидации релиза. |
| **Cost (Infrastructure)** | Объем дополнительных вычислительных ресурсов. |
| **Net Complexity** | Требования к L7-маршрутизации (Gateway API, Service Mesh, либо Nginx/HAProxy). |
| **Config Drift Risk** | Риск расхождения конфигурации между узлами (актуально для Bare Metal/VM). |
| **SRE-влияние** | Влияние на Error Budget и необходимость алертинга/runbook. |

### Сравнительная таблица стратегий

| Стратегия | Downtime | Blast Radius | Откат | Сложность | Стоимость | База данных |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Recreate** | **Есть** | 100% | Медленный | Низкая | 1x | Любая |
| **Rolling Update** | Минимальный | Средний | Средний | Средний | 1x + surge | N-1 совместимость |
| **Blue-Green** | **Zero** | 100% | **Мгновенный** | Средняя | **2x** | N-1 совместимость |
| **Canary** | **Zero** | **Минимальный** | Быстрый | **Высокая** | 1x + canary | N-1 совместимость |
| **Shadow** | **Zero** | **0%** | Мгновенный | **Очень выс.** | **2x** | Изоляция (ReadOnly/Mock) |
| **A/B Testing** | **Zero** | Сегмент | Быстрый | Высокая | 1x+ | N-1 совместимость |

> Примечание по инфраструктуре: колонка «Стоимость» для традиционной среды означает не облачные инстансы, а физические/виртуальные серверы. Blue-Green и Shadow требуют дублирования *всего* пула обслуживания трафика (две копии фермы серверов + балансировщик), тогда как Canary — только небольшую долю дополнительных узлов.

### Архитектура и потоки трафика

Понимание того, *как* перемещается трафик, критично для выбора. Ниже — схемы распределения запросов между v1 (старая) и v2 (новая) версиями.

**Recreate** — последовательная замена, сервис недоступен:
```text
Время ──────────────────────────────────────────────►
v1:  [##########]        (остановлен)
v2:               (старт) [##########]
                  ↑ Downtime (разрыв)
```

**Rolling Update** — постепенная замена реплик, обе версии одновременно в строю:
```text
Этап 1:  v1 v1 v1 v1
Этап 2:  v2 v1 v1 v1
Этап 3:  v2 v2 v1 v1
Этап 4:  v2 v2 v2 v1
Этап 5:  v2 v2 v2 v2   ← готово
```

**Blue-Green** — две независимые среды, мгновенное переключение VIP/веса:
```text
          ┌─────────┐         ┌─────────┐
Трафик ──►│  Blue   │  switch │  Green  │
 (VIP)    │   v1    │ ──────► │   v2    │
          └─────────┘         └─────────┘
(до switch Green прогревается и smoke-тестится вне трафика)
```

**Canary** — малая доля трафика на v2, постепенное наращивание:
```text
L7-балансировщик:
  95% ──► v1
   5% ──► v2   (после валидации: 90/10 → 75/25 → 50/50 → 0/100)
```

**Shadow** — весь трафик идет на v1, копия (mirror) направляется на v2, ответ v2 игнорируется:
```text
Трафик ──► v1 (реальный ответ пользователю)
            │
            └─mirror─► v2 (ответ отбрасывается, анализируется только поведение)
```

**A/B Testing** — сегментация по признаку (заголовок/cookie/user-agent), а не по проценту:
```text
Пользователь с cookie ab=v2  ──► v2
Пользователь с cookie ab=v1  ──► v1
Остальные                    ──► v1 (контрольная группа)
```

### Техническое обоснование выбора (Why)

1.  **Recreate:** Выбирается, когда архитектура не допускает одновременной работы двух версий приложения с одной БД (например, монолит с тяжелыми миграциями, изменение типа колонки под блокировкой). Дешев в инфраструктуре, но требует окна обслуживания (maintenance window).
2.  **Rolling Update:** Стандарт для большинства stateless-микросервтисов и традиционных ферм приложений за Nginx/HAProxy, где допустимо кратковременное сосуществование версий. В традиционной среде реализуется поочередным выводом узлов из балансировщика (`drain`), обновлением и возвратом в пул.
3.  **Blue-Green:** Идеален для критических систем, где риск ошибки велик, а время отката должно быть минимальным. Требует удвоения ресурсов. В on-prem реализуется через VRRP/VIP (keepalived) или мгновенную смену весов в балансировщике.
4.  **Canary:** Выбор для высоконагруженных систем, где важно проверить логику на реальных пользователях перед полным релизом. Требует L7-маршрутизации и наблюдаемости (Judge) для автоматического принятия решения.
5.  **Shadow:** Используется для проверки производительности и корректности (нефункциональных требований) при глубоком рефакторинге или смене движка под полной нагрузкой, без риска для пользователя. Критично: v2 должна быть строго read-only или писать в изолированное хранилище.
6.  **A/B Testing:** Применяется, когда цель — бизнес-валидация (конверсия, удержание), а не техническая стабильность. Решение принимается по продуктовым метрикам, а не по техническим Golden Signals.

## Практические сценарии

### Жизненный цикл прогрессивного развертывания (Canary)

Стандартный процесс (применим и в Kubernetes, и в традиционной среде через Nginx/HAProxy + Judge-скрипт) включает этапы:
1.  **Stage 0 (Smoke):** Запуск v2 с 0% трафика. Проверка health-эндпоинтов и `Readiness`.
2.  **Stage 1 (Internal):** Направление трафика сотрудников или QA (по заголовку `x-dev-user` или cookie).
3.  **Stage 2 (Canary 5%):** Начало раскатки на случайных пользователей.
4.  **Analysis (Gating):** Автоматический Judge сравнивает 5xx ошибки и P95 Latency v1 vs v2, а также скорость прожигания Error Budget.
5.  **Promotion:** Постепенное увеличение (25% → 50% → 100%) с паузами для стабилизации метрик.

### Реализация через L7-балансировщик (Nginx / HAProxy) — традиционная среда

В on-prem среде роль L7-маршрутизатора выполняет Nginx или HAProxy. Ниже — рабочие конфигурации для каждой стратегии.

#### Canary через Nginx (split_clients)

Распределение по проценту с возможностью sticky-привязки по IP:

```nginx
http {
    # $request_id — случайная раскатка по доле трафика
    split_clients $request_id $canary_upstream {
        5%   canary_app;
        *    stable_app;
    }

    upstream stable_app {
        server 10.0.1.10:8080 max_fails=3 fail_timeout=30s;
        server 10.0.1.11:8080 max_fails=3 fail_timeout=30s;
    }
    upstream canary_app {
        server 10.0.1.20:8080 max_fails=3 fail_timeout=30s;
    }

    server {
        listen 80;
        location / {
            proxy_pass http://$canary_upstream;
            proxy_set_header Host $host;
            proxy_next_upstream error timeout http_502 http_503 http_504;
        }
    }
}
```

**Валидация:**
```bash
# → соотношение ~95 на stable, ~5 на canary
for i in $(seq 1 100); do curl -s http://lb.local/hostname; done | sort | uniq -c
# → после правки процента (например 25%) и reload:
nginx -t && systemctl reload nginx
```

#### Blue-Green через смену весов в Nginx (мгновенный switch)

Обе версии в одном upstream, переключение веса без простоя:

```nginx
upstream app {
    server 10.0.1.10:8080 weight=0;   # Blue (v1) — выведен из пула
    server 10.0.1.20:8080 weight=1;   # Green (v2) — принимает 100%
}
```
Переключение обратно (мгновенный откат) — меняем веса на `weight=1` / `weight=0` и делаем `systemctl reload nginx`.

*Альтернатива для полной изоляции сред — VRRP/VIP через keepalived:* Blue и Green находятся в разных фермах, VIP принадлежит активной. При switch Green поднимает `vrrp_instance` с большим приоритетом, VIP мигрирует за доли секунды (аналог «мгновенного переключения» в облаке).

#### Shadow через Nginx (mirror module)

```nginx
server {
    listen 80;
    location / {
        mirror /shadow;
        proxy_pass http://stable_app;
    }
    location = /shadow {
        internal;
        proxy_pass http://shadow_app$request_uri;
        # обязательно: подавить запись в prod БД на стороне v2
        proxy_set_header X-Shadow-Mode true;
    }
}
```
**Ограничение:** зеркальный трафик удваивает нагрузку на БД/внешние сервисы. v2 должна работать в режиме read-only или через mock-слой.

#### A/B Testing через Nginx (map по cookie/заголовку)

```nginx
map $cookie_ab_test $ab_target {
    default      stable_app;
    "v2"         canary_app;
}
map $http_x_ab_test $ab_target_hdr {
    default      $ab_target;
    "v2"         canary_app;
}

upstream stable_app { server 10.0.1.10:8080; }
upstream canary_app { server 10.0.1.20:8080; }

server {
    listen 80;
    location / {
        proxy_pass http://$ab_target_hdr;
    }
}
```
**Валидация:**
```bash
# → попадает на canary
curl --cookie "ab_test=v2" http://lb.local/
# → попадает на stable (контрольная группа)
curl http://lb.local/
```

#### Rolling Update через поочередный drain в HAProxy

```haproxy
backend app_servers
    balance roundrobin
    option httpchk GET /healthz
    http-check expect status 200
    server app1 10.0.1.10:8080 check inter 3s rise 2 fall 3
    server app2 10.0.1.11:8080 check inter 3s rise 2 fall 3
```
Процедура обновления одного узла:
```bash
# 1. Вывести узел из пула (drain) — HAProxy перестанет слать трафик после fall=3
# 2. Обновить приложение и перезапустить systemd-юнит
systemctl restart myapp
# 3. Дождаться UP в HAProxy
echo "show stat" | socat /var/run/haproxy.sock stdio | grep app1   # → status=UP
# 4. Повторить для следующего узла
```

### Реализация на уровне ОС и процессов (systemd) — Recreate / атомарная смена

Для монолитов и приложений без балансировщика атомарная смена версии достигается через symlink и рестарт юнита:

```bash
# Развертывание новой версии рядом со старой (immutable artifacts)
ln -sfn /opt/app/2.3.1 /opt/app/current
systemctl restart myapp

# Мгновенный откат (быстрее, чем переустановка)
ln -sfn /opt/app/2.3.0 /opt/app/current
systemctl restart myapp
```

Минимальный systemd-юнит с бережным выключением и проверкой запуска:
```ini
[Unit]
Description=MyApp
After=network.target

[Service]
Type=notify
ExecStart=/opt/app/current/bin/myapp
WorkingDirectory=/opt/app/current
TimeoutStartSec=60
TimeoutStopSec=30
Restart=on-failure
# Бережное завершение: процесс должен дождаться активных запросов
KillSignal=SIGTERM
# Живой лимит ресурсов (аналог In-Place Resize) — применяется без рестарта:
# systemctl set-property myapp.service MemoryMax=2G CPUQuota=150%

[Install]
WantedBy=multi-user.target
```

### Автоматизация через Ansible (Blue-Green на Bare Metal/VM)

Ниже — сокращенный плейбук, реализующий Blue-Green поверх двух групп серверов и HAProxy. Полный жизненный цикл — в материале по традиционной инфраструктуре (см. «См. также»).

```yaml
- hosts: green
  become: true
  tasks:
    - name: Download artifact v2
      get_url:
        url: "https://artifactory.local/my-app-{{ app_version }}.tar.gz"
        dest: "/tmp/my-app.tar.gz"
        checksum: "sha256:{{ lookup('url', 'https://artifactory.local/my-app.sha256') }}"
    - name: Extract to versioned dir
      unarchive:
        src: "/tmp/my-app.tar.gz"
        dest: "/opt/app/{{ app_version }}"
        remote_src: yes
    - name: Restart service
      systemd:
        name: myapp
        state: restarted
    - name: Wait for health
      uri:
        url: "http://localhost:8080/healthz"
        status_code: 200
      retries: 10
      delay: 3

- hosts: lb
  become: true
  tasks:
    - name: Switch upstream to green
      template:
        src: haproxy.cfg.j2
        dest: /etc/haproxy/haproxy.cfg
      notify: reload haproxy
  handlers:
    - name: reload haproxy
      systemd:
        name: haproxy
        state: reloaded
```

### Реализация через Gateway API (облачная оркестрация, Kubernetes)

Современная альтернатива Ingress и Istio, позволяющая управлять весами на уровне нативных ресурсов Kubernetes:

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: payments-canary
spec:
  parentRefs:
  - name: internal-gateway
  rules:
  - backendRefs:
    - name: payments-v1
      port: 8080
      weight: 90
    - name: payments-v2
      port: 8080
      weight: 10
```

### Влияние In-Place Resize на Rolling Update

Для приложений с долгим временем инициализации (Java/Spring, ML-модели) стандартный Rolling Update (создание нового пода) слишком медленен.
- **Подход (Kubernetes 2026):** Использование VPA (Vertical Pod Autoscaler) в режиме `InPlaceOrRecreate`. Если обновление касается только лимитов ресурсов, Kubernetes патчит работающий контейнер без его перезапуска, что исключает прогрев кэшей и повторное соединение с БД.
- **Аналог в традиционной среде:** `systemctl set-property myapp.service MemoryMax=2G` изменяет cgroup лимит на живом процессе без рестарта — тот же эффект для долго стартующих приложений.

### Работа с базами данных: паттерн Expand and Contract

Любая стратегия (кроме Recreate) требует сосуществования версий. Это обязывает использовать многоэтапные миграции БД:
1.  **Expand (Расширение):** Добавление новых колонок/таблиц, которые v1 игнорирует, а v2 использует. БД поддерживает оба формата. Новые колонки делают NULL-able, чтобы не ломать запись старой версии.
2.  **Migrate (Миграция):** Перенос данных из старого формата в новый в фоновом режиме (batched UPDATE / backfill), без блокировок больших таблиц.
3.  **Contract (Сжатие):** После того как v2 стала стабильной и v1 удалена, старые колонки/таблицы удаляются.

Практический пример (добавление колонки без простоя):
```sql
-- Expand: безопасно для работающей v1
ALTER TABLE orders ADD COLUMN total_net NUMERIC(12,2) NULL;

-- Migrate: фоновый батч-перенос (по 1000 строк, чтобы не блокировать таблицу)
UPDATE orders SET total_net = total WHERE total_net IS NULL
  AND id BETWEEN :batch_start AND :batch_end;

-- Contract (после удаления v1 и проверки):
ALTER TABLE orders DROP COLUMN total;
```

### SRE-практики: Error Budget и автоматический откат (Judge)

В традиционной среде роль Judge выполняет связка Prometheus + gate-шаг в CI/Ansible. Ключевой принцип — решение принимается на основе Error Budget, а не «на глаз».

Пример правила алертинга на прожигание бюджета канарейкой (Prometheus):
```yaml
- alert: CanaryErrorBudgetBurn
  expr: |
    (
      sum(rate(http_requests_total{canary="true",code=~"5.."}[5m]))
      /
      sum(rate(http_requests_total{canary="true"}[5m]))
    ) / 0.01 > 14.4   # >14.4x burn rate = прожиг 2% бюджета за 1ч
  for: 5m
  labels:
    severity: critical
  annotations:
    summary: "Canary v2 сжигает Error Budget — требуется откат"
```
Gate-шаг в пайплайне (псевдокод):
```bash
# Запрос метрики в Prometheus перед продвижением стадии
err_rate=$(curl -s "http://prom.local:9090/api/v1/query?query=\
sum(rate(http_requests_total{canary=\"true\",code=~\"5..\"}[5m]))\
/sum(rate(http_requests_total{canary=\"true\"}[5m]))" | jq '.data.result[0].value[1]')

if awk "BEGIN {exit !($err_rate > 0.01)}"; then
  echo "ОШИБКА: error rate $err_rate превышает SLO 1% — блокируем продвижение"
  exit 1
fi
# → продвижение к следующей стадии canary
```

### Мониторинг и наблюдаемость (Golden Signals)

Для валидации релиза собирают и сравнивают v1 vs v2 по четырем сигналам. Минимальный набор (Prometheus + node_exporter, работает on-prem):

```yaml
# Примеры PromQL для Judge
# Errors (доля 5xx):
sum(rate(http_requests_total{code=~"5.."}[5m])) / sum(rate(http_requests_total[5m]))
# Latency P95 (требуется histogram-метрика):
histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket[5m])) by (le))
# Traffic (RPS):
sum(rate(http_requests_total[5m]))
# Saturation (доступная память узла):
node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes
```
**Валидация (команда):**
```bash
curl -s "http://prom.local:9090/api/v1/query?query=\
histogram_quantile(0.95,%20sum(rate(http_request_duration_seconds_bucket[5m]))%20by%20(le))" \
  | jq '.data.result[0].value[1]'   # → "0.142" (P95 = 142 мс)
```

### Устранение неполадок (Troubleshooting)

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Node OOM во время Rollout** | Слишком большой `maxSurge`. | Уменьшить `maxSurge` или добавить узлы в кластер. |
| **Canary Analysis Timeout** | Недостаточно трафика для сбора статистики. | Увеличить время анализа или долю Canary. |
| **Stuck in Pending** | Нехватка ресурсов (CPU/RAM/PVC) для новых подов. | Проверить `kubectl describe pod` и квоты в Namespace. |
| **Sticky Session Break** | Неверная настройка балансировщика при Canary. | Использовать `Cookie-based affinity` в Gateway API / Service Mesh. |
| **Shadow Side Effects** | Зеркальный трафик вызвал запись в Prod БД. | Использовать Mock-сервисы или Read-only режим для Shadow. |
| **VIP не мигрирует (keepalived)** | Firewall блокирует VRRP (протокол 112) или равный priority. | Разрешить `proto 112` между узлами; задать разный `priority`. |
| **Nginx upstream «flapping»** | Слишком агрессивные `inter`/`fall` или нестабильный health-эндпоинт. | Увеличить `rise`/`fall` до 2–3; проверить, что `/healthz` не ложноположителен. |
| **Canary не получает трафик (Nginx)** | `split_clients` привязан к `$remote_addr` за NAT → все на stable. | Использовать `$request_id` для случайной раскатки или ACL по заголовку. |
| **DNS TTL ломает Zero-Downtime** | Клиенты кэшируют старый IP при DNS-switch. | Использовать L7-веса/VRRP вместо DNS; снизить TTL только как крайняя мера. |
| **Clock Drift** | Уплывание времени на VM ломает TLS/лидерство. | `chrony` с несколькими stratum-1/PTP источниками; `chronyc tracking`. |
| **Config Drift (Bare Metal)** | Сервер «накопил» ручные изменения. | Ежедневный `ansible-playbook --check --diff`; переход на Immutable Images. |

## Дополнительная информация

### Сравнение инструментов развертывания

Выбор между Helm и Kustomize (Kubernetes) зависит от требований к динамике и упаковке:

| Характеристика | Kustomize | Helm |
| :--- | :--- | :--- |
| Тип | Наложения (Overlays) | Шаблонизация (Go Templates) |
| Сложность | Низкая (Декларативно) | Высокая (Императивная логика) |
| Версионирование | Отсутствует нативно | Чарты (Charts) с версиями |
| 2026 Trend | Идеален для GitOps | Идеален для COTS-приложений |

Для **традиционной инфраструктуры (Bare Metal / VM)** экосистема иная:

| Инструмент | Роль | Подход | Когда использовать |
| :--- | :--- | :--- | :--- |
| **Ansible** | Push/Pull конфигурация и деплой | Мутабельный | Тяжелые БД, долгоживущие серверы, JIT-доступ. |
| **Packer** | Сборка Golden Image | Иммутабельный | Масштабируемые stateless-сервисы, минимизация дрифта. |
| **Terraform** | Провижининг VM/сетей | Иммутабельный | Управление гипервизором / bare-metal через API. |
| **Nomad** | Единый Control Plane (бинарники + контейнеры) | Гибридный | Гетерогенные нагрузки без Kubernetes. |
| **HAProxy / Nginx** | L7-маршрутизация для Canary/Blue-Green | — | Любая стратегия, требующая деления трафика. |

### Лучшие практики и эксплуатация

1. **Одна версия в production одновременно для критичных миграций** — используйте Recreate + окно обслуживания, если схема БД не допускает N-1.
2. **Автоматический откат (Auto-Rollback)** — Judge должен не только блокировать продвижение, но и инициировать откат при превышении порога ошибок. В on-prem — шаг в Ansible/CI, в K8s — Argo Rollouts/Flagger.
3. **Health-эндпоинт проверяет зависимости**, а не только `200 OK`. Иначе балансировщик пустит трафик в «живой, но мертвый» экземпляр.
4. **Graceful shutdown обязателен** для Rolling/Canary — иначе активные запросы получат 502 при выводе узла из пула.
5. **Разделяйте продвижение и видимость функции** — Canary (трафик) + Feature Flag (логика) закрывают разные риски.
6. **Runbook на каждый откат** — оператор должен за ≤5 минут выполнить откат по письменной инструкции, без разбора причин в моменте.
7. **Postmortem после каждого failed release** — без поиска виноватого, с action-items по предотвращению.

### Граничные случаи и ограничения

- **Долгие транзакции БД** блокируют этап Contract (удаление старой колонки). Решение: выполнять DROP в окно низкой нагрузки под `LOCK TIMEOUT`.
- **Session Affinity ломает Canary** — sticky-сессия может «приклеить» пользователя к v1 даже при переключении весов. Используйте внешнее хранилище сессий (Redis) или пересаживайте cookie при релизе.
- **Shadow пишет в prod** — главный риск теневой стратегии. Обязателен read-only режим или mock-слой на стороне v2.
- **DNS TTL** делает DNS-based Blue-Green не zero-downtime для клиентов с агрессивным кэшированием. Предпочтительны L7-веса или VRRP/VIP.
- **Малый объем трафика** делает Canary-анализ статистически незначимым — нужно либо увеличить долю, либо продлить окно анализа.
- **Config Drift** в Bare Metal медленно «стареет» серверы; без Immutable Images рано или поздно возникает расхождение между узлами.

### См. также

- **[Сине-зеленое развертывание](./blue_green_deployment.md)** — глубокое погружение в Blue-Green.
- **[Канареечное развертывание](./canary_deployment.md)** — детальная реализация и метрики.
- **[Развертывание в традиционной инфраструктуре](./traditional_infrastructure.md)** — Bare Metal / VM паттерны и Ansible/Packer.

---

### Совет по собеседованию

**Вопрос:** В чем фундаментальное различие между Canary и Blue-Green в контексте управления рисками?

**Ответ:** **Blue-Green** минимизирует время отката (мгновенное переключение), но подвергает 100% пользователей риску при переключении на v2. **Canary** минимизирует радиус поражения (Blast Radius), подвергая риску лишь малую долю трафика, но требует более сложной наблюдаемости (Judge, Error Budget) для автоматического принятия решения о раскатке.
