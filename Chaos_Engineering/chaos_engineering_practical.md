# Chaos Engineering — практическое руководство (LitmusChaos, Game Days)

## Определения

**Chaos Engineering** — практика контролируемых экспериментов на инфраструктуре для обнаружения системных уязвимостей до того, как они вызовут инцидент в production. Ключевой принцип: эксперименты проводятся в контролируемой среде с автоматическим прерыванием при критической деградации.

**Game Day** — запланированное мероприятие, в ходе которого команда имитирует реальные инциденты (отказы серверов, сетевые сбои, утечки памяти) и отрабатывает процедуры реагирования в реальном времени. Цель — проверить people, process, technology.

**Steady State Hypothesis** — предположение о том, что система находится в стабильном состоянии (HTTP 200, latency < 200ms, error rate < 1%). Эксперимент считается успешным, если steady state сохраняется во время fault injection.

**Blast Radius** — область воздействия эксперимента. Определяет, сколько ресурсов/пользователей будет затронуто. В production blast radius должен быть минимальным (1-5% трафика).

**Stop-switch (Аварийная остановка)** — автоматический механизм прекращения эксперимента при нарушении SLO. Может быть реализован через алерты Prometheus/Alertmanager или встроенный в платформу (Chaos Mesh, Litmus) emergency stop.

**Probe (Проба)** — активная проверка steady state во время эксперимента. Проверяет доступность сервиса (HTTP 200), время отклика, количество рестартов. Без probes эксперимент — не научный метод.

**Fault Injection (Инъекция сбоев)** — целенаправленное внесение дефекта в систему для проверки ее поведения. Подмножество Chaos Engineering, фокусирующееся на конкретном условии сбоя.

**Resilience (Устойчивость)** — способность системы адаптироваться к изменениям и поглощать сбои без потери функциональности. Хаос-инженерия является инструментом для достижения resilience.

**MTTR (Mean Time to Recovery)** — время от прекращения инъекции до возвращения системы в steady state. Чем ниже MTTR, тем лучше отлажены процессы восстановления.

**MTTD (Mean Time to Detect)** — время от начала инъекции до срабатывания первого алерта. Показывает качество observability.

## Основные концепции

### Жизненный цикл хаос-эксперимента

Качественный эксперимент проходит через шесть этапов:

```
1. Определить steady state → как выглядит "норма"?
2. Сформулировать гипотезу → "сервис выдержит отказ пода"
3. Спроектировать эксперимент → какую неудачу имитируем?
4. Выполнить в staging → проверить, что всё работает
5. Выполнить в production (canary) → с Blast Radius 1-5%
6. Проанализировать результаты → нашли слабые места?
7. Исправить обнаруженные проблемы
8. Повторить
```

### Принципы безопасности

1. **Всегда начинайте с staging** — первое применение инструмента обязательно в тестовой среде.
2. **Ограничивайте Blast Radius** — начинайте с 1% трафика или одного пода. Никогда не применяйте `mode: all` в production без проверки.
3. **Имейте emergency stop** — автоматическое прерывание при критических метриках. Один человек должен иметь физический доступ к кнопке «остановить всё».
4. **Мониторьте в реальном времени** — дашборды Grafana во время эксперимента.
5. **Уведомляйте команду** — все должны знать о запланированном эксперименте. Используйте общий чат и статус-страницу.
6. **Не проводите эксперименты** во время критических периодов (релизы, праздники, маркетинговые акции).

### Компоненты инструментария

Качественный инструмент Chaos Engineering управляет pipeline из пяти этапов:

```
1. Target Selection (Выбор цели)
   └── Label Selectors / IP / Hostname
   └── Blast Radius filter (только 1–5% ресурсов)

2. Fault Injection (Внесение сбоя)
   └── Network: delay, loss, partition (tc, iptables)
   └── Compute: CPU hog, memory hog, IO stress
   └── Infrastructure: pod kill, node drain, disk fill

3. Monitoring & Probes (Наблюдение)
   └── HTTP/GRPC probes (Litmus, Chaos Mesh)
   └── Prometheus metrics pull
   └── Business metrics validation

4. Stop Condition (Условие остановки)
   └── Time-based: TOTAL_CHAOS_DURATION истек
   └── Metric-based: error_rate > SLO
   └── Probe-based: health check вернул 500

5. Cleanup & Analysis (Очистка и анализ)
   └── Автоматическое удаление CRD/политик
   └── Генерация отчета: steady state upheld?
```

