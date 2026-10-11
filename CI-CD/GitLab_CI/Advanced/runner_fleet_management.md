# Управление парком Runner'ов (Fleet Management)

**Актуально для:** GitLab Runner 19.x (GitLab 19.x)

> Область применения заметок: практики DevOps, SRE и SysAdmin при эксплуатации самостоятельно развёрнутых (on-prem / self-hosted) систем. Материалы, относящиеся к публичным облакам и технологиям искусственного интеллекта, в данной базе знаний не рассматриваются.

## Определения

**Управление парком Runner'ов (Runner Fleet Management)** — совокупность административных, политических и технических процессов по обеспечению CI/CD мощностями в масштабах организации. Фокус смещается с настройки отдельного Runner'а на управление группой исполнителей как единым ресурсом.

**Политики распределения ресурсов (Resource Allocation Policies)** — набор правил, определяющих, какие команды, проекты или типы задач имеют приоритетный доступ к вычислительным мощностям.

**Квотирование (Quotas)** — жёсткие или мягкие ограничения на потребление ресурсов (минуты выполнения, количество параллельных джоб, CPU/RAM) на уровне групп пользователей или департаментов.

**Оркестратор флота (Fleet Orchestrator)** — компонент (например, GitLab Fleeting/Taskscaler), который управляет жизненным циклом Runner'ов: созданием, регистрацией, мониторингом здоровья и удалением.

**Золотой образ (Golden Image)** — предварительно настроенный и протестированный шаблон ОС или контейнера, содержащий стандартный набор инструментов, библиотек и средств безопасности.

**Эфемерный Runner (Ephemeral Runner)** — исполнитель, который после выполнения одной (или ограниченного числа) задач уничтожается и заменяется свежим. Исключает накопление состояния (side-effects), кэш-атаки и «сноубола» зависимостей между джобами.

**Плотность упаковки (Bin-packing)** — стратегия размещения нескольких параллельных джоб на один узел так, чтобы минимизировать неиспользуемые остатки CPU/RAM и снизить число физических узлов.

## Архитектура управления флотом

Современный парк Runner'ов строится на базе трехуровневой архитектуры:

1.  **Уровень управления (Control Plane):** CI/CD сервер GitLab, который распределяет задачи и хранит метаданные о состоянии флота.
2.  **Уровень координации (Orchestration Layer):** Автоскейлеры и контроллеры (Fleeting/Taskscaler, KEDA, Docker Machine). Они принимают решение о масштабировании на основе длины очереди или расписания.
3.  **Уровень исполнения (Execution Layer):** Непосредственно Runner'ы (VM, контейнеры, bare metal), где выполняется код джобы.

### Жизненный цикл Runner'а

1.  **Provisioning:** Динамическое создание вычислительного ресурса (виртуальная машина, контейнер).
2.  **Registration:** Автоматическая регистрация Runner'а в GitLab с использованием временных токенов (JIT Config).
3.  **Execution:** Выполнение одной или нескольких задач (в зависимости от политики эфемерности).
4.  **Deregistration:** Корректное удаление Runner'а из списка активных в Control Plane.
5.  **Termination/Cleanup:** Уничтожение ресурса для предотвращения накопления состояния (Side-effects).

### Модели управления Runner'ами

| Модель | Описание | Использование | Стоимость |
|:---|:---|:---|:---|
| **Static (Shared/Group/Project)** | Постоянные серверы, всегда доступны | Малые команды, простые проекты | Фиксированная |
| **Auto-scaling (Docker Machine)** | Динамическое создание VM | Средние нагрузки | Pay-per-use |
| **Kubernetes Executor** | Поды в K8s кластере | Высокие нагрузки, K8s-native | Pay-per-use |
| **Fleeting/Taskscaler** | Нативный автоскейлинг через API | Enterprise, on-premise | Оптимальная |

### Стратегии масштабирования

