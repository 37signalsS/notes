# Мониторинг и метрики DevSecOps

**Актуально для:** DevSecOps monitoring stack 2026 (Prometheus 2.55+, Loki 3.x, Grafana 11.x, Alertmanager 0.27+)

## Определения

**Security Observability** — способность понимать состояние безопасности системы через метрики, логи и трейсы. Включает сбор данных от всех источников (CI/CD, рантайм, сканеры, аудит), их корреляцию и оповещение об аномалиях.

**Security Metrics** — количественные показатели, оценивающие эффективность security-программы: скорость исправления уязвимостей, покрытие сканированием, количество инцидентов, compliance posture.

**Security Dashboard** — визуализация security-метрик в реальном времени (Grafana, Kibana, ASPM UI) для Security-команды, разработчиков и менеджмента.

**Alerting** — автоматическое уведомление о security-событиях, требующих внимания: критические CVE, подозрительная активность в CI/CD, утечка секретов, drift конфигурации.

**SIEM (Security Information and Event Management)** — система для сбора, корреляции и анализа security-событий из разных источников (логи, аудит, сканеры, runtime sensors).

## Базовые концепции

### Источники данных для Security Observability

| Источник | Тип данных | Примеры |
| :--- | :--- | :--- |
| **CI/CD** | Логи пайплайнов, артефакты сканирования, аудит доступа | GitLab CI logs, GitHub Actions logs, SARIF-отчёты, Vault audit logs |
| **Runtime** | Системные вызовы, сетевые соединения, процессы | Falco/Tetragon alerts, auditd logs, eBPF traces |
| **Сканеры** | Результаты SAST, DAST, SCA, IaC scanning | Semgrep SARIF, Trivy JSON, Checkov reports, ZAP scans |
| **Аудит** | Действия пользователей и сервисных аккаунтов | Kubernetes audit logs, Vault audit logs, Git audit logs |
| **Сеть** | Сетевой трафик, DNS-запросы, соединения | WAF logs, proxy logs, NetFlow, DNS queries |
| **Хосты** | Изменения файлов, установка пакетов, логины | auditd, Wazuh FIM, osquery, journald |

### Ключевые метрики DevSecOps

**Coverage метрики:**
- **SAST Coverage:** процент строк кода, покрытых SAST-сканированием.
- **SCA Coverage:** процент зависимостей, просканированных SCA-инструментом.
- **IaC Coverage:** процент IaC-файлов, проверенных на misconfigurations.
- **Secrets Scan Coverage:** процент репозиториев, где настроен secret scanning.
- **Container Scan Coverage:** процент образов, просканированных на CVE перед деплоем.

**Quality метрики:**
- **False Positive Rate:** процент ложных срабатываний среди всех findings.
- **Mean Time to Triage (MTTT):** среднее время от обнаружения уязвимости до её классификации.
- **Mean Time to Remediate (MTTR):** среднее время от triage до исправления.
- **Vulnerability Escape Rate:** процент уязвимостей, обнаруженных в продакшене, хотя должны были быть пойманы в CI/CD.
- **Security Debt Ratio:** количество открытых security findings, старше 30/90 дней, относительно общего числа findings.

**Operational метрики:**
- **Pipeline Block Rate:** процент пайплайнов, заблокированных security gates.
- **Gate Latency:** время выполнения security-сканирований в CI/CD.
- **Secret Rotation Compliance:** процент секретов, ротированных в соответствии с политикой.
- **Compliance Score:** процент контрольных точек, пройденных при аудите (CIS, PCI DSS, SOC 2).
- **Incident Response Time:** время от detection до containment и remediation.

**Risk метрики:**
- **Critical/High Findings Open:** количество открытых критичных/высоких уязвимостей.
- **EPSS-weighted Risk Score:** взвешенный риск уязвимостей с учётом вероятности эксплуатации (EPSS).
- **Blast Radius:** число затронутых систем при компрометации.
- **Attack Surface:** количество открытых портов, внешних IP, публичных API-эндпоинтов.

