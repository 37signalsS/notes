# Архитектура и масштабирование GitLab

**Актуально для:** GitLab 17.x–19.x

## Определения

* **Omnibus GitLab** — официальный пакет (deb/rpm), содержащий GitLab и все его зависимости. Управляется утилитой `gitlab-ctl`. Оптимален для большинства self-hosted инсталляций.
* **GitLab Shell** — компонент, обрабатывающий SSH-соединения для Git-операций (clone, push, pull). Работает как демон, слушающий на отдельном порту (по умолчанию 22 или 2222) и взаимодействующий с GitLab Rails API для аутентификации и авторизации.
* **Workhorse** — HTTP-прокси, обрабатывающий «тяжелые» запросы: загрузку/выгрузку артефактов, Git LFS, WebIDE. Снимает нагрузку с Puma, передавая ему только простые запросы.
* **Puma** — веб-сервер Ruby, обрабатывающий основной API и веб-интерфейс GitLab. Использует многопоточную модель для параллельной обработки запросов.
* **GitLab Runner** — агент, выполняющий задачи CI/CD. Опрашивает GitLab Server по HTTP(S) и запускает задания в различных окружениях (Docker, Kubernetes, Shell).
* **Gitaly** — Git RPC сервис, обеспечивающий доступ к репозиториям. Все операции с файловой системой Git проходят через этот слой.
* **Gitaly Cluster (RAFT)** — архитектура высокой доступности для Git-данных (v17+). Использует протокол консенсуса Raft для репликации. **Примечание:** Gitaly Cluster поддерживается только на виртуальных машинах; развертывание в Kubernetes не поддерживается.
* **Praefect** — прокси-слой для Gitaly Cluster, управляющий маршрутизацией запросов и репликацией.
* **Sidekiq** — многопоточный фоновый обработчик задач на Ruby. Отвечает за асинхронные процессы: отправку уведомлений, обработку пайплайнов, чистку кэша.
* **GitLab Orbit** — графовая база данных контекста жизненного цикла ПО (v19.x). Индексирует связи между кодом, тикетами и пайплайнами для обеспечения трассировки и аналитики.
* **ClickHouse** — колоночная СУБД, используемая в GitLab (v19.x+) для хранения и быстрой обработки аналитических данных, таких как метрики DORA и логи безопасности.
* **GitLab Geo** — решение для территориально распределенных команд. Позволяет создавать read-only зеркала инстанса в разных регионах для ускорения Git-операций и обеспечения DRP (Disaster Recovery).
* **Valkey** — высокопроизводительное in-memory хранилище (форк Redis), используемое в GitLab 19.x как основной механизм кэширования и брокер сообщений для Sidekiq. В 19.0 поддержка Redis 6 удалена; рекомендуется Valkey 7.2+ или Redis 7.2+.
* **Patroni** — кластерный менеджер для PostgreSQL, обеспечивающий автоматический failover и репликацию в конфигурациях высокой доступности.
* **Consul** — система обнаружения сервисов и конфигурации, используемая для координации узлов PostgreSQL и Gitaly Cluster в HA-конфигурациях.

## Предварительные требования

### Версия GitLab и поддержка функций

| Функция | Минимальная версия | Примечание |
| :--- | :--- | :--- |
| Omnibus GitLab (базовый) | 11.0+ | Установка через пакетный менеджер |
| `gitlab-ctl` | 11.0+ | Инструмент управления инстансом |
| Gitaly Cluster (RAFT) | 17.0+ | Высокая доступность Git-данных на VM |
| Valkey 7.2+ | 19.0+ | Замена Redis в качестве кэша и брокера |
| PostgreSQL 17 | 19.0+ | Минимально поддерживаемая версия БД |
| Envoy Gateway | 19.0+ | Сетевая точка входа для Helm-инсталляций |
| GitLab Orbit | 19.x | Графовая аналитика на ClickHouse |
| Kubernetes-интеграция (KAS) | 17.x+ | Агент для кластеров K8s |

### Необходимые знания