| Стратегия | Описание | Когда использовать |
|:---|:---|:---|
| **Reactive** | Создание Runner'а при появлении задачи | Нерегулярные нагрузки |
| **Scheduled** | Создание Runner'ов по расписанию | Предсказуемые нагрузки (ночные сборки) |
| **Predictive** | На основе исторических данных | Крупные команды с трендами |
| **Hybrid** | Комбинация reactive + scheduled | Большинство production сред |

### Эфемерные vs постоянные раннеры

| Свойство | Эфемерные (Ephemeral) | Постоянные (Persistent/Static) |
|:---|:---|:---|
| **Жизнь узла** | Создаётся под задачу, удаляется после | Живёт недели/месяцы |
| **Воспроизводимость** | Максимальная (всегда чистое окружение) | Риск «дрейфа» конфигурации |
| **Безопасность** | Поверхность атаки не накапливается | Требует регулярного патчинга и очистки |
| **Cold Start** | Выше (загрузка ОС/образа) | Ниже (узел уже готов) |
| **Стоимость/амортизация** | Платим только за время задачи | Платим за простой тоже |
| **Где применять** | Тесты, сборки, непривилегированный код | Долгие интеграционные стенды, кэш-зависимые задачи |

Рекомендация: по умолчанию — эфемерные раннеры; постоянные оставлять только для узкоспециализированных долгоживущих стендов с контролируемым доступом.

## Практические сценарии

### Предварительные требования

**Аппаратные/программные требования:**
- Хост с ОС Linux (Ubuntu/Debian/RHEL), Docker Engine или KVM/libvirt для автоскейлинга
- GitLab Server 19.x (self-hosted) с доступным API
- GitLab Runner 19.x, установленный из официального репозитория
- Сеть: Runner'ы должны иметь доступ к GitLab API и внутренним registry/зеркалам; без прямого выхода в публичный Internet (air-gapped)
- Внутренний registry (Harbor, Nexus) или локальный mirror для образов
- sysctl: `net.ipv4.ip_forward = 1` для Docker bridge networking

**Инициализация security-фич GitLab:**
- Включить `protected` и `locked` флаги для production Runner'ов
- Настроить Runner Groups с наследованием настроек
- Создать минимально привилегированный Runner Registration Token
- Включить audit logging в Admin Area → Settings → Audit Events

### Сценарий 1: Статический пул self-hosted раннеров (systemd)

Для небольших контуров или долгоживущих стендов раннер ставится как системный сервис:

```bash
# Установка и регистрация GitLab Runner (self-hosted инстанс)
sudo gitlab-runner install --user gitlab-runner --working-directory /srv/gitlab-runner
sudo gitlab-runner register \
  --non-interactive \
  --url "https://gitlab.corp.local" \
  --token "$RUNNER_REGISTRATION_TOKEN" \
  --executor "docker" \
  --description "static-docker-$(hostname)" \
  --tag-list "linux,docker,shared" \
  --run-untagged="true" \
  --locked="false"
sudo systemctl enable --now gitlab-runner
```

**Проверка:**
```bash
# → Runner registered successfully
sudo systemctl status gitlab-runner  # → active (running)
sudo gitlab-runner list  # → отображает зарегистрированного runner'а
```

Ограничение параллелизма задаётся в `/etc/gitlab-runner/config.toml` (`concurrent = N`). Такие раннеры не масштабируются сами — их число контролирует администратор.

### Сценарий 2: Эфемерные раннеры на собственных гипервизорах (Fleeting + libvirt/KVM)

Вместо инстансов внешних провайдеров пул поднимается на своих гипервизорах. После каждой задачи VM уничтожается — состояние не накапливается.

```toml
[[runners]]
  name = "kvm-ephemeral-fleet"
  executor = "docker-autoscaled"
  [runners.autoscaler]
    plugin = "libvirt"        # собственный гипервизор, без привязки к внешним провайдерам
    capacity_per_instance = 1
    max_instances = 50
    [runners.autoscaler.plugin_config]
      uri = "qemu:///system"
      template = "ci-runner-ubuntu-22.04"  # золотой образ ВМ
```

**Проверка:**
```bash
# Проверка работы Fleeting plugin
gitlab-runner --debug list  # → в логах видно подключение к libvirt
# → новые инстансы создаются при появлении задач в очереди
```