### Архитектура Security Monitoring

```
Источники данных → Сбор → Обработка → Хранение → Визуализация → Алерты
```

**Сбор (Collection):**
- **Agents:** Falco, Wazuh, osquery, auditd — собирают данные с хостов.
- **Exporters:** Prometheus exporters, OpenTelemetry collectors — собирают метрики.
- **Log shippers:** Filebeat, Fluentd, Vector — собирают логи и отправляют в централизованное хранилище.

**Обработка (Processing):**
- **Парсинг и нормализация:** преобразование разных форматов (JSON, CEF, Syslog) в единый формат.
- **Обогащение:** добавление контекста (CMDB, asset criticality, vulnerability data).
- **Корреляция:** связывание событий из разных источников (например, Falco alert + Kubernetes audit log + Vault audit log).

**Хранение (Storage):**
- **Hot storage (SIEM):** Elasticsearch, OpenSearch — для быстрого поиска и расследования.
- **Metrics storage:** Prometheus, Thanos, Cortex — для метрик и дашбордов.
- **Cold storage:** MinIO/self-hosted object storage — для долгосрочного хранения аудит-логов (compliance).

**Визуализация (Visualization):**
- **Grafana:** дашборды для метрик (Prometheus, Loki, Tempo).
- **Kibana:** поиск и визуализация логов (Elasticsearch/OpenSearch).
- **ASPM UI:** дашборды для security findings (DefectDojo, Snyk, Cycode).

**Алерты (Alerting):**
- **Alertmanager:** агрегация и дедупликация алертов.
- **Self-hosted on-call:** Mattermost webhooks, email, SMS — уведомления дежурным.
- **Mattermost/email:** каналы для security-алертов.

## Практические сценарии

### Пример 1: Security Dashboard в Grafana (Prometheus + Loki)

Создание дашборда для отслеживания security-метрик CI/CD и рантайма.

**Предусловия:** Prometheus собирает метрики от GitLab CI, Falco, Vault; Loki собирает логи; Grafana подключена к обоим источникам.

**Панели дашборда:**

1. **Pipeline Security Gates:**
   - `gitlab_ci_jobs_total{status="failed"}[5m]` — падшие security jobs.
   - `gitlab_ci_jobs_duration_seconds{job_name="sast_scan"}` — latency SAST.
   - `trivy_vulnerabilities_total{severity="CRITICAL"}` — критичные CVE в образах.

2. **Runtime Security:**
   - `falco_alerts_total` — алерты Falco по типам (container escape, suspicious process).
   - `falco_alerts_total{priority="critical"}` — критичные алерты.

3. **Vault Audit:**
   - `vault_audit_log_entries_total` — обращения к секретам.
   - `vault_audit_log_entries_total{operation="read"}` — чтения секретов.

4. **Compliance:**
   - `cis_benchmark_score` — процент пройденных CIS-контролей.
   - `compliance_violations_total` — нарушения политик.

5. **Trends:**
   - `security_findings_open_total` — открытые findings по дням.
   - `security_findings_closed_total` — закрытые findings.
   - `mttr_seconds` — MTTR по severity.

**Validation:** дашборд загружается за <3 секунд, панели обновляются каждые 30 секунд, алерты срабатывают при превышении порогов.

### Пример 2: Security Alerting через Alertmanager

Настройка алертов на критические security-события.

**Предусловия:** Prometheus собирает метрики; Alertmanager настроен на отправку в Mattermost и email.