- Структура GitLab CI/CD, стадии (stages) и правила запуска (`rules`)
- Основы GitLab CI/CD Variables и Protected/Masked переменные
- Принципы DORA-метрик и их связи с окружениями
- Базовое понимание Kubernetes Namespaces, Services и Ingress (для сценариев с кластером)
- Основы администрирования Linux: systemd, логирование, сетевые порты

### Требования к инфраструктуре

| Компонент | Минимум | Рекомендация Production |
| :--- | :--- | :--- |
| CPU | 4 vCPU | 8+ vCPU |
| RAM | 16 ГБ | 32+ ГБ |
| Диск | 100 ГБ SSD | 500+ ГБ NVMe |
| Сеть | 1 Гбит/с | 10 Гбит/с с низкой задержкой |

## Архитектура и принципы работы

### Взаимодействие компонентов

GitLab построен на микросервисной архитектуре, где каждый компонент отвечает за свою область. Взаимодействие происходит через внутренние API и RPC-вызовы.

**Поток запросов:**

1. **Внешний запрос** (HTTP/HTTPS или SSH) поступает на точку входа (Nginx или Envoy Gateway).
2. **Веб-сервер** (Puma) обрабатывает API и веб-интерфейс.
3. **Workhorse** проксирует «тяжелые» запросы (артефакты, Git LFS, репозитории) соответствующим сервисам.
4. **GitLab Shell** обрабатывает Git-операции по SSH, обращаясь к Gitaly.
5. **Gitaly** выполняет низкоуровневые Git-операции и управляет хранилищем.
6. **Sidekiq** обрабатывает асинхронные фоновые задачи (уведомления, пайплайны, очистка).
7. **PostgreSQL** хранит метаданные (пользователи, проекты, права, пайплайны).
8. **Valkey** управляет сессиями, кэшем и очередями Sidekiq.

### Модель выполнения CI/CD

GitLab Server формирует очередь заданий, которые выбирают **GitLab Runners**. Взаимодействие происходит по Pull-модели: раннеры опрашивают сервер по HTTP(S).

**Масштабирование через Kubernetes:**
В крупных инфраструктурах используется запуск в Kubernetes, где за каждую джобу отвечает отдельный под.
* **Изоляция:** Каждый запуск происходит в "чистом" контейнере, исключая конфликты зависимостей между пайплайнами.
* **Динамические ресурсы:** Под создается только на время выполнения задачи, потребляя ресурсы кластера ровно столько, сколько указано в лимитах джобы.
* **Автомасштабирование:** Kubernetes автоматически распределяет поды раннеров по свободным нодам кластера.

### Целостность данных и доступность

* **Gitaly Cluster:** Использует Raft-консенсус для репликации Git-данных между тремя и более узлами. Обеспечивает консистентность даже при выходе из строя одной зоны.
* **PostgreSQL HA:** Patroni + Consul обеспечивают автоматический failover без единой точки отказа.
* **Geo-репликация:** Для территориально распределенных команд создаются read-only зеркала инстанса.

## Компоненты системы

| Компонент | Назначение | Тип |
| :--- | :--- | :--- |
| **Nginx / Envoy Gateway** | Входная точка трафика, SSL-termination, маршрутизация | Stateless |
| **GitLab Rails (Puma)** | Ядро приложения: API, веб-интерфейс, бизнес-логика | Stateless |
| **Workhorse** | Прокси для тяжелых HTTP-запросов (артефакты, LFS, репозитории) | Stateless |
| **GitLab Shell** | Обработка SSH-соединений для Git-операций | Stateless |
| **Gitaly** | RPC-сервис для операций с репозиториями | Stateful |
| **Sidekiq** | Фоновая обработка задач | Stateless |
| **PostgreSQL 17+** | Хранение метаданных | Stateful |
| **Valkey 7.2+** | Кэш, сессии, очереди Sidekiq | Stateful |
| **Registry** | Хранение Docker-образов | Stateful |
| **ClickHouse** | Аналитические данные, метрики DORA | Stateful |
| **Prometheus** | Сбор метрик компонентов | Stateless |
| **Grafana** | Визуализация метрик | Stateless |

### Варианты развертывания