**Ключевые компоненты:**
- **Chaos Controller / Daemon:** Основной процесс, который принимает CRD/политики и управляет инъекцией. В Chaos Mesh — `chaos-controller-manager` и `chaos-daemon`. В LitmusChaos — `chaos-operator`.
- **Sidecar / Agent:** Дополнительный контейнер или демон, который работает на целевом узле и выполняет фактическую инъекцию сбоя (например, `chaos-daemon` использует `tc` для сетевых задержек).
- **Exporter:** Сбор метрик об эксперименте (статус, длительность,blast radius). В Chaos Mesh — `chaos-mesh-exporter`.

## Практические сценарии

### LitmusChaos — установка и настройка

#### Предварительные требования

```bash
# Kubernetes 1.24+
kubectl version --short
# → Client Version: v1.28.0
# → Server Version: v1.28.0

# Helm 3
helm version
# → version.BuildInfo{Version:"v3.14.0", ...}

# Кластер с доступом
kubectl cluster-info
# → Kubernetes control plane is running at https://<api>:6443
# → CoreDNS is running at https://<api>:6443/api/v1/namespaces/kube-system/services/kube-dns:dns/proxy
```

#### Установка LitmusChaos 3.x

```bash
# Добавление Helm-репозитория
helm repo add litmuschaos https://litmuschaos.github.io/litmus-helm
helm repo update

# Установка в отдельный namespace
kubectl create namespace litmus

helm install litmus litmuschaos/litmus \
  --namespace litmus \
  --set portalServer.enabled=true \
  --set portalServer.service.type=LoadBalancer

# Проверка установки
kubectl get pods -n litmus
# → NAME                                        READY   STATUS    RESTARTS   AGE
# → litmus-chaos-controller-manager-xxx         1/1     Running   0          2m
# → litmus-chaos-daemon-xxx                     1/1     Running   0          2m
# → litmus-frontend-xxx                         1/1     Running   0          2m
```

#### Установка через kubectl (без Helm)

```bash
# Litmus Control Plane
kubectl apply -f https://litmuschaos.github.io/litmus/litmus-3.0.0.yaml

# Проверка CRDs
kubectl get crd | grep litmus
# → chaosengines.litmuschaos.io
# → chaosexperiments.litmuschaos.io
# → chaosresults.litmuschaos.io
```

#### Настройка Litmus Portal

```bash
# Открытие Portal
kubectl port-forward svc/litmus-portal-frontend -n litmus 8080:8080

# Доступ: http://localhost:8080
# По умолчанию: admin / litmus
```

### Chaos Mesh — установка

#### Установка через Helm

```bash
helm repo add chaos-mesh https://charts.chaos-mesh.org
helm repo update

kubectl create namespace chaos-mesh

helm install chaos-mesh chaos-mesh/chaos-mesh \
  --namespace chaos-mesh \
  --set chaosDaemon.runtime=containerd \
  --set chaosDaemon.socketPath=/run/containerd/containerd.sock \
  --version 2.6.0

# Проверка
kubectl get pods -n chaos-mesh
# → NAME                                        READY   STATUS    RESTARTS   AGE
# → chaos-mesh-controller-manager-xxx           1/1     Running   0          2m
# → chaos-mesh-daemon-xxx                       1/1     Running   0          2m
```

### LitmusChaos — практические эксперименты

#### Эксперимент 1: Pod Delete (удаление пода)

Проверка: выживет ли сервис при потере пода?

```yaml
apiVersion: litmuschaos.io/v1alpha1
kind: ChaosEngine
metadata:
  name: pod-delete-experiment
  namespace: litmus
spec:
  appinfo:
    appns: production        # Namespace приложения
    applabel: app=api-gateway # Label целевого пода
    appkind: deployment
  chaosServiceAccount: litmus-admin
  experiments:
    - name: pod-delete
      spec:
        components:
          env:
            - name: TOTAL_CHAOS_DURATION
              value: "60"        # Длительность: 60 секунд
            - name: CHAOS_INTERVAL
              value: "10"        # Интервал между удалениями
            - name: FORCE
              value: "false"     # Graceful shutdown
        probe:
          - name: check-availability
            type: httpProbe
            httpProbe/inputs:
              url: "http://api-gateway.production.svc.cluster.local/health"
              method:
                get:
                  criteria: ==
                  responseCode: "200"
            mode: Continuous
            runProperties:
              probeTimeout: 5000
              interval: 2000
              retry: 3
```

#### Эксперимент 2: Pod CPU Hog (нагрузка на CPU)

Проверка: как ведёт себя сервис при 100% CPU?