```yaml
# alerts.yaml
groups:
  - name: security_alerts
    rules:
      - alert: CriticalVulnerabilityInProduction
        expr: trivy_vulnerabilities_total{severity="CRITICAL", env="production"} > 0
        for: 5m
        labels:
          severity: critical
          team: platform
        annotations:
          summary: "Critical CVE in production image"
          description: "Image {{ $labels.image }} has {{ $value }} critical CVEs"

      - alert: FalcoCriticalAlert
        expr: falco_alerts_total{priority="critical"} > 0
        for: 1m
        labels:
          severity: critical
          team: sre
        annotations:
          summary: "Falco critical alert"
          description: "{{ $labels.rule }} on {{ $labels.pod_name }}"

      - alert: VaultTokenSpike
        expr: rate(vault_audit_log_entries_total{operation="read"}[5m]) > 100
        for: 2m
        labels:
          severity: warning
          team: security
        annotations:
          summary: "Vault token spike"
          description: "Unusual number of Vault reads: {{ $value | humanize }}"

      - alert: SecurityPipelineFailure
        expr: gitlab_ci_jobs_total{status="failed", job_name=~"sast_|dast_|sca_"} > 0
        for: 3m
        labels:
          severity: warning
          team: devsecops
        annotations:
          summary: "Security pipeline failed"
          description: "Job {{ $labels.job_name }} failed in {{ $labels.project }}"
```

**Validation:** алерты срабатывают при наступлении условия, отправляются в Mattermost-канал `#security-alerts` и email on-call SRE.

### Пример 3: Сбор и анализ логов Falco в Loki

Централизованный сбор security-логов с раннеров и продакшен-подобов.

**Предусловия:** Falco настроен на всех узлах; Loki развёрнут в кластере; Promtail собирает логи Falco.

**1. Поиск алертов Falco за последний час:**

```bash
# Через LogCLI
logcli query '{job="falco"} | json | priority="critical"' --since=1h

# Или через Grafana Explore
# Запрос: {job="falco"} | json | priority="critical"
```

**2. Фильтрация по namespace и поду:**

```bash
logcli query '{job="falco"} | json | k8s_ns_name="production" | pod_name="api-server-xxx"' --since=24h
```

**3. Корреляция с Kubernetes audit log:**

```bash
# Falco alert + audit log для того же пода
logcli query '{job="falco"} | json | priority="critical" | line_format "{{.time}} {{.rule}} {{.k8s_pod_name}}"' --since=1h
logcli query '{job="kube-apiserver"} | json | "api-server" | user.username="system:serviceaccount:ci"' --since=1h
```

**Validation:** логи Falco доступны в Loki, запросы возвращают результаты за <5 секунд, можно строить дашборды и алерты на основе логов.

### Пример 4: Автоматизированный сбор SARIF-отчётов в ASPM

Агрегация результатов всех сканеров в единой платформе.

**Предусловия:** DefectDojo или Snyk AppRole настроен; CI/CD экспортирует SARIF.

```yaml
# .gitlab-ci.yml
stages: [security, aspm_sync]

sast_scan:
  stage: security
  image: returntocorp/semgrep
  script:
    - semgrep scan --config auto --sarif --output gl-sast-report.sarif
  artifacts:
    reports:
      sast: gl-sast-report.sarif

aspm_sync:
  stage: aspm_sync
  image: python:3.11
  script:
    - pip install requests
    - |
      python upload_to_aspm.py \
        --url https://aspm.example.com/api/v2/import-scan \
        --token $ASPM_TOKEN \
        --product "MyApp" \
        --engagement "CI/CD" \
        --scan_type "Semgrep Scan" \
        --file gl-sast-report.sarif
```

**Validation:** findings появляются в ASPM в течение 2 минут после завершения пайплайна; дубликаты объединяются, приоритизация обновляется.

## Установка и настройка инструментов

### Bare-metal развёртывание Prometheus

Для on-premise сред без Kubernetes используйте бинарную установку с systemd. SSoT — [Bare-metal / On-Premise развёртывание Prometheus](../../Prometheus/installation/bare_metal_setup.md).

**Предусловия:** Linux host с systemd, пользователь `prometheus` без логина, доступные порты 9090, 9093, 9100.