| Метод | Особенности | Рекомендация |
| :--- | :--- | :--- |
| **Omnibus (Package)** | Простая установка и обновление. Полный контроль над компонентами. | Production (Single Node / Distributed) |
| **Hybrid** | Rails/Sidekiq в Kubernetes, Gitaly Cluster и БД на виртуальных машинах. | Enterprise HA / Large Scale |
| **Helm Chart / Operator** | Полное развертывание в Kubernetes. Gitaly в K8s не поддерживается для HA; рекомендуется VM. | Kubernetes-native (Scaling focus) |

## Управление через Omnibus

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

### 4. Управление инстансом

Подробное руководство по управлению GitLab инстансом: бэкап, восстановление, обновление, управление секретами — описано в **[Управление инстансом GitLab](../Advanced/gitlab_instance_administration.md)**.

### 7. Оптимизация производительности

Параметры настройки Puma, Sidekiq, Gitaly, PostgreSQL и Valkey описаны в **[Управлении инстансом GitLab](../Advanced/gitlab_instance_administration.md)** и **[Управлении базами данных GitLab](../Advanced/gitlab_database_management.md)**.

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

## Граничные случаи

### Ограничения и нюансы

1. **Gitaly в Kubernetes:** Gitaly Cluster (HA с RAFT-репликацией) поддерживается только на виртуальных машинах. Развертывание в Kubernetes возможно только в шардированном режиме без кластеризации.

2. **Valkey и Redis:** Начиная с GitLab 19.0, поддержка Redis 6 удалена. Для новых инсталляций используйте Valkey 7.2+ или Redis 7.2+.

3. **Envoy Gateway в Helm-инсталляциях:** Начиная с GitLab 19.0, Gateway API с Envoy Gateway становится стандартом для Helm Chart. NGINX Ingress остаётся доступным до версии 20.0.

4. **PostgreSQL 17 minimum:** Начиная с GitLab 19.0, PostgreSQL 17 является минимально поддерживаемой версией. При обновлении с 18.x убедитесь, что БД обновлена до 17+.

5. **Память для Puma и Shared Memory:** В Docker-инсталляциях стандартный `shm_size` (64MB) недостаточен для Puma и системы метрик. Рекомендуется минимум 1GB, иначе возникают ошибки 502/504.

6. **Sidekiq queue buildup:** При высокой нагрузке очередь Sidekiq может расти из-за недостаточной параллельности или блокировок в БД. Увеличьте `sidekiq['max_concurrency']` и проверьте долгие запросы.

7. **Gitaly и дисковые задержки:** Gitaly критичен к задержкам диска. Использование HDD или сетевых хранилищ с высокой задержкой приводит к таймаутам Git-операций и деградации UI.

8. **Geo-репликация и задержки:** При настройке GitLab Geo учтите, что репликация асинхронная. Secondary-ноды могут отставать на несколько секунд, что влияет на актуальность данных в read-only сценариях.

## Дополнительная информация

### Хранилище данных

Для on-prem инфраструктур рекомендуется использовать объектные хранилища (MinIO, Ceph RADOS Gateway) для артефактов, бэкапов и LFS-объектов. Это позволяет горизонтально масштабировать Rails-ноды без использования NFS.

### Опыт эксплуатации и рекомендации

* **Registry Separation:** Рекомендуется использовать внешний Container Registry (например, Harbor) или выносить встроенный Registry за пределы основного инстанса.
* **Gitaly на выделенных серверах:** Gitaly требует быстрых NVMe-дисков и выделенных ресурсов. Размещение на общих VM с другими компонентами приводит к contention по дискам и памяти.
* **SSD/NVMe обязательны:** Gitaly крайне чувствителен к задержкам диска. HDD приводит к таймаутам Git-операций и деградации UI.

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

Подробные сценарии troubleshooting, типичные ошибки и диагностические команды описаны в **[Управлении инстансом GitLab](../Advanced/gitlab_instance_administration.md)** и **[Безопасности и закреплении GitLab Server](../Advanced/gitlab_server_security_hardening.md)**.

### Лучшие практики