```yaml
apiVersion: litmuschaos.io/v1alpha1
kind: ChaosEngine
metadata:
  name: cpu-hog-experiment
  namespace: litmus
spec:
  appinfo:
    appns: production
    applabel: app=payment-service
    appkind: deployment
  chaosServiceAccount: litmus-admin
  experiments:
    - name: pod-cpu-hog
      spec:
        components:
          env:
            - name: TOTAL_CHAOS_DURATION
              value: "120"
            - name: CPU_CORES
              value: "2"          # Количество ядер для нагрузки
            - name: CPU_LOAD
              value: "100"        # Процент загрузки
        probe:
          - name: check-response-time
            type: httpProbe
            httpProbe/inputs:
              url: "http://payment-service.production.svc.cluster.local/health"
              method:
                get:
                  criteria: ==
                  responseCode: "200"
            mode: Continuous
            runProperties:
              probeTimeout: 10000
              interval: 5000
```

#### Эксперимент 3: Network Latency (сетевая задержка)

Проверка: как Circuit Breaker реагирует на задержки 500мс?

```yaml
apiVersion: litmuschaos.io/v1alpha1
kind: ChaosEngine
metadata:
  name: network-latency-experiment
  namespace: litmus
spec:
  appinfo:
    appns: production
    applabel: app=catalog-service
    appkind: deployment
  chaosServiceAccount: litmus-admin
  experiments:
    - name: pod-network-latency
      spec:
        components:
          env:
            - name: TOTAL_CHAOS_DURATION
              value: "300"
            - name: NETWORK_LATENCY
              value: "500"       # 500ms задержки
            - name: JITTER
              value: "100"       # Разброс задержки
            - name: DESTINATION_IPS
              value: "10.0.0.0/8"  # Целевые IP
        probe:
          - name: check-circuit-breaker
            type: httpProbe
            httpProbe/inputs:
              url: "http://catalog-service.production.svc.cluster.local/health"
              method:
                get:
                  criteria: ==
                  responseCode: "200"
            mode: Continuous
            runProperties:
              probeTimeout: 5000
              interval: 2000
```

#### Эксперимент 4: Pod Memory Hog (нагрузка на RAM)

Проверка: что происходит при OOM Kill?

```yaml
apiVersion: litmuschaos.io/v1alpha1
kind: ChaosEngine
metadata:
  name: memory-hog-experiment
  namespace: litmus
spec:
  appinfo:
    appns: production
    applabel: app=user-service
    appkind: deployment
  chaosServiceAccount: litmus-admin
  experiments:
    - name: pod-memory-hog
      spec:
        components:
          env:
            - name: TOTAL_CHAOS_DURATION
              value: "120"
            - name: MEMORY_HOG
              value: "500"      # 500MB потребления
            - name: MEMORY_CONTAINER_LIMIT
              value: "100"      # Процент от лимита контейнера
        probe:
          - name: check-pod-restarts
            type: k8sProbe
            k8sProbe/inputs:
              command: |
                kubectl get pods -n production -l app=user-service -o json | jq '.items[].status.containerStatuses[].restartCount'
              retries: 5
              interval: 10000
              probeTimeout: 5000
```

### Chaos Mesh — практические эксперименты

#### Network Delay

```yaml
apiVersion: chaos-mesh.org/v1alpha1
kind: NetworkChaos
metadata:
  name: network-delay-catalog
spec:
  action: delay
  mode: one
  selector:
    namespaces:
      - production
    labelSelectors:
      app: catalog
  delay:
    latency: "200ms"
    correlation: "25"
    jitter: "50ms"
  duration: "10m"
  direction: to
```

#### Pod Kill

```yaml
apiVersion: chaos-mesh.org/v1alpha1
kind: PodChaos
metadata:
  name: pod-kill-api
  namespace: chaos-mesh
spec:
  action: pod-kill
  mode: one
  selector:
    namespaces:
      - production
    labelSelectors:
      app: api-gateway
  gracePeriod: 0
  duration: "5m"
```

#### IO Chaos (дисковые ошибки)

```yaml
apiVersion: chaos-mesh.org/v1alpha1
kind: IOChaos
metadata:
  name: io-delay-database
  namespace: chaos-mesh
spec:
  action: latency
  mode: one
  selector:
    namespaces:
      - production
    labelSelectors:
      app: postgres
  delay: "100ms"
  volumePath: /var/lib/postgresql/data
  duration: "5m"
```

### Pumba — хаос для Docker-контейнеров