**Ключевые моменты безопасности:**
- TLS на Web UI через `--web.config.file`
- Basic auth с хэшированными паролями
- Firewall: разрешить порты 9090, 9093, 9100 только с IP monitoring-сервера
- Self-monitoring: Prometheus собирает метрики самого себя и Alertmanager

### Установка Node Exporter на monitored хостах

Node Exporter собирает метрики ядра Linux (CPU, memory, disk, network, systemd, cgroups). SSoT — [Установка Node Exporter](../../Prometheus/installation/node_exporter_installation.md).

**Предусловия:** Linux host, пользователь `node_exporter` без логина, порт 9100 доступен для Prometheus.

**Важные коллекторы для security-мониторинга:**
- `--collector.systemd` — состояние юнитов, failed units
- `--collector.processes` — процессы, открытые дескрипторы
- `--no-collector.zfs` / `--no-collector.nfs` — отключите ненужные коллекторы для снижения overhead

### Loki + Alloy для security-логов

> **Статус:** Promtail переведён в deprecated (весна 2026). Для новых инсталляций используйте **Grafana Alloy** — универсальный коллектор телеметрии, заменяющий Promtail и Grafana Agent. Поддержка Promtail ограничена критическими багфиксами.

Сбор и индексация security-логов (Falco, auditd, nginx, application logs) через Alloy:

```bash
# Alloy: установка на monitored host
ALLOY_VERSION=1.18.0
wget https://github.com/grafana/alloy/releases/download/v${ALLOY_VERSION}/alloy-linux-amd64.zip
unzip alloy-linux-amd64.zip
cp alloy-linux-amd64 /usr/local/bin/alloy
```

```hcl
# /etc/alloy/config.alloy
// 1. Обнаружение локальных лог-файлов
discovery.file "security_logs" {
  path_targets = [{
    __path__ = "/var/log/falco/*.log",
  }]
  path_targets = [{
    __path__ = "/var/log/audit/audit.log",
  }]
  path_targets = [{
    __path__ = "/var/log/nginx/access.log",
  }]
}

// 2. Чтение обнаруженных файлов
loki.source.file "security" {
  targets    = discovery.file.security_logs.targets
  forward_to = [loki.write.loki_backend.receiver]
}

// 3. Отправка логов в Loki
loki.write "loki_backend" {
  endpoint {
    url = "http://loki:3100/loki/api/v1/push"
  }
}
```

```ini
# /etc/systemd/system/alloy.service
[Unit]
Description=Grafana Alloy
After=network.target

[Service]
Type=simple
User=root
ExecStart=/usr/local/bin/alloy run /etc/alloy/config.alloy
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

**Validation:** `systemctl status alloy` — active; в Loki запрос `{job="security"}` возвращает логи; `alloy fmt /etc/alloy/config.alloy` и `alloy lint /etc/alloy/config.alloy` — синтаксис корректен.

Для развёртывания в Kubernetes см. SSoT — [Установка Grafana Alloy в Kubernetes](../../Loki/loki_stack_setup/alloy_installation.md).

### Alertmanager для security-алертов

Alertmanager агрегирует, дедуплицирует и маршрутизирует алерты. Для security-сред используйте severity-based routing:

```yaml
# /etc/alertmanager/alertmanager.yml
global:
  resolve_timeout: 5m
  smtp_smarthost: 'localhost:25'
  smtp_from: 'alertmanager@example.com'

route:
  receiver: 'default-email'
  group_by: ['alertname', 'service', 'severity']
  group_wait: 30s
  group_interval: 5m
  repeat_interval: 4h
  routes:
    - match:
        severity: critical
      receiver: 'security-critical'
    - match:
        severity: warning
      receiver: 'security-warning'

receivers:
  - name: 'default-email'
    email_configs:
      - to: 'ops@example.com'

  - name: 'security-critical'
    email_configs:
      - to: 'security-oncall@example.com'
    webhook_configs:
      - url: 'http://mattermost.example.com/hooks/security'

  - name: 'security-warning'
    email_configs:
      - to: 'security-team@example.com'

