# Runbooks и Incident Response для веб-серверов

## Определения

**Incident (Инцидент)** — любое неплановое событие, которое приводит к снижению, нарушению или потере качества сервиса. В контексте веб-серверов: 5xx, падение worker'ов, OOM, заполнение диска.

**MTTR (Mean Time To Repair)** — среднее время восстановления сервиса после инцидента. Цель: минимизировать MTTR за счёт runbooks и автоматизации.

**Runbook (Плейбук)** — пошаговая инструкция по реагированию на типичный инцидент. Содержит команды диагностики, критерии escalation, шаги отката.

**Escalation Path (Путь эскалации)** — цепочка лиц, которых нужно уведомить при невозможности решить инцидент на текущем уровне. L1 → L2 → L3 → CTO.

**Postmortem (Разбор инцидента)** — документ, описывающий причину инцидента, timeline, impact, remediation, lessons learned.

**Blameless Postmortem** — разбор без поиска виноватых, с фокусом на системные причины и улучшения.

**Maintenance Window (Окно обслуживания)** — запланированное время для проведения работ, при котором допустимо снижение качества сервиса.

**Change Freeze (Заморозка изменений)** — период, в котором запрещено вносить изменения в production (например, перед чёрной пятницей).

**Backout Plan (План отката)** — пошаговый план возврата к предыдущему стабильному состоянию, если изменение приводит к инциденту.

## Основные концепции

### Классификация инцидентов

| Класс | Пример | MTTR цель | Escalation |
| :--- | :--- | :--- | :--- |
| **P1 — Critical** | Полный outage, данные под угрозой | 15-30 мин | CTO, Legal |
| **P2 — High** | Частичная недоступность, 5xx > 10% | 1-2 часа | L2, Team Lead |
| **P3 — Medium** | Деградация latency, 502/504 | 4-8 часов | L1, L2 |
| **P4 — Low** | Единичные ошибки, косметические | 24-48 часов | L1 |

### Timeline инцидента

| Стадия | Описание | Действие |
| :--- | :--- | :--- |
| **Detection** | Обнаружение (мониторинг, пользователь) | Создать тикет, собрать контекст |
| **Triage** | Оценка severity, назначение на инженера | Классифицировать P1-P4 |
| **Mitigation** | Остановка распространения (rollback, draining) | Выполнить backout plan |
| **Resolution** | Полное устранение причины | Проверить восстановление |
| **Postmortem** | Документирование, lessons learned | Через 48-72 часа |

### Компоненты Runbook

| Компонент | Описание |
| :--- | :--- |
| **Title** | Название инцидента |
| **Severity** | P1-P4 |
| **Symptoms** | Как выглядит инцидент (alert, пользовательское обращение) |
| **Diagnosis** | Команды для диагностики |
| **Mitigation** | Шаги для остановки инцидента |
| **Resolution** | Полное устранение причины |
| **Escalation** | Кто уведомлять, если не получается |
| **Backout** | План отката изменений |

## Практические сценарии

### Сценарий 1: Runbook для 502 Bad Gateway

```markdown
## Runbook: 502 Bad Gateway — Nginx

**Severity:** P2 (High)

**Symptoms:**
- Alert: `nginx_http_requests_total{status="502"} > 10`
- Пользователи жалуются: "Сайт не открывается"
- В логах Nginx: `upstream prematurely closed connection`

**Diagnosis:**
```bash
# 1. Проверить статус Nginx
systemctl status nginx

# 2. Проверить upstream
sudo nginx -T | grep -E 'proxy_pass|upstream'
ss -ltnp 'sport = :8000'

# 3. Проверить бэкенд
curl -v http://127.0.0.1:8000/health
systemctl status myapp

# 4. Проверить логи бэкенда
journalctl -u myapp --since '-30 minutes'
```

**Mitigation:**
```bash
# 1. Перезапустить бэкенд
systemctl restart myapp

# 2. Проверить статус
systemctl status myapp
curl -v http://127.0.0.1:8000/health

# 3. Перезагрузить Nginx
systemctl reload nginx
```

**Escalation:**
- Если бэкенд не запускается: L2, Team Lead
- Если проблема повторяется: L3, Architect

**Backout:**
- Откатить последний deploy бэкенда: `git revert HEAD && systemctl restart myapp`
```

### Сценарий 2: Runbook для OOM

```markdown
## Runbook: OOM Killer сработал на Nginx

**Severity:** P1 (Critical)

**Symptoms:**
- Alert: `node_exporter_oom_killer_total > 0`
- Nginx не отвечает, в логах: `killed process`
- `dmesg`: `Out of memory: Kill process 1234 (nginx)`

**Diagnosis:**
```bash
# 1. Проверить OOM события
sudo dmesg -T | grep -i oom
sudo journalctl -k -g 'oom|out of memory|killed process'