Ключевые параметры (`uri`, `template`) зависят от выбранного гипервизора (libvirt/KVM, VMware, Proxmox). Важно: `executor = "docker-autoscaled"` (или `custom`) + эфемерная VM дают модель «одна джоба — один свежий узел».

### Сценарий 3: Масштабируемый флот в кластере оркестратора с KEDA (GitLab)

Пример настройки `ScaledObject` для автоматического масштабирования раннеров на основе очереди (self-hosted GitLab):

```yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: gitlab-runner-scaler
spec:
  scaleTargetRef:
    name: gitlab-runner-deployment
  minReplicaCount: 1
  maxReplicaCount: 50
  triggers:
  - type: gitlab
    metadata:
      url: https://gitlab.corp.local          # self-hosted инстанс
      tokenFromEnv: GITLAB_READ_TOKEN          # Токен с правами read_api
      registrationTokenFromEnv: RUNNER_TOKEN
```

**Проверка:**
```bash
# Проверка масштабирования
kubectl get deployment gitlab-runner -w
# → при появлении задач в очереди replicas увеличиваются
kubectl get pods -n gitlab-runners  # → новые pods создаются динамически
```

### Сценарий 4: Мониторинг флота (Prometheus + Grafana, PromQL)

```yaml
# scrape-конфиг: опрашиваем /metrics каждого раннера
scrape_configs:
  - job_name: gitlab-runner
    static_configs:
      - targets: ['runner-1.corp.local:9252', 'runner-2.corp.local:9252']
```

Полезные запросы:

```promql
# Текущий размер очереди (джоб в ожидании)
gitlab_runner_queue_size

# Занятые раннеры (running)
sum(gitlab_runner_jobs{state="running"})

# Доля инфраструктурных падений (сигнал к cordon/drain)
rate(gitlab_runner_job_failures_total{reason="runner_system_failure"}[5m])

# Утилизация слотов
sum(gitlab_runner_jobs{state="running"}) / count(gitlab_runner_jobs) * 100
```

**Проверка:**
```bash
# Проверка эндпоинта метрик
curl -s http://runner-1.corp.local:9252/metrics | head -20
# → вывод содержит метрики gitlab_runner_*
```

Алерты строятся на `gitlab_runner_queue_size > 0` за длительное окно и на росте `runner_system_failure`.

### Сценарий 5: Конфигурация config.toml для высокой нагрузки

```toml
# /etc/gitlab-runner/config.toml — оптимизированный для production
concurrent = 50
check_interval = 1
shutdown_timeout = 30

[session_server]
  session_timeout = 1800
  session_affinity = true

# Метрики для мониторинга
metrics_server = ":9252"

[[runners]]
  name = "high-performance-runner"
  url = "https://gitlab.corp.local"
  token = "glrt-xxxxxxxxxxxx"
  executor = "docker"
  shell = "bash"
  
  # Лимиты задач
  limit = 10
  max_concurrent = 10
  
  # Очистка
  clean_policy = "always"
  clean_period = "24h"
  
  [runners.docker]
    image = "alpine:latest"
    privileged = false
    disable_entrypoint_overwrite = false
    oom_kill_disable = false
    disable_cache = false
    volumes = ["/cache", "/tmp/artifacts:/tmp/artifacts"]
    shm_size = 268435456  # 256 MB
    pull_policy = ["if-not-present"]
    
    # Лимиты ресурсов
    memory = "8g"
    cpus = "4"
    
    # Сеть
    dns = ["10.0.0.2", "10.0.0.3"]  # внутренний DNS
    dns_search = []
    
    # Безопасность
    disable_sysctls = false
    security_opt = ["no-new-privileges"]
    
  [runners.cache]
    Type = "s3"
    Shared = true
    [runners.cache.s3]
      ServerAddress = "minio.internal:9000"
      BucketName = "runner-cache"
      AccessKey = "${MINIO_ACCESS_KEY}"
      SecretKey = "${MINIO_SECRET_KEY}"
      Insecure = false
```