inhibit_rules:
  - source_match:
      severity: 'critical'
    target_match:
      severity: 'warning'
    equal: ['service']
```

**Validation:** `amtool check-config alertmanager.yml` — синтаксис корректен; алерты группируются и маршрутизируются по severity.

## Оперативные команды

| Команда / Инструмент | Назначение | Ожидаемый результат |
| :--- | :--- | :--- |
| `promtool query instant --host=http://prometheus:9090 'up{job="falco"}'` | Проверка метрик Falco | 1 если Falco Up, 0 если Down |
| `logcli query '{job="falco"} | json | priority="critical"' --since=1h` | Поиск критичных алертов Falco | Список алертов за последний час |
| `grafana-cli admin reset-admin-password` | Сброс пароля Grafana | Новый пароль для admin |
| `jq '[.runs[].results[] | select(.level=="error")] | length' report.sarif` | Подсчёт критичных findings в SARIF | Число critical/high findings |
| `vault audit enable file file_path=/var/log/vault/audit.log` | Включение аудит-логирования Vault | Подтверждение включения |
| `alertmanager --config.file=alertmanager.yml` | Запуск Alertmanager | Запущен сервис на порту 9093 |
| `kubectl logs -n falco -l app=falco --tail=100` | Просмотр логов Falco | Последние 100 строк логов Falco |

## Устранение неисправностей

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| Falco не отправляет алерты | Неверная конфигурация output или сеть | Проверить `falco.yaml`: `outputs: stdout: enabled: true`, `webserver: enabled: true` |
| Loki не индексирует логи | Неправильный конфиг Promtail или Loki unreachable | Проверить `promtail-config.yaml`, убедиться что Loki доступен |
| Grafana дашборд пустой | Неправильные имена метрик/логов | Проверить query в Explore, свериться с Prometheus/Loki |
| Alertmanager не отправляет алерты | Неверный конфиг receiver или webhook недоступен | Проверить `alertmanager.yml`, webhook URL, Mattermost/email конфигурацию |
| SARIF-файл пустой | Сканер не сработал или неверный формат вывода | Проверить команду запуска сканера, убедиться что `--sarif` флаг активен |
| Vault audit log пустой | Audit device не включён или неверный путь | Проверить `vault audit list`, убедиться что путь доступен для записи |
| Prometheus не собирает метрики | Экспортер не запущен или неверный scrape config | Проверить `prometheus.yml`, убедиться что target Up |

## Граничные случаи и ограничения

### Monitoring stack как цель атаки

Prometheus, Grafana и Alertmanager часто остаются без базовой аутентификации, особенно в on-premise средах. Риски:
- **Prometheus без auth:** любой, кто имеет доступ к порту 9090, может читать все метрики, включая внутренние labels и значения. Используйте `--web.config.file` с TLS + basic auth или reverse proxy.
- **Grafana без auth:** доступ к дашбордам = доступ к визуализации security-событий. Настройте `auth.basic` и интеграцию с LDAP/OAuth.
- **Alertmanager без auth:** злоумышленник может отключать алерты или менять routing. Ограничьте доступ к порту 9093 только monitoring-сервером.

### Высокая кардинальность метрик и стоимость

Метрики с большим числом уникальных label-комбинаций (например, `user_id`, `trace_id`, `request_id` в качестве label) вызывают взрыв числа активных серий (cardinality explosion). Последствия:
- **TSDB overload:** Prometheus начинает потреблять больше памяти и диска.
- **Query latency:** сложные запросы над millions of series выполняются медленно.
- **Retention pressure:** база данных заполняется быстрее, требуется чаще удалять старые блоки.

**Рекомендация:** не используйте high-cardinality значения как labels; применяйте recording rules для агрегации; ограничьте retention по storage size.

### Single-host против cluster deployment