```bash
# Пауза контейнера на 30 секунд
pumba pause --duration 30s <container_id>

# Удаление контейнера (SIGKILL)
pumba kill --signal SIGKILL <container_id>

# Сетевая задержка 500мс
pumba netem --duration 60s --delay 500ms <container_id>

# Потеря пакетов 10%
pumba netem --duration 60s --loss 10% <container_id>

# Остановка всех контейнеров образа
pumba stop --duration 60s <image_name>
```

### Toxiproxy + k6 — тестирование Resilience

```bash
# Создаем прокси для целевого сервиса
docker run -d --name toxiproxy -p 8474:8474 -p 8666:8666 shopify/toxiproxy

# Добавляем задержку 300мс
curl -X POST http://localhost:8474/proxies/api-service/toxics \
  -H "Content-Type: application/json" \
  -d '{"name":"latency","type":"latency","attributes":{"latency":300}}'

# Генерация нагрузки через k6
k6 run --vus 50 --duration 5m script.js
```

### Game Day — шаблон проведения

#### Структура Game Day Runbook

```markdown
# Game Day Runbook: [Название сценария]

## Информация
- Дата: YYYY-MM-DD HH:MM UTC
- Длительность: X часов
- Ответственный: @имя
- Уведомлены: #team-chat

## Участники
- Facilitator (модератор): @имя
- Observer (наблюдатель): @имя
- Responder (реагирующий): @имя

## Цели
1. Проверить время реакции команды на инцидент
2. Оценить эффективность алертинга
3. Проверить процедуры эскалации
4. Оценить время восстановления (MTTR)

## Сценарий
1. Внедрить fault injection (описание)
2. Наблюдать за алертами и метриками
3. Отработать процедуры реагирования
4. Восстановить систему

## Fault Injection
- Инструмент: LitmusChaos / Chaos Mesh
- Эксперимент: [название]
- Blast Radius: [1% / 5% / specific pods]
- Длительность: [X минут]

## Ожидаемые алерты
- [ ] Alert: HighErrorRate (severity: critical)
- [ ] Alert: PodRestarts (severity: warning)
- [ ] Alert: HighLatency (severity: warning)

## Метрики для наблюдения
- Error rate (Grafana dashboard)
- P99 latency
- Pod restart count
- HTTP status code distribution

## Критерии успеха
- [ ] Алерты сработали в течение < 5 минут
- [ ] Команда обнаружила инцидент в течение < 10 минут
- [ ] Время реагирования < 15 минут
- [ ] Система восстановлена без ручного вмешательства
- [ ] Post-mortem документ создан

## Результаты
| Метрика | Ожидание | Факт |
| --- | --- | --- |
| Detection time | < 5 min | |
| Response time | < 15 min | |
| Recovery time | < 30 min | |
| Alerter accuracy | 100% | |
```

#### Game Day: Сценарий 1 — Database Failover

```
Цель: Проверить automatic failover PostgreSQL primary → standby

Этапы:
1. Остановить PostgreSQL primary (pod delete или SIGTERM)
2. Наблюдать:
   - Алерт: "PostgreSQL primary down" срабатывает?
   - Patroni/Repmgr выполняет failover?
   - Приложение переключается на новый primary?
3. Восстановить старый primary как standby
4. Проверить data consistency

Ожидаемый результат:
- Failover завершается за < 60 секунд
- Нет потери данных
- Приложение продолжает работать
```

#### Game Day: Сценарий 2 — Cache Failure (Redis down)

```
Цель: Проверить поведение при потере кеша

Этапы:
1. Остановить Redis кластер (все master-ноды)
2. Наблюдать:
   - Приложение переключается на database (без кеша)?
   - Database выдерживает дополнительную нагрузку?
   - Алерты: "Redis down", "High DB load"
3. Восстановить Redis
4. Проверить cache warming

Ожидаемый результат:
- Приложение работает без кеша (деградация, но не отказ)
- Database не падает под нагрузкой
- Cache warming работает корректно
```

#### Game Day: Сценарий 3 — Network Partition

```
Цель: Проверить поведение при split-brain

Этапы:
1. Разделить сеть между нодами кластера (NetworkChaos)
2. Наблюдать:
   - Как ведут себя leader-election?
   - Есть ли split-brain?
   - Какие сервисы отказывают?
3. Восстановить сеть
4. Проверить консистентность данных

Ожидаемый результат:
- Leader election работает корректно
- Нет split-brain
- Данные консистентны после восстановления
```

## Установка и настройка

### LitmusChaos — systemd service (self-hosted)

Если Litmus Portal развертывается на bare-metal сервере:

