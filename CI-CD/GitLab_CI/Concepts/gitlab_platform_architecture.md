# Архитектура и масштабирование GitLab

## Определения

* **Omnibus GitLab** — официальный пакет (deb/rpm), содержащий GitLab и все его зависимости. Управляется утилитой `gitlab-ctl`. Оптимален для большинства self-hosted инсталляций.
* **GitLab Shell** — компонент, обрабатывающий SSH-соединения для Git-операций (clone, push, pull). Работает как демон, слушающий на отдельном порту (по умолчанию 22 или 2222) и взаимодействующий с GitLab Rails API для аутентификации и авторизации.
* **Workhorse** — HTTP-прокси, обрабатывающий «тяжелые» запросы: загрузку/выгрузку артефактов, Git LFS, WebIDE. Снимает нагрузку с Puma, передавая ему только простые запросы.
* **Puma** — веб-сервер Ruby, обрабатывающий основной API и веб-интерфейс GitLab. Использует многопоточную модель для параллельной обработки запросов.
* **GitLab Runner** — агент, выполняющий задачи CI/CD. Опрашивает GitLab Server по HTTP(S) и запускает задания в различных окружениях (Docker, Kubernetes, Shell).
* **Gitaly** — Git RPC сервис, обеспечивающий доступ к репозиториям. Все операции с файловой системой Git проходят через этот слой.
* **Gitaly Cluster (RAFT)** — современная (v17+) архитектура высокой доступности для Git-данных. Использует протокол консенсуса Raft для репликации без участия внешнего прокси Praefect.
* **Sidekiq** — многопоточный фоновый обработчик задач на Ruby. Отвечает за асинхронные процессы: отправку уведомлений, обработку пайплайнов, чистку кэша.
* **GitLab Orbit** — графовая база данных контекста жизненного цикла ПО (v19.x). Индексирует связи между кодом, тикетами и пайплайнами для обеспечения трассировки и аналитики.
* **ClickHouse** — колоночная СУБД, используемая в GitLab (v19.x+) для хранения и быстрой обработки аналитических данных, таких как метрики DORA и логи безопасности.
* **GitLab Geo** — решение для территориально распределенных команд. Позволяет создавать read-only зеркала инстанса в разных регионах для ускорения Git-операций и обеспечения DRP (Disaster Recovery).

## Основные концепции

### Компоненты системы

GitLab представляет собой микросервисную экосистему, где каждый компонент отвечает за свою область:

* **Nginx / Envoy Gateway:** Входная точка трафика. В Cloud Native инсталляциях (v19.x) Envoy Gateway заменяет Nginx Ingress для поддержки расширенных функций балансировки и безопасности.
* **GitLab Rails (Puma/Workhorse):** Ядро приложения. Puma обрабатывает веб-запросы и API. Workhorse — легковесный прокси, обрабатывающий «тяжелые» HTTP-запросы (артефакты, Git LFS).
* **PostgreSQL 17:** Хранение метаданных: пользователи, проекты, задачи, права доступа.
* **Valkey 7.2+:** Хранилище сессий, кэша и очередей задач Sidekiq (замена Redis).
* **Gitaly Cluster:** Сервис доступа к репозиториям. Масштабируется горизонтально через шардирование или кластеризацию.
* **Registry:** Встроенный Container Registry для хранения Docker-образов.
* **Object Storage:** Внешнее S3-совместимое хранилище (MinIO, Ceph RADOS Gateway) для всех Stateless-данных: артефакты, бэкапы, LFS.

### Механизм выполнения задач (CI/CD)

GitLab Server формирует очередь заданий, которые выбирают **GitLab Runners**. Взаимодействие происходит по Pull-модели: раннеры опрашивают сервер по HTTP(S).

**Масштабирование через GitLab Runner Operator:**
В крупных инфраструктурах используется запуск в Kubernetes, где за каждую джобу отвечает отдельный под.
*   **Изоляция:** Каждый запуск происходит в "чистом" контейнере, что исключает конфликты зависимостей между разными пайплайнами.
*   **Динамические ресурсы:** Под создается только на время выполнения задачи, потребляя ресурсы кластера ровно столько, сколько указано в лимитах джобы.
*   **Автомасштабирование:** Kubernetes автоматически распределяет поды раннеров по свободным нодам кластера.