| Аспект | Single-host / Bare-metal | Kubernetes |
| :--- | :--- | :--- |
| **Развёртывание** | systemd unit + бинарники | Helm chart / Operator |
| **Service Discovery** | `file_sd_configs`, static_configs | Kubernetes SD, Kubelet |
| **Хранение TSDB** | Локальный диск (/var/lib/prometheus) | Persistent Volume (PVC) |
| **Масштабирование** | Ручное добавление targets | Автоматическое через CRD |
| **Резервное копирование** | `tar` + remote copy | Velero / snapshot PVC |

Для single-host сред SSoT — [Bare-metal / On-Premise развёртывание Prometheus](../../Prometheus/installation/bare_metal_setup.md).

### Log retention и compliance требования

Security-логи часто подпадают под compliance (PCI DSS, SOC 2, ISO 27001, ФЗ-152). Ключевые аспекты:
- **Hot retention:** 30–90 дней в Elasticsearch/Loki для оперативного поиска.
- **Cold/WORM:** 1–7 лет в неизменяемом хранилище (MinIO с WORM, tape libraries).
- **Access control:** RBAC в Grafana и Elasticsearch; все обращения к audit logs логируются.
- **Integrity:** cryptographic verification (hash chain, signatures) для доказательства неизменности.

См. детали в [Централизованное логирование](../../Linux/SystemAdministration/Logging/cloud_logging.md).

### Alert fatigue и настройка порогов

Избыточные алерты приводят к игнорированию критических событий. Причины:
- **Нет runbook:** алерт сработал, но инженер не знает, что делать.
- **Нет дедупликации:** один инцидент генерирует 100+ алертов.
- **Порог слишком низкий:** алерт срабатывает на плановые всплески трафика.
- **Нет приоритизации:** все алерты выглядят одинаково.

Решение: severity-based routing, inhibition rules, silencing на время деплоев, `for` параметр для de-flapping, мета-мониторинг количества алертов. Детали — в [Рекомендации по мониторингу и алертингу](../../Concepts/Observability_and_Monitoring/monitoring_alerting_recommendations.md).

### Time skew и multi-host корреляция

При корреляции событий из разных хостов критична синхронизация времени:
- **NTP/Chrony:** все monitoring-серверы и targets должны быть синхронизированы.
- **Точность:** для security-событий рекомендуется `±1 секунда` или лучше.
- **Диагностика:** `chronyc tracking`, `timedatectl status`.

### Self-monitoring blind spots

Если Prometheus или Loki недоступны, вы не видите, что происходит. Метрики саммониторинга:
- `prometheus_tsdb_head_series` — количество активных серий
- `prometheus_notifications_sent_total` — доставленные алерты
- `prometheus_config_last_reload_successful` — успешность конфигурации
- `up{job="prometheus"}` — доступность самого Prometheus

**Validation:** дашборд саммониторинга показывает `up = 0` для самого Prometheus в течение >2 минут — автоматический алерт в отдельный канал.

## Рекомендации

### Архитектура

- **Централизованный сбор:** все логи и метрики собираются в единые системы (Prometheus, Loki, SIEM).
- **Separation of concerns:** метрики, логи и трейсы хранятся в специализированных системах, но коррелируются через единый trace ID.
- **Retention policies:** hot storage 30-90 дней, cold storage 1-7 лет в зависимости от compliance.
- **Immutable audit logs:** логи аудита должны быть неизменяемыми (WORM, append-only) для compliance.

### Алертинг

- **Severity-based routing:** critical → on-call (Mattermost/email/SMS), warning → team channel, info → email.
- **Deduplication:** группировка одинаковых алертов (same fingerprint) для предотвращения alert fatigue.
- **Runbooks:** каждый тип алерта должен иметь runbook с пошаговыми действиями.
- **Escalation policy:** если алерт не подтверждён за N минут — эскалация на следующий уровень.

### Дашборды