```bash
# /etc/systemd/system/litmus-portal.service
[Unit]
Description=Litmus Portal
After=network.target

[Service]
Type=simple
WorkingDirectory=/opt/litmus
ExecStart=/usr/local/bin/litmus-portal
Restart=always
RestartSec=5
Environment="PORT=8080"
Environment="LOG_LEVEL=info"

[Install]
WantedBy=multi-user.target
```

```bash
# Применение и запуск
sudo systemctl daemon-reload
sudo systemctl enable --now litmus-portal
sudo systemctl status litmus-portal
# → Active: active (running) since ...
```

### Chaos Mesh — systemd daemon (bare-metal node)

Для инъекции сбоев на физических серверах:

```bash
# /etc/systemd/system/chaos-daemon.service
[Unit]
Description=Chaos Mesh Daemon
After=network.target

[Service]
Type=simple
ExecStart=/usr/local/bin/chaos-daemon --runtime containerd --socketpath /run/containerd/containerd.sock
Restart=always
RestartSec=5
LimitMEMLOCK=infinity

[Install]
WantedBy=multi-user.target
```

```bash
# Применение и запуск
sudo systemctl daemon-reload
sudo systemctl enable --now chaos-daemon
sudo systemctl status chaos-daemon
# → Active: active (running) since ...

# Проверка логов
sudo journalctl -u chaos-daemon -f
# → time="2024-01-15T10:00:00Z" level=info msg="Chaos Daemon started"
```

### Проверка установки

```bash
# Проверка подов
kubectl get pods -n litmus
kubectl get pods -n chaos-mesh

# Проверка CRDs
kubectl get crd | grep litmus
kubectl get crd | grep chaos-mesh

# Проверка daemonset (chaos-daemon на всех нодах)
kubectl get daemonset -n chaos-mesh
# → NAME            DESIRED   CURRENT   READY   UP-TO-DATE   AVAILABLE
# → chaos-daemon    3         3         3       3            3

# Проверка systemd юнитов (bare-metal)
systemctl status litmus-portal chaos-daemon
```

## Операции и команды

### Жизненный цикл эксперимента

Полный цикл chaos-эксперимента состоит из шести этапов:

| Этап | Операция | Инструмент / Команда |
|:---|:---|:---|
| **1. Определение steady state** | Сбор baseline метрик | `Prometheus: histogram_quantile(0.99, sum by (le) (rate(http_request_duration_seconds_bucket[1h])))` |
| **2. Формулировка гипотезы** | Описание сценария в runbook | Markdown, Git |
| **3. Выбор blast radius** | Ограничение namespace / label | `kubectl apply -f chaos-experiment.yaml` с `mode: one` |
| **4. Настройка probes** | HTTP/tcp/exec пробы | Litmus probes, Chaos Mesh prober |
| **5. Выполнение** | Запуск эксперимента | `kubectl apply -f network-delay.yaml` |
| **6. Остановка и анализ** | Emergency stop | `kubectl delete -f network-delay.yaml`, Alertmanager silence |

### Chaos Mesh — управление экспериментами

```bash
# Применить эксперимент (сетевая задержка)
kubectl apply -f network-delay.yaml

# Проверить статус эксперимента
kubectl get networkchaos -n chaos-mesh

# Посмотреть логи chaos daemon
kubectl logs -n chaos-mesh -l app=chaos-daemon -f

# Принудительная остановка эксперимента
kubectl delete -f network-delay.yaml

# Проверить CRDs
kubectl get crd | grep chaos-mesh
```

### LitmusChaos — управление экспериментами

```bash
# Применить ChaosEngine
kubectl apply -f chaos-engine.yaml

# Проверить статус эксперимента
kubectl get chaosengine -n litmus

# Посмотреть результат
kubectl describe chaosresult -n litmus

# Удалить эксперимент
kubectl delete -f chaos-engine.yaml

# Проверить CRDs
kubectl get crd | grep litmus
```

### Pumba — хаос для Docker-контейнеров

```bash
# Пауза контейнера на 30 секунд
pumba pause --duration 30s <container_id>

# Удаление контейнера (SIGKILL)
pumba kill --signal SIGKILL <container_id>

# Сетевая задержка 500мс
pumba netem --duration 60s --delay 500ms <container_id>

# Потеря пакетов 10%
pumba netem --duration 60s --loss 10% <container_id>

# Остановка всех контейнеров образа
pumba stop --duration 60s <image_name>
```

### Toxiproxy — TCP proxy anomalies