### Варианты развертывания

| Метод | Особенности | Рекомендация |
| :--- | :--- | :--- |
| **Omnibus (Package)** | Простая установка и обновление. Полный контроль над компонентами. | **Production (Single Node / Distributed)** |
| **Cloud Native Hybrid** | Rails/Sidekiq в Kubernetes, Gitaly Cluster и БД на виртуальных машинах. | **Enterprise HA / Large Scale** |
| **Helm Chart / Operator** | Полное развертывание в Kubernetes. Gitaly в K8s пока только в шардированном режиме. | **Kubernetes-native (Scaling focus)** |

### Управление через Omnibus

Основным инструментом управления является утилита `gitlab-ctl`. Все настройки хранятся в файле `/etc/gitlab/gitlab.rb`.

* **Применение изменений:** `sudo gitlab-ctl reconfigure`.
* **Проверка статуса:** `sudo gitlab-ctl status`.
* **Просмотр логов:** `sudo gitlab-ctl tail`.
* **Безопасность:** Файл `gitlab-secrets.json` обязателен для бэкапа, так как хранит ключи шифрования.

## Практические сценарии

### 1. Одноузловая архитектура (Single Node)

Все компоненты на одной виртуальной машине. Оптимально для команд до 1000 пользователей и небольших инсталляций.

* **Ресурсы:** Минимум 4 vCPU / 16 ГБ RAM. При интенсивном использовании CI/CD рекомендуется 8 vCPU / 32 ГБ RAM.
* **Преимущества:** Простота обновлений и резервного копирования одной командой `gitlab-backup create`.

### 2. Распределенная архитектура (Distributed)

Разнесение компонентов по отдельным хостам для изоляции нагрузки. Рекомендуется для 2000+ пользователей.

* **Gitaly:** Первым выносится на выделенный сервер с быстрыми NVMe-дисками, так как операции Git — самые ресурсозатратные.
* **Базы данных:** PostgreSQL 17 и Valkey выносятся на отдельные узлы для предотвращения конкуренции за IO и память.
* **Stateless-слой:** Несколько серверов с Rails (Puma), работающих за общим балансировщиком.

### 3. Высокая доступность (High Availability)

Для Enterprise-инсталляций (3000+ пользователей) с жесткими требованиями к SLA.

* **Traffic Management:** Использование **Envoy Gateway** для интеллектуальной маршрутизации и защиты от DDoS на уровне L7.
* **Gitaly Cluster:** Кластер из 3+ нод Gitaly с RAFT-репликацией, обеспечивающий консистентность Git-данных даже при выходе из строя целой зоны доступности.
* **PostgreSQL HA:** Кластер под управлением **Patroni** и **Consul**, обеспечивающий автоматический failover и отсутствие единой точки отказа в слое данных.
* **Kubernetes-деплой:** Rails и Sidekiq запускаются в Kubernetes (для быстрого горизонтального масштабирования), в то время как Gitaly и БД остаются на выделенных VM (для стабильной производительности дисковой подсистемы).

### 4. Резервное копирование и восстановление

Автоматизация бэкапов критичных данных GitLab.

```bash
# Создание полного бэкапа
sudo gitlab-backup create CRON=1

# Настройка автоматического бэкапа (crontab)
echo "0 2 * * * /opt/gitlab/bin/gitlab-backup create CRON=1" | sudo crontab -

# Восстановление из бэкапа
sudo gitlab-ctl stop puma sidekiq
sudo gitlab-backup restore BACKUP=1234567890
sudo gitlab-ctl restart
```

**Важные файлы для бэкапа:**

```bash
# Обязательные файлы
/etc/gitlab/gitlab-secrets.json    # Ключи шифрования
/etc/gitlab/gitlab.rb              # Конфигурация

# Дополнительные данные
/var/opt/gitlab/git-data/          # Git-репозитории
/var/opt/gitlab/backups/           # Бэкапы БД
```

### 5. Обновление GitLab

Пошаговая процедура обновления с проверкой совместимости.