- **Three-level dashboards:**
  - **Executive:** высокоуровневые метрики (security posture, incident count, compliance score).
  - **Operational:** метрики для SRE/Security-команды (alerts, pipeline failures, runtime anomalies).
  - **Developer:** метрики для команд (findings count, MTTR, coverage).
- **Real-time updates:** дашборды обновляются каждые 30-60 секунд для оперативного реагирования.
- **Correlation:** дашборды должны позволять коррелировать данные из разных источников (например, Falco alert + Kubernetes audit log).

### Compliance

- **Audit trail:** все security-события логируются с меткой времени, user identity, action, outcome.
- **Immutable logs:** логи аудита хранятся в неизменяемом хранилище с cryptographic verification.
- **Retention:** PCI DSS — 1 год (3 месяца hot), SOC 2 — attestation period, ISO 27001 — по политике организации.
- **Access to logs:** доступ к audit logs ограничен Security-командой и compliance officers; все обращения логируются.

## Эксплуатация DevSecOps monitoring с точки зрения Sysadmin/SRE

### systemd: управление стеком мониторинга

Все компоненты (Prometheus, Loki, Alertmanager, Node Exporter, Promtail) должны работать под systemd:

```ini
# /etc/systemd/system/prometheus.service
[Unit]
Description=Prometheus Monitoring System
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=prometheus
Group=prometheus
ExecStart=/usr/local/bin/prometheus \
  --config.file=/etc/prometheus/prometheus.yml \
  --storage.tsdb.path=/var/lib/prometheus \
  --storage.tsdb.retention.time=30d \
  --storage.tsdb.retention.size=10GB \
  --web.listen-address=:9090 \
  --web.enable-lifecycle \
  --web.enable-admin-api \
  --storage.tsdb.wal-compression=true
Restart=always
RestartSec=5
LimitNOFILE=65536

[Install]
WantedBy=multi-user.target
```

**Validation:** `systemctl status prometheus` — active (running); `journalctl -u prometheus -f` — логи без ошибок.

### Ротация логов и управление диском

Prometheus пишет TSDB в `/var/lib/prometheus`; Loki — в `/var/lib/loki`; логи приложений — в `/var/log/`. Контроль размера:

```bash
# logrotate для Prometheus (если используется файловый брокер)
cat <<'EOF' | sudo tee /etc/logrotate.d/prometheus
/var/log/prometheus/*.log {
    daily
    rotate 14
    compress
    delaycompress
    missingok
    notifempty
    copytruncate
    maxsize 100M
}
EOF

# Очистка старых блоков TSDB (если retention не сработал)
find /var/lib/prometheus -maxdepth 1 -type d -name "0*" -mtime +30 -exec rm -rf {} \;
```

**Monitoring disk usage:**
```bash
# Алерт на заполнение диска
cat <<'EOF' | sudo tee /etc/prometheus/rules/node_alerts.yml
groups:
  - name: node_alerts
    rules:
      - alert: NodeDiskSpaceLow
        expr: 100 - (node_filesystem_avail_bytes{mountpoint="/"} / node_filesystem_size_bytes{mountpoint="/"} * 100) > 85
        for: 15m
        labels:
          severity: warning
        annotations:
          summary: "Disk space low on {{ $labels.instance }}"
          description: "Free space is {{ $value | humanizePercentage }}"
EOF
```

### Firewall: разрешение scraping

На monitored хостах открывайте порт 9100 (Node Exporter) только для IP Prometheus-сервера:

```bash
# iptables
iptables -A INPUT -p tcp --dport 9100 -s 10.0.0.10 -j ACCEPT
iptables -A INPUT -p tcp --dport 9100 -j DROP

# nftables
table inet filter {
  chain input {
    type filter hook input priority 0; policy accept;
    tcp dport 9100 ip saddr 10.0.0.10 accept
    tcp dport 9100 drop
  }
}
```

### Управление сертификатами для monitoring endpoints

Если Grafana/Prometheus/Alertmanager exposed через HTTPS:

```bash
# Let's Encrypt через certbot (если есть публичный домен)
certbot certonly --nginx -d grafana.example.com --non-interactive --agree-tos -m admin@example.com
# → /etc/letsencrypt/live/grafana.example.com/fullchain.pem

# Автопродление
systemctl enable --now certbot.timer

# Или самоподписанные для internal use
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout /etc/prometheus/tls/server.key \
  -out /etc/prometheus/tls/server.crt \
  -subj "/CN=prometheus.internal"
```

### auditd: аудит конфигурации monitoring

Фиксация изменений в конфигах Prometheus, Alertmanager, Grafana:

```bash
# Правила auditd
auditctl -w /etc/prometheus/ -p wa -k prometheus_config
auditctl -w /etc/alertmanager/ -p wa -k alertmanager_config
auditctl -w /etc/grafana/ -p wa -k grafana_config
auditctl -w /usr/local/bin/prometheus -p x -k prometheus_exec
auditctl -w /usr/local/bin/alertmanager -p x -k alertmanager_exec

# Просмотр событий
ausearch -k prometheus_config -i --start recent
# → type=CONFIG_CHANGE msg=audit(...): name="/etc/prometheus/prometheus.yml" ...
```

### Резервное копирование TSDB и конфигов

```bash
# Ежедневный бэкап конфигов и правил
tar czf /backup/prometheus-config-$(date +%Y%m%d).tar.gz /etc/prometheus/
tar czf /backup/alertmanager-config-$(date +%Y%m%d).tar.gz /etc/alertmanager/

# Бэкап TSDB (после остановки Prometheus)
systemctl stop prometheus
tar czf /backup/prometheus-tsdb-$(date +%Y%m%d).tar.gz /var/lib/prometheus/
systemctl start prometheus
```

**Retention:** храните бэкапы 30–90 дней на локальном NAS, 1 год — на MinIO/WORM-хранилище.

## Дополнительная информация

### Связь с другими доменами

- **Observability:** базовые концепции observability — в **[Four Pillars of Observability](../../Concepts/Observability_and_Monitoring/four_pillars_of_observability.md)**, **[Logs Deep Dive](../../Concepts/Observability_and_Monitoring/logs_deep_dive.md)**.
- **Logging:** практическое руководство по логированию — в **[CI-CD/Testing/observability_driven_testing.md](../../CI-CD/Testing/observability_driven_testing.md)**.
- **Runtime security:** Falco, Tetragon — в **[Falco](../../Security/Tools/falco.md)**, **[Docker runtime monitoring](../../Docker/Docker_security/runtime_monitoring.md)**.
- **SIEM:** ELK Stack, Wazuh — в **[ELK_Stack](../../ELK_Stack/)**, **[Wazuh](../../Security/Tools/Wazuh/)**.

### Инструменты

- **Metrics:** Prometheus, Grafana, Thanos, Cortex, VictoriaMetrics.
- **Logs:** Loki, Elasticsearch, OpenSearch, Graylog, Splunk.
- **Traces:** Jaeger, Tempo, Zipkin.
- **SIEM:** Elastic SIEM, Wazuh, Splunk, IBM QRadar.
- **Alerting:** Alertmanager, self-hosted on-call (Mattermost, email, SMS).
- **Security-specific:** Falco, Tetragon, osquery, Wazuh.

### Frameworks

- **MITRE ATT&CK:** для mapping security events к тактикам и техникам.
- **NIST Cybersecurity Framework:** Identify, Protect, Detect, Respond, Recover.
- **SOC 2:** Trust Services Criteria — Security, Availability, Processing Integrity, Confidentiality, Privacy.

## См. также

- **[DevSecOps — обзор методологии](./devsecops_overview.md)**
- **[Bare-metal / On-Premise развёртывание Prometheus](../../Prometheus/installation/bare_metal_setup.md)**
- **[Рекомендации по мониторингу и алертингу](../../Concepts/Observability_and_Monitoring/monitoring_alerting_recommendations.md)**