Базовые рекомендации по управлению инстансом, бэкапу, обновлению и безопасности перечислены в **[Управлении инстансом GitLab](../Advanced/gitlab_instance_administration.md)** и **[Администрировании GitLab в масштабе](../Advanced/gitlab_administration_at_scale.md)**.

### Критичные изменения последних версий

* **19.0**: Минимальная версия PostgreSQL повышена до 17. Поддержка Redis 6 удалена; рекомендуется Valkey 7.2+ или Redis 7.2+.
* **19.0**: В Helm-инсталляциях Envoy Gateway становится стандартом вместо NGINX Ingress.
* **19.x**: Gitaly Cluster не поддерживается в Kubernetes; требуется развертывание на VM.
* **19.x**: Появление GitLab Orbit и ClickHouse для аналитики жизненного цикла ПО.
* **18.x**: Удаление поддержки legacy-интеграций Kubernetes на базе сертификатов в пользу GitLab Agent (KAS).

### Смотрите также

* **[Установка Self-Hosted GitLab CE](../../Tutorials/self_hosted_installation.md)** — практическое руководство по развертыванию.
* **[Интеграция с Kubernetes](../Advanced/gitlab_kubernetes_integration_guide.md)** — развертывание GitLab в Kubernetes-кластерах.
* **[GitOps и GitLab](../../../GitOps/GitOps_overview.md)** — архитектурные подходы к доставке ПО.
* **[Регистрация GitLab Runner](../../Tutorials/runner_registration.md)** — настройка CI/CD после установки GitLab.
* **[GitLab + Runner через Docker Compose](../../Tutorials/gitlab_runner_docker_compose.md)** — готовый стек для быстрого старта.
* **[Управление инстансом GitLab](../Advanced/gitlab_instance_administration.md)** — бэкап, восстановление, обновление.
* **[Обновление и обслуживание GitLab](../Advanced/gitlab_upgrades_and_maintenance.md)** — zero-downtime обновления, blue-green, maintenance.
* **[Безопасность и закрепление GitLab Server](../Advanced/gitlab_server_security_hardening.md)** — закрепление ОС, SSL/TLS, защита API.
* **[Управление базами данных GitLab](../Advanced/gitlab_database_management.md)** — PostgreSQL и Valkey/Redis.
* **[Sidekiq: глубинное погружение](../Advanced/gitlab_sidekiq_deep_dive.md)** — управление очередями и воркерами.
* **[Gitaly: глубинное погружение](../Advanced/gitlab_gitaly_deep_dive.md)** — конфигурация и производительность.
* **[Администрирование GitLab в масштабе](../Advanced/gitlab_administration_at_scale.md)** — распределённые архитектуры и масштабирование.
* **[Управление Package Registry GitLab](../Advanced/gitlab_package_registry_administration.md)** — администрирование пакетов.
* **[Мониторинг и метрики GitLab CI/CD](../Advanced/monitoring_and_metrics.md)** — Prometheus, Grafana, алертинг.
* **[Наблюдаемость пайплайнов GitLab CI/CD](./gitlab_ci_observability.md)** — DORA-метрики, дашборды, OpenTelemetry.
* **[Container Registry в GitLab CI/CD](../Advanced/container_registry.md)** — управление образами, cleanup, signing.
* **[Сканирование безопасности в GitLab CI/CD](./gitlab_ci_security_scanning.md)** — SAST/DAST/Secret Detection.
* **[Compliance и Audit в GitLab CI/CD](../Advanced/compliance_and_audit.md)** — Pipeline Execution Policies.
* **[Внешняя аутентификация GitLab](../Advanced/gitlab_external_auth.md)** — LDAP, SAML, OIDC.
* **[Capacity Planning для GitLab CI/CD](../Advanced/gitlab_capacity_planning.md)** — планирование мощности CI/CD инфраструктуры.
* **[Монорепозитории в GitLab CI/CD](../Advanced/gitlab_monorepo_ci.md)** — стратегии CI/CD для монорепозиториев.
* **[GitLab Dogfooding](../Advanced/gitlab_dogfooding.md)** — использование GitLab для разработки GitLab.