```bash
# Создание прокси
curl -X POST http://localhost:8474/proxies -d '{"name":"app","listen":"0.0.0.0:8080","upstream":"app:8080","enabled":true}'

# Добавление задержки 5000мс
curl -X POST http://localhost:8474/proxies/app/toxics -d '{"name":"latency","type":"latency","attributes":{"latency":5000}}'

# Потеря пакетов 10%
curl -X POST http://localhost:8474/proxies/app/toxics -d '{"name":"loss","type":"loss","attributes":{"percentage":10}}'

# Удаление toxic
curl -X DELETE http://localhost:8474/proxies/app/toxics/latency

# Список прокси
curl http://localhost:8474/proxies
```

### Cleanup — обязательные шаги после эксперимента

```bash
# 1. Удалить все ресурсы chaos
kubectl delete -f chaos-experiment.yaml
kubectl delete -f chaos-engine.yaml

# 2. Проверить отсутствие остаточных ресурсов
kubectl get networkchaos,podchaos,stresschaos -n chaos-testing

# 3. Убедиться, что метрики вернулись к baseline
# Проверка в Prometheus: latency p99, error rate

# 4. Очистить алерты/силуты
# Alertmanager: убрать silence, если создавались временные

# 5. Архивировать результаты
# Сохранить логи, графики, вывод probes в runbook
```

### Validation — проверка steady state после cleanup

```bash
# Проверка доступности сервиса
curl -f http://api-gateway.production.svc.cluster.local/health
# → OK

# Проверка количества рестартов подов
kubectl get pods -n production -l app=api-gateway -o json | jq '.items[].status.containerStatuses[].restartCount'
# → 0

# Проверка метрик в Prometheus
# → latency p99 вернулся к baseline
# → error rate < 0.1%
# → RPS вернулся к baseline
```

## Автоматизация

### CI-CD Pipeline с Chaos Testing

```yaml
# .gitlab-ci.yml
stages:
  - build
  - test
  - chaos
  - deploy

chaos-test:
  stage: chaos
  script:
    - kubectl apply -f chaos-experiments/pod-delete.yaml
    - sleep 120  # Ждём завершения эксперимента
    - kubectl delete -f chaos-experiments/pod-delete.yaml
    # Проверяем, что алерты НЕ сработали (system is resilient)
    - |
      ALERTS=$(curl -s http://alertmanager:9093/api/v2/alerts | jq 'length')
      if [ "$ALERTS" -gt 0 ]; then
        echo "Chaos experiment triggered alerts - system not resilient"
        exit 1
      fi
  rules:
    - if: '$CI_PIPELINE_SOURCE == "schedule"'  # Запуск по расписанию
```

### Automated Game Day (LitmusChaos Workflow)

```yaml
apiVersion: litmuschaos.io/v1alpha1
kind: ChaosWorkflow
metadata:
  name: game-day-workflow
  namespace: litmus
spec:
  entrypoint: game-day
  templates:
    - name: game-day
      steps:
        - - name: step-1-delete-pod
            template: pod-delete
        - - name: step-2-check-availability
            template: http-probe
        - - name: step-3-wait
            template: wait-step
        - - name: step-4-delete-db
            template: pod-delete-db

    - name: pod-delete
      chaosEngine:
        spec:
          experiments:
            - name: pod-delete
              spec:
                components:
                  env:
                    - name: TOTAL_CHAOS_DURATION
                      value: "60"

    - name: http-probe
      chaosEngine:
        spec:
          experiments:
            - name: pod-delete
              spec:
                probe:
                  - name: check-availability
                    type: httpProbe
                    httpProbe/inputs:
                      url: "http://api-gateway:8080/health"
                      method:
                        get:
                          criteria: ==
                          responseCode: "200"
                    mode: Continuous

    - name: wait-step
      container:
        image: busybox
        command: ["sleep", "300"]  # 5 минут ожидания
```

### Cron — планирование экспериментов

```bash
# Пример: ежедневный хаос-тест в 02:00 через CronJob
kubectl apply -f - <<EOF
apiVersion: batch/v1
kind: CronJob
metadata:
  name: daily-chaos-test
  namespace: chaos-testing
spec:
  schedule: "0 2 * * *"
  jobTemplate:
    spec:
      template:
        spec:
          serviceAccountName: chaos-admin
          restartPolicy: Never
          containers:
          - name: chaos-runner
            image: bitnami/kubectl:latest
            command:
            - /bin/sh
            - -c
            - |
              kubectl apply -f /chaos/pod-delete.yaml
              sleep 120
              kubectl delete -f /chaos/pod-delete.yaml
              # Проверка метрик
              ERROR_RATE=$(curl -s http://prometheus:9090/api/v1/query?query=sum(rate(http_requests_total{status=~"5.."}[5m]))/sum(rate(http_requests_total[5m])) | jq '.data.result[0].value[1]' -r)
              if (( $(echo "$ERROR_RATE > 0.05" | bc -l) )); then
                echo "FAIL: Error rate $ERROR_RATE exceeds 5%"
                exit 1
              fi
EOF
```