```bash
# 1. Проверка текущей версии
sudo gitlab-rake gitlab:env:info

# 2. Резервное копирование перед обновлением
sudo gitlab-backup create

# 3. Обновление пакета (Debian/Ubuntu)
sudo apt update && sudo apt install gitlab-ce

# 4. Применение миграций
sudo gitlab-ctl reconfigure

# 5. Проверка статуса
sudo gitlab-ctl status
sudo gitlab-rake gitlab:check SANITIZE=true
```

**Порядок обновления:**
1. Прочитайте [changelog](https://about.gitlab.com/releases/) для версии назначения.
2. Проверьте совместимость PostgreSQL и Redis/Valkey.
3. Обновляйте по одной минорной версии за раз.
4. Протестируйте на staging-окружении.

### 6. Настройка мониторинга через Prometheus

Интеграция с внешним Prometheus для централизованного мониторинга.

```yaml
# prometheus.yml
scrape_configs:
  - job_name: 'gitlab'
    static_configs:
      - targets: ['gitlab.example.com:9090']
    metrics_path: '/-/metrics'
    bearer_token: 'YOUR_GITLAB_API_TOKEN'

  - job_name: 'gitlab-runners'
    static_configs:
      - targets: ['runner1.example.com:9252', 'runner2.example.com:9252']
```

**Ключевые метрики для алертинга:**

```yaml
# alerts.yml
groups:
  - name: gitlab
    rules:
      - alert: GitLabPumaDown
        expr: up{job="gitlab"} == 0
        for: 1m
        labels:
          severity: critical

      - alert: GitLabHighLatency
        expr: gitlab_workflow_duration_seconds > 5
        for: 5m
        labels:
          severity: warning
```

### 7. Оптимизация производительности

Настройка параметров для повышения отзывчивости.

```ruby
# /etc/gitlab/gitlab.rb

# Puma (веб-сервер)
puma['worker_processes'] = 4
puma['threads_max'] = 16

# Sidekiq (фоновые задачи)
sidekiq['max_concurrency'] = 20

# Gitaly (Git-операции)
gitaly['configuration'] = {
  concurrency: [
    { rpc: "/gitaly.SmartHTTPService/PostReceivePack", max_per_repo: 3 }
  ],
  storage: [
    { name: "default", path: "/var/opt/gitlab/git-data/repositories" }
  ]
}

# PostgreSQL
postgresql['shared_buffers'] = "4GB"
postgresql['work_mem'] = "16MB"

# Valkey
valkey['maxmemory'] = "8gb"
valkey['maxmemory-policy'] = "allkeys-lru"
```

### 8. Настройка GitLab Runner (Docker Compose)

Запуск Runner в Docker с оптимальными настройками.

```yaml
version: '3.8'
services:
  gitlab-runner:
    image: gitlab/gitlab-runner:latest
    container_name: gitlab-runner
    restart: always
    volumes:
      - /srv/gitlab-runner/config:/etc/gitlab-runner
      - /var/run/docker.sock:/var/run/docker.sock
    environment:
      - GITLAB_RUNNER_TOKEN=${RUNNER_TOKEN}
    deploy:
      resources:
        limits:
          cpus: '2'
          memory: 4G
        reservations:
          cpus: '1'
          memory: 2G
```

**Регистрация Runner:**

```bash
# Регистрация нового Runner
docker exec -it gitlab-runner gitlab-runner register \
  --non-interactive \
  --url "https://gitlab.example.com/" \
  --token "${RUNNER_TOKEN}" \
  --executor "docker" \
  --docker-image "alpine:latest" \
  --description "docker-runner" \
  --tag-list "docker,linux" \
  --run-untagged="true" \
  --locked="false"
```

## Дополнительная информация

### Использование Object Storage (S3)

Переход на S3 решает несколько критических задач:

1. **Независимость от дисков:** Позволяет горизонтально масштабировать Rails-ноды без использования NFS.
2. **Синхронизация Sidekiq:** Гарантирует доступность артефактов при обработке задач на разных серверах.
3. **Оптимизация БД:** Хранение метаданных и диффов в S3 снижает нагрузку на PostgreSQL.

### Опыт эксплуатации и рекомендации

* **Registry Separation:** Рекомендуется использовать внешний Container Registry (например, Harbor) или выносить встроенный Registry за пределы основного инстанса.
* **Gitaly на Kubernetes:** На текущий момент (19.x) Gitaly в K8s поддерживает только шардирование. Для полноценного HA с репликацией данных рекомендуется Gitaly Cluster на виртуальных машинах.

### Мониторинг и наблюдаемость

GitLab предоставляет встроенные инструменты мониторинга для отслеживания состояния компонентов:

* **Prometheus:** Встроенный экземпляр собирает метрики всех компонентов. Доступен по адресу `http://<gitlab-host>:9090`.
* **Grafana:** Встроенный дашборд для визуализации метрик. Доступен по адресу `http://<gitlab-host>:3000`.
* **Alertmanager:** Алертинг на основе метрик Prometheus. Настраивается через файл `/etc/gitlab/gitlab.rb`.

**Ключевые метрики для мониторинга:**

```bash
# Просмотр метрик через API
curl -s http://localhost:9090/api/v1/query?query=gitlab_workflow_duration_seconds

# Проверка состояния компонентов
sudo gitlab-ctl status
```

| Компонент | Критичные метрики | Пороговые значения |
|:---|:---|:---|
| **Puma** | `puma_workers`, `puma_threads` | Workers > 0, Threads > 0 |
| **Sidekiq** | `sidekiq_running_jobs`, `sidekiq_queue_size` | Queue < 1000 |
| **Gitaly** | `gitaly_connections`, `gitaly_latency_seconds` | Latency < 1s |
| **PostgreSQL** | `pg_stat_activity`, `pg_stat_database` | Connections < max_connections |
| **Valkey** | `valkey_connected_clients`, `valkey_used_memory` | Memory < maxmemory |

### Диагностика и устранение неполадок

#### Типичные ошибки и их решения

| Ошибка | Причина | Решение |
|:---|:---|:---|
| **502 Bad Gateway** | Puma не отвечает или перегружен | Проверьте статус Puma: `sudo gitlab-ctl status puma`. Увеличьте `puma['worker_processes']` в `gitlab.rb`. |
| **504 Gateway Timeout** | Workhorse не может дождаться ответа от Puma | Увеличьте таймауты в `gitlab.rb`: `workhorse['api_queue_duration']`. |
| **Gitaly high latency** | Проблемы с диском или сеть | Проверьте I/O: `iostat -x 1`. Убедитесь, что используется SSD/NVMe. |
| **Sidekiq queue buildup** | Медленная обработка задач | Увеличьте `sidekiq['max_concurrency']`. Проверьте логи: `sudo gitlab-ctl tail sidekiq`. |
| **PostgreSQL connection limit** | Исчерпан лимит соединений | Увеличьте `max_connections` или оптимизируйте запросы. |
| **Valkey memory overflow** | Исчерпан лимит памяти | Увеличьте `maxmemory` или настройте eviction policy. |

**Методы диагностики:**

```bash
# Просмотр логов конкретного компонента
sudo gitlab-ctl tail puma
sudo gitlab-ctl tail sidekiq
sudo gitlab-ctl tail gitaly

# Проверка использования ресурсов
sudo gitlab-ctl metrics | grep -E "puma|sidekiq|gitaly"

# Тестирование connectivity
sudo gitlab-rake gitlab:check
```

### Лучшие практики

1. **Регулярно обновляйте GitLab** — безопасности и исправления ошибок выходят в каждом релизе.
2. **Настройте мониторинг** — используйте встроенный Prometheus/Grafana для отслеживания метрик.
3. **Бэкапьте конфигурацию** — файл `gitlab-secrets.json` критичен для восстановления.
4. **Используйте SSD/NVMe** — Gitaly крайне чувствителен к задержкам диска.
5. **Ограничьте ресурсы** — настройте лимиты CPU/RAM для Docker-контейнеров.
6. **Тестируйте обновления** — сначала обновляйте на staging-окружении.
7. **Документируйте изменения** — ведите журнал изменений конфигурации.

### Смотрите также

* **[Интеграция с Kubernetes](../Advanced/gitlab_kubernetes_integration_guide.md)** — развертывание GitLab в Kubernetes-кластерах.
* **[Официальные Reference Architectures](https://docs.gitlab.com/ee/administration/reference_architectures/)** — эталонные схемы масштабирования.
* **[GitOps и GitLab](../../../GitOps/GitOps_overview.md)** — архитектурные подходы к доставке ПО.