**Проверка:**
```bash
# Проверка синтаксиса конфигурации
gitlab-runner verify  # → Configuration is valid

# Проверка запуска
sudo systemctl restart gitlab-runner
sudo systemctl status gitlab-runner  # → active (running)

# Проверка метрик
curl -s http://localhost:9252/metrics | grep gitlab_runner_concurrent
```

### Сценарий 6: Автоматическая очистка Docker контейнеров

```yaml
# .gitlab-ci.yml — очистка Runner'ов
runner:cleanup:
  stage: .pre
  image: docker:24.0
  services:
    - docker:24.0-dind
  variables:
    DOCKER_HOST: tcp://docker:2375
  script:
    - |
      echo "=== Docker Cleanup ==="
      
      # Удаление остановленных контейнеров
      docker container prune -f
      echo "Pruned stopped containers"
      
      # Удаление неиспользуемых образов старше 7 дней
      docker image prune -a -f --filter "until=168h"
      echo "Pruned images older than 7 days"
      
      # Удаление неиспользуемых volumes
      docker volume prune -f
      echo "Pruned unused volumes"
      
      # Удаление build cache старше 7 дней
      docker builder prune -a -f --filter "until=168h"
      echo "Pruned build cache"
      
      # Статистика
      echo "=== Disk Usage After Cleanup ==="
      docker system df
  rules:
    - if: $CI_PIPELINE_SOURCE == "schedule"
```

**Проверка:**
```bash
# В логах пайплайна:
# → Pruned stopped containers
# → Pruned images older than 7 days
# → Вывод docker system df показывает снижение использования диска
```

### Сценарий 7: Мониторинг Runner fleet через API

```bash
#!/bin/bash
# runner_fleet_status.sh — проверка состояния всех Runner'ов

TOKEN="$GITLAB_API_TOKEN"
GITLAB_URL="https://gitlab.corp.local"

echo "=== Runner Fleet Status ==="

# Получение списка всех Runner'ов
RUNNERS=$(curl --silent --header "PRIVATE-TOKEN: $TOKEN" \
  "$GITLAB_URL/api/v4/runners?per_page=100" | jq '.')

# Статистика
TOTAL=$(echo "$RUNNERS" | jq 'length')
ACTIVE=$(echo "$RUNNERS" | jq '[.[] | select(.active == true)] | length')
ONLINE=$(echo "$RUNNERS" | jq '[.[] | select(.online == true)] | length')
PAUSED=$(echo "$RUNNERS" | jq '[.[] | select(.paused == true)] | length')

echo "Total Runners: $TOTAL"
echo "Active: $ACTIVE"
echo "Online: $ONLINE"
echo "Paused: $PAUSED"

# Детали по каждому Runner
echo ""
echo "=== Runner Details ==="
echo "$RUNNERS" | jq -r '.[] | "\(.id) |\(.description) |\(.status) |\(.active) |\(.jobs_completed) jobs completed"'

# Проверка проблемных Runner'ов
echo ""
echo "=== Problematic Runners ==="
echo "$RUNNERS" | jq -r '.[] | select(.online == false and .active == true) | "⚠️ \(.description) is offline but active"'
```

**Проверка:**
```bash
chmod +x runner_fleet_status.sh
./runner_fleet_status.sh
# → Total Runners: 15
# → Active: 12
# → Online: 11
# → Paused: 3
```

### Сценарий 8: Скрипт диагностики Runner'ов