## Устранение неполадок

| Проблема | Вероятная причина | Решение |
|:---|:---|:---|
| **LitmusChaos не находит поды** | Неверный namespace или label | Проверьте `appns` и `applabel` в ChaosEngine |
| **Chaos Mesh CRD не установлены** | Неполная установка | `kubectl apply -f https://chaos-mesh.org/manifests/chaos-mesh.yaml` |
| **Probe не работает** | NetworkPolicy блокирует | Добавьте исключение для Litmus/Chaos Mesh в NetworkPolicy |
| **Эксперимент не останавливается** | Истёк `TOTAL_CHAOS_DURATION` | Проверьте логи ChaosDaemon / chaos-operator |
| **Нет алертов после fault injection** | Alertmanager не настроен | Проверьте интеграцию Ruler → Alertmanager |
| **Game Day прерывается** | Emergency stop сработал | Это корректное поведение — проверьте стабильность системы |
| **Сетевая задержка не применяется** | BPF/tc недоступен | Убедитесь, что `chaos-daemon` имеет права CAP_SYS_ADMIN |
| **Sidecar не инжектируется** | Istio/Ambient conflict | Проверьте, что namespace не аннотирован для sidecar injection |
| **Алерты не срабатывают во время эксперимента** | Метрика не существует или label mismatch | Проверьте `up` и availability probe для целевого сервиса. Убедитесь, что job в Prometheus активен. |
| **False positive: алерт сработал без хаоса** | Сезонный пик или соседний эксперимент | Добавьте `without (instance)` агрегацию, настройте `for:` длительность. Используйте `offset` для сравнения с baseline. |
| **Burn Rate всегда 0** | SLO слишком мягкий или метрика 5xx отсутствует | Проверьте, что `http_requests_total` имеет label `status`. Убедитесь в правильности порога SLO. |
| **Latency p99 скачет без хаоса** | GC pause или cold start | Добавьте `jitter` к baseline, используйте `avg_over_time()` вместо `rate()` для сглаживания. |
| **Error Budget расходуется слишком быстро** | SLO нереалистично низкий или реальный деградация | Пересмотрите SLO. Если деградация реальная — эксперимент корректен, остановите его и разберитесь с проблемой. |
| **Steady State смещается во время эксперимента** | Наличие другого трафика (боты, фоновые задания) | Изолируйте трафик эксперимента (separate path или label). Используйте `sum without (job)` для фильтрации. |
| **Метрики не собираются** | Exporter не настроен или метрики неэкспортируются | Проверьте JMX exporter (Java), pg_stat_statements (PostgreSQL), custom metrics (App). |
| **PromQL возвращает no data** | Интервал сбора слишком большой | Уменьшите `scrape_interval` в Prometheus. Для коротких экспериментов используйте `[1m]` вместо `[5m]`. |
| **Эксперимент не останавливается автоматически** | Stop-switch не настроен или пороги слишком мягкие | Настройте Alertmanager правила с `for:` и severity. Проверьте, что chaos платформа интегрирована с алертингом. |
| **Probe показывает FAIL без причины** | Таймаут probe слишком короткий | Увеличьте `probeTimeout` и `retry` в конфигурации пробы. Проверьте доступность эндпоинта из сети probe. |

## Лучшие практики

### Pre-experiment checks

1. **Валидируйте Observability ДО эксперимента** — если мониторинг не видит сбой, эксперимент бессмысленен. Проверьте алерты, дашборды, trace coverage.
2. **Определите stop-switch заранее** — автоматическая остановка по метрикам, а не по таймауту. Таймаут — fallback, а не основной механизм.
3. **Создайте runbook** — цель, гипотеза, blast radius, baseline метрики, критерии успеха, критерии остановки, контакты ответственных.
4. **Проверьте blast radius** — убедитесь, что эксперимент затрагивает только целевые ресурсы. Проверьте label selectors, namespace, mode (one vs all).
5. **Синхронизируйте с DR-планом** — если у вас есть сценарии Disaster Recovery, хаос-эксперименты должны их покрывать (failover БД, восстановление кеша).