# 2. Проверить память
free -h
vmstat 1 5

# 3. Проверить процессы
ps aux --sort=-%mem | head -10
```

**Mitigation:**
```bash
# 1. Перезапустить Nginx
systemctl restart nginx

# 2. Проверить статус
systemctl status nginx
curl -v http://localhost/

# 3. Уменьшить worker_processes
sed -i 's/worker_processes auto/worker_processes 2/' /etc/nginx/nginx.conf
systemctl reload nginx
```

**Escalation:**
- Если память заканчивается: L2, инфраструктура
- Если повторяется: L3, Architect

**Backout:**
- Откатить конфиг: `git checkout HEAD -- /etc/nginx/`
- Восстановить worker_processes
```

### Сценарий 3: Incident Response протокол

```yaml
# /etc/alertmanager/incident_rules.yml
groups:
  - name: incident_rules
    rules:
      - alert: Incident502
        expr: sum(rate(nginx_http_requests_total{status="502"}[5m])) > 10
        for: 2m
        labels:
          severity: p2
          runbook: "https://wiki.example.com/runbooks/502-bad-gateway"
        annotations:
          summary: "High 502 rate"
          description: "{{ $value }} 502 errors per second"

      - alert: IncidentOOM
        expr: increase(node_exporter_oom_killer_total[5m]) > 0
        for: 0m
        labels:
          severity: p1
          runbook: "https://wiki.example.com/runbooks/oom-killer"
        annotations:
          summary: "OOM Killer triggered"
          description: "OOM on {{ $labels.instance }}"
```

### Сценарий 4: Postmortem шаблон

```markdown
# Postmortem: 502 Bad Gateway — 2026-09-24

## Summary
- **Date:** 2026-09-24
- **Duration:** 14:32 — 14:47 (15 минут)
- **Severity:** P2
- **Impact:** 5xx > 30%, 2000 пользователей затронуто

## Timeline
- 14:32 — Alert fired: 502 rate > 10/s
- 14:33 — Инженер назначен, начата диагностика
- 14:35 — Обнаружен утечка памяти в бэкенде
- 14:40 — Бэкенд перезапущен, 502 прекратились
- 14:47 — Сервис полностью восстановлен

## Root Cause
Утечка памяти в Python-приложении (не закрывались соединения с БД). При заполнении RAM процесс убит OOM Killer, Nginx вернул 502.

## Detection
Alertmanager fired `502 rate > 10/s`.

## Remediation
1. Перезапуск бэкенда
2. Уменьшение worker_processes в Nginx
3. Добавление memory limit в бэкенд

## Action Items
- [ ] Добавить memory limit в systemd unit (MaxMemory=256M)
- [ ] Настроить alert на memory usage > 80%
- [ ] Обновить runbook с шагами диагностики утечек

## Lessons Learned
- Нужно мониторить memory usage на бэкенде
- Runbook можно улучшить: добавить `smem`, `valgrind`
```

## Лучшие практики

1. **Runbook для каждого P1/P2:** 502, 504, OOM, диск, DNS, TLS.
2. **Actionable alerts:** каждый алерт должен иметь `runbook_url`. Если нельзя отреагировать — это не алерт, а шум.
3. **MTTR < 30 минут для P1:** настройте мониторинг и алерты так, чтобы детекция занимала < 5 минут.
4. **Blameless postmortem:** фокус на системные причины, не на виноватых.
5. **Escalation path:** каждый должен знать, кого уведомлять при невозможности решить инцидент.
6. **Backout plan для каждого change:** любое изменение в production должно иметь план отката.
7. **Maintenance window для изменений:** все planned changes — в окно обслуживания.
8. **Change freeze перед событиями:** чёрная пятница, релизы — заморозка изменений за 2 недели.

## Граничные случаи и ограничения

1. **Ночные инциденты:** если инженер не может решить инцидент, escalate на call rotation.
2. **Cascade failures:** один сбой приводит к цепному. Нужен circuit breaker и bulkhead.
3. **Flapping alerts:** если алерт то появляется, то исчезает — настройте `for: 5m`.
4. **Alert fatigue:** слишком много алертов → игнорирование. Сократите до actionable.
5. **No runbook:** если runbook отсутствует, MTTR растёт в разы. Начните с минимального.

## Дополнительная информация

- **[Наблюдаемость HTTP-сервисов](../../Networking/Protocols/HTTP/http_monitoring_observability.md)** — RED method, алерты.
- **[Prometheus Alertmanager](../../Prometheus/alertmanager.md)** — routing, inhibition, silencing.
- **[Prometheus recording rules](../../Prometheus/recording_rules.md)** — SLO-based alerts.