```bash
#!/bin/bash
# runner_diagnostics.sh — полная диагностика Runner fleet

echo "=== GitLab Runner Diagnostics ==="

# 1. Статус службы
echo "1. Service Status:"
sudo gitlab-runner status

# 2. Версия
echo ""
echo "2. Version:"
sudo gitlab-runner --version

# 3. Зарегистрированные Runner'ы
echo ""
echo "3. Registered Runners:"
sudo gitlab-runner list

# 4. Проверка доступности
echo ""
echo "4. Runner Verification:"
sudo gitlab-runner verify

# 5. Системные ресурсы
echo ""
echo "5. System Resources:"
echo "   CPU: $(nproc) cores"
echo "   Memory: $(free -h | awk '/^Mem:/ {print $2}')"
echo "   Disk: $(df -h / | awk 'NR==2 {print $4}') available"
echo "   Load: $(uptime | awk -F'load average:' '{print $2}')"

# 6. Docker статус
echo ""
echo "6. Docker Status:"
if command -v docker &> /dev/null; then
    echo "   Docker version: $(docker --version)"
    echo "   Containers: $(docker ps -a | wc -l)"
    echo "   Images: $(docker images | wc -l)"
    echo "   Disk usage:"
    docker system df
else
    echo "   Docker not installed"
fi

# 7. Последние логи
echo ""
echo "7. Recent Logs (last 20 lines):"
sudo journalctl -u gitlab-runner --no-pager -n 20 2>/dev/null || echo "   No systemd logs available"

# 8. Проверка сети
echo ""
echo "8. Network Connectivity:"
if curl -s -o /dev/null -w "%{http_code}" "https://gitlab.corp.local/api/v4/version" | grep -q "200"; then
    echo "   GitLab: ✓ Accessible"
else
    echo "   GitLab: ✗ Not accessible"
fi
```

**Проверка:**
```bash
chmod +x runner_diagnostics.sh
./runner_diagnostics.sh
# → вывод по каждому пункту диагностики
```

### Сценарий 9: Обновление Runner fleet (Rolling Update)

```bash
#!/bin/bash
# runner_rolling_update.sh — последовательное обновление Runner'ов

GITLAB_URL="https://gitlab.corp.local"
TOKEN="$GITLAB_API_TOKEN"

# 1. Получить список активных Runner'ов
RUNNERS=$(curl --silent --header "PRIVATE-TOKEN: $TOKEN" \
  "$GITLAB_URL/api/v4/runners?per_page=100" | jq -r '.[] | select(.active == true) | "\(.id) \(.description)"')

echo "=== Rolling Update: $RUNNERS"

for RUNNER_ID in $RUNNERS; do
    echo "Updating runner $RUNNER_ID..."
    
    # 2. Перевести runner в paused
    curl --request POST --header "PRIVATE-TOKEN: $TOKEN" \
      "$GITLAB_URL/api/v4/runners/$RUNNER_ID/pause"
    
    # 3. Дождаться завершения текущих задач
    while true; do
        STATUS=$(curl --silent --header "PRIVATE-TOKEN: $TOKEN" \
          "$GITLAB_URL/api/v4/runners/$RUNNER_ID" | jq -r '.status')
        if [ "$STATUS" == "paused" ]; then
            break
        fi
        echo "  Waiting for jobs to complete..."
        sleep 10
    done
    
    # 4. Обновить бинарник на хосте
    ssh runner-host "sudo apt-get update && sudo apt-get install -y gitlab-runner"
    
    # 5. Перезапустить службу
    ssh runner-host "sudo systemctl restart gitlab-runner && sudo systemctl status gitlab-runner"
    
    # 6. Вернуть runner в active
    curl --request POST --header "PRIVATE-TOKEN: $TOKEN" \
      "$GITLAB_URL/api/v4/runners/$RUNNER_ID/activate"
    
    echo "  Runner $RUNNER_ID updated and activated"
done

echo "=== Rolling Update Complete ==="
```

**Проверка:**
```bash
# → каждый runner обновлён поочерёдно без остановки всего флота
# → мониторинг очереди показывает отсутствие задержек
```

### Сценарий 10: Планирование мощностей (Capacity Planning)

**Базовая формула оценки пиковой ёмкости (в слотах):**

```
пиковые_слоты ≈ (среднее_число_параллельных_джоб_в_пик × среднее_время_джоб_сек) / допустимое_время_ожидания_сек × запас(headroom)
```

Где `запас` обычно 1.2–1.3 (20–30% на всплески и обслуживание узлов).