### Выполнение экспериментов

6. **Начинайте с минимального blast radius** — 1% трафика или один под. Никогда не применяйте `mode: all` в production без проверки.
7. **Используйте probes** — проверяйте steady state во время эксперимента. Без probes эксперимент — не научный метод.
8. **Сравнивайте с baseline, а не с абсолютными порогами** — 100ms latency приемлемы для одного сервиса и неприемлемы для другого.
9. **Коррелируйте метрики во времени** — latency spike + error rate spike + saturation spike = деградация. Одиночный спред — возможно, шум.
10. **Учитывайте seasonality** — исключайте из baseline дни распродаж, релизов и патч-вторников.

### Автоматизация и governance

11. **Интегрируйте в CI-CD pipeline** — каждый Pull Request должен проходить минимальный хаос-тест в Staging.
12. **Проводите Game Days** — минимум 1 раз в квартал. Это не только техническая проверка, но и тренировка команды.
13. **Используйте Resilience as Code** — хаос-эксперименты хранятся в Git рядом с манифестами приложения. Процесс review обязателен.
14. **Фиксируйте метрики после эксперимента** — MTTD, MTTR, Time to Signal, blast radius фактический. Это данные для улучшения следующих экспериментов.
15. **Анализируйте production incidents** — каждый production incident — это готовый сценарий для хаос-эксперимента. Воспроизведите отказ в контролируемых условиях.

### Избегайте ошибок

16. **Не полагайтесь на одну метрику** — если latency выросла, но error rate и traffic стабильны, это может быть planned maintenance, а не деградация.
17. **Не игнорируйте L2/L3 при положительных L0/L1** — бизнес-метрики могут не упасть, если кэш работает, а база данных уже мертва.
18. **Не забывайте про retry storm** — error rate может выглядеть нормальной, если клиент ретраит. Смотрите RPS вместе с error rate.
19. **Не используйте average latency** — среднее скрывает хвосты. Используйте p99/p999.
20. **Не оставляйте эксперимент без cleanup** — после остановки убедитесь, что все CRD/политики удалены, метрики вернулись к baseline.

## Дополнительная информация

### Типичные ошибки интерпретации

- **Парадокс среднего:** Средняя задержка (average) остается в норме, но p99.9 вырастает в 10 раз. Хаос-инженерия всегда работает с «хвостами» распределения.
- **Retry Storm:** Метрика Error Rate может выглядеть стабильной, если клиент делает много попыток, но при этом резко растет RPS и задержка. Необходимо анализировать эти метрики в связке.
- **Маскировка сбоя кэшем:** Если при отключении БД сервис продолжает отдавать 200 OK из кэша, эксперимент может показаться успешным. Важно проверять `cache_hit_ratio` и `db_query_duration`.
- **Baseline drift:** Если baseline считается за 7 дней, а в этот период был релиз, то «норма» уже искажена. Пересчитывайте baseline после значимых изменений.

### Интеграция с DORA

Хаос-эксперименты напрямую влияют на метрики DORA:
- **Change Failure Rate (CFR):** Снижается за счет выявления багов конфигурации до деплоя в Prod.
- **MTTR:** Улучшается за счет отработки сценариев восстановления и настройки качественного алертинга.

### См. также

* [Chaos Engineering: Обзор](./chaos_engineering_overview.md) — основные принципы и практики
* [Инструменты Chaos Engineering](./chaos_engineering_tools.md) — пайплайн эксперимента, stop-switch, blast radius
* [Chaos Engineering — тестирование resilience-паттернов](./chaos_resilience_patterns_testing.md) — Circuit Breaker, Bulkhead.
* [Chaos Engineering — stateful-приложения](./chaos_stateful_applications.md) — PostgreSQL, Redis, Kafka failover.
* [Chaos Engineering — service mesh](./chaos_service_mesh.md) — Istio/Envoy chaos.
* [Chaos Engineering — application-level chaos](./chaos_application_level.md) — exception injection, thread pool exhaustion.
* [Chaos Engineering — advanced blast radius](./chaos_advanced_blast_radius.md) — progressive rollout, traffic mirroring.
* [Chaos Engineering — observability](./chaos_observability.md) — traces, logs, audit trail.
* [Chaos Engineering — maturity model](./chaos_maturity_and_governance.md) — governance, KPIs.
* [Chaos Engineering — CI/CD pipelines](./chaos_cicd_pipelines.md) — интеграция в конвейер.
* [Chaos Engineering — non-Kubernetes](./chaos_non_kubernetes.md) — VM, bare-metal, Docker chaos.