**Практические шаги (SysAdmin/SRE):**
1. Собрать историю из очереди (Prometheus/Grafana) за 2–4 недели, выделить p95/p99 параллелизма.
2. Выбрать размер узла под **bin-packing**: если средняя джоба требует 2 CPU / 4 GiB, узел на 16 CPU / 32 GiB вместит ~7–8 параллельных джоб с запасом, а не 8 «впритык» (риск OOM при всплеске).
3. Учитывать «тяжёлые» джоб (интеграционные тесты, сборки монолита) отдельно — выносить на выделенные узлы через Taints, чтобы они не вытесняли обычные.
4. Регулярно пересматривать: рост числа команд линейно увеличивает слоты, но эффективность упаковки падает при фрагментации.

**Проверка:**
```promql
# В Grafana: p95 параллельность за 4 недели
quantile(0.95, gitlab_runner_jobs_total)
# → сравниваем с текущей ёмкостью флота
```

## Устранение неполадок (Troubleshooting)

### Типичные ошибки

| Симптом | Вероятная причина | Действие |
|:---|:---|:---|
| Очередь растёт, раннеры idle | Неверные теги, `concurrent` слишком низкий, нет matching runner | Проверить теги джоба и раннеров, `concurrent` в `config.toml` |
| Джобы зависают в `pending` | Нет свободных слотов, автокейлер не работает | Метрика Queue Time; проверить health autoscaler, minReplicaCount |
| Cold start > 60 сек | Тяжёлый golden image, холодный кэш зависимостей | Оптимизировать образ, включить warm pool, предварительный pull зависимостей |
| `No space left on device` | Логи/кэш/артефакты заполнили диск | Настроить `docker system prune`, ограничить retention артефактов, мониторинг диска |
| Кэш отравлён (cache poisoning) | Общий кэш между проектами | Изолировать кэш, использовать ephemeral runners для недоверенного кода |
| Раннер не deregister после удаления | Устаревшая запись в CI-сервере | Скрипт очистки через API; настроить TTL на регистрацию |
| Токен регистрации истёк | Долгоживущий статический токен | Переход на JIT Config / OIDC; мониторинг срока действия токена |
| Раннер скомпрометирован | Утечка через workspace или кэш | Уничтожить узел, rebuild из golden image, отозвать токен |

### Диагностические команды

```bash
# 1. Проверка статуса Runner'ов
sudo gitlab-runner status
# → active (running) / inactive

# 2. Проверка зарегистрированных Runner'ов
sudo gitlab-runner list
# → список с URL, executor, tags, status

# 3. Проверка конфигурации
gitlab-runner verify
# → Configuration is valid / errors

# 4. Проверка очереди через API
curl --header "PRIVATE-TOKEN: $TOKEN" \
  "https://gitlab.corp.local/api/v4/jobs?scope=pending&per_page=10"
# → список висящих джоб

# 5. Проверка метрик Runner'а
curl -s http://localhost:9252/metrics | grep gitlab_runner_queue_size
# → текущий размер очереди

# 6. Проверка audit log
sudo journalctl -u gitlab-runner --since "1 hour ago"
# → последние события Runner'а
```

## Рекомендации

1. По умолчанию — эфемерные раннеры; постоянные оставлять только для специализированных долгоживущих стендов с контролируемым доступом.
2. Используйте золотые образы (Packer, Docker) для идемпотентного развёртывания; все инструменты — из доверенных внутренних репозиториев.
3. Переход с долгоживущих регистрационных токенов на динамические (JIT Config, OIDC) — исключает компрометацию всего флота при утечке одного ключа.
4. Мониторьте флот как инфраструктуру: Queue Time, Runner Saturation, Failure Rate — это SRE-метрики с алертами, а не разовые проверки.
5. Настраивайте bin-packing с запасом 20–30% на headroom; выделяйте «тяжёлые» джобы на отдельные узлы через Taints.
6. В air-gapped средах pré-downloaded образы или внутренние зеркала; запрещайте раннерам прямой выход в публичный Internet.
7. Изолируйте кэш и артефакты между проектами — иначе общий кэш становится вектором атаки (cache poisoning).
8. Регулярно выполняйте drain/cordon при обновлениях и инцидентах; завершайте активные джобы gracefully через `SIGTERM`.
9. Ограничивайте `concurrent` и `limit` на уровне раннера, чтобы один «тяжёлый» пайплайн не занимал весь флот.
10. Включайте structured logging и централизованный сбор логов для audit trail и расследования инцидентов.

## Ограничения и edge cases

- **Air-gapped среды:** В изолированных сетях раннер не может тянуть образы из публичных реестров. Решение — pré-downloaded golden images на узлы или внутренние зеркала (Nexus, Harbor, MinIO). Подробнее: **[Изолированные среды (Air-gapped)](../../Core_Concepts/air_gapped_environments.md)**.
- **Нагрузка на control plane:** Частая регистрация/deregistration эфемерных раннеров создаёт шум в API GitLab. Ограничьте `check_interval` и используйте JIT Config, чтобы не хранить старые токены.
- **Cold start эфемерных раннеров:** Загрузка ОС/образа добавляет латентность. Для latency-чувствительных пайплайнов — warm pools или постоянные раннеры с контролируемым доступом.
- **Multi-tenancy и кэш:** Общий кэш между проектами — поверхность атаки (cache poisoning). Изолируйте кэш по namespace/project или используйте scoped S3-бакеты.
- **Устаревшие/проприетарные гипервизоры:** Не все гипервизоры имеют плагины для Fleeting/Taskscaler. Для VMware, OpenStack, Proxmox, libvirt — проверьте актуальность плагина перед внедрением.
- **Регуляторные требования:** В regulated industries требуется audit trail: какой раннер, какой токен, какой джоб, какие секреты использовались. Включайте structured logging и централизованный сбор логов.
- **Noisy neighbor:** При bin-packing на одном узле «тяжёлый» джоб может выедать CPU/RAM у соседних. Используйте cgroups/Docker resource limits и выделенные узлы через Taints.
- **Feature Flags:** Некоторые функции автоскейлинга (например, `gitlab_runner_autoscaling`) управляются feature flags в GitLab. Проверяйте их статус в Admin Area → Settings → CI/CD → Runner before deploying auto-scaling.
- **Runner Groups inheritance:** Настройки Runner Groups (tags, locked, run_untagged) наследуются вниз по иерархии. При неправильной конфигурации дочерние проекты могут получить доступ к непреднамеренным раннерам.
- **Maintenance mode:** При обновлении GitLab Server переводите Runner'ы в maintenance mode, чтобы предотвратить потерю задач во время downtime. Используйте `gitlab-runner pause` на всех активных Runner'ах перед обновлением.

## Дополнительная информация

### Связанные темы

- **[Обзор GitLab Runner и Executor](./gitlab_ci_runners_executors.md)** — типы Runner'ов и executor'ы
- **[Регистрация Runner](../Tutorials/runner_registration.md)** — установка и регистрация
- **[Мониторинг и метрики](./monitoring_and_metrics.md)** — метрики Runner'ов
- **[Кэширование](./gitlab_ci_caching/caching_overview.md)** — оптимизация кэша на Runner'ах
- **[Docker Compose установка](../Tutorials/gitlab_runner_docker_compose.md)** — запуск в контейнере
- **[Безопасность CI/CD](../../Core_Concepts/ci_cd_security_hardening.md)** — hardening Runner'ов и окружений
- **[Безопасность секретов](../../DevSecOps/secrets_management.md)** — динамические токены, OIDC, Vault для раннеров
- **[Управление парком раннеров (общее)](../../runner-fleet-management.md)** — общие принципы Fleet Management для GitLab/GitHub/Jenkins

### См. также

- **[KEDA Autoscaling](https://keda.sh/docs/2.14/scalers/gitlab/)** — документация по GitLab scaler
- **[GitLab Fleeting](https://docs.gitlab.com/runner/executors/docker_autoscaler.html)** — архитектура автоскейлинга нового поколения
- **[GitLab Runner Metrics](https://docs.gitlab.com/runner/monitoring/)** — встроенные метрики Prometheus
