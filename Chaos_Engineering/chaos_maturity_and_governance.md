# Chaos Maturity Model и Governance

## Определения

**Chaos Maturity Model** —框架 для оценки зрелости программы Chaos Engineering в компании. Определяет текущий уровень, выявляет пробелы и формирует дорожную карту улучшений.

**Chaos Governance** — набор процессов, политик и ролей, обеспечивающих безопасное и эффективное проведение хаос-экспериментов в production.

**Chaos Program KPIs** — метрики для оценки эффективности программы: количество экспериментов, покрытие сценариев, MTTR improvement, false positive rate.

**Risk Assessment Framework** — процесс оценки рисков перед экспериментом: идентификация критичных сервисов, определение допустимого blast radius, планирование emergency stop. Включает матрицу влияние/сложность/риск.

**Experiment Documentation Standard** — единый формат документирования экспериментов: runbook, timeline, metrics, post-mortem. Минимальный набор: objective, hypothesis, procedure, success criteria, stop conditions, emergency stop.

**Change Advisory Board (CAB) для хаоса** — группа, approve эксперименты в production, особенно для критичных сервисов. Состав: SRE Lead (chair), Platform Engineer, Service Owner, Security Engineer, Observability Engineer.

**Chaos Program KPIs** — метрики для оценки эффективности программы: experiment coverage, MTTR improvement, false positive rate, stop-switch effectiveness, time to signal, game day frequency.

## Основные концепции

### Maturity Model: 5 уровней

| Уровень | Название | Характеристики | Инструменты | Покрытие |
|:---|:---|:---|:---|:---|
| **0** | Ad Hoc | Ручное выключение серверов, нет документирования | SSH, kill | <10% сценариев |
| **1** | Manual & Staging | Ручные эксперименты в staging, базовый мониторинг | Chaos Monkey manual, basic alerts | 10-30% |
| **2** | Automated & Guardrails | Автоматизация через Chaos Mesh/Litmus, stop-switch, probes | Chaos Mesh, Litmus, Prometheus | 30-60% |
| **3** | Continuous Production | Постоянные эксперименты в production, blast radius 1-5%, Resilience as Code | Chaos Mesh CI/CD, progressive rollout | 60-90% |
| **4** | Autonomous | AI-driven experiment generation, auto-remediation, predictive resilience | ML-based hypothesis generation | 90-100% |

### Переход между уровнями

```
Level 0 → 1: Документирование первых экспериментов, базовый мониторинг
Level 1 → 2: Автоматизация, stop-switch, probes, Game Days
Level 2 → 3: CI/CD интеграция, progressive rollout, Resilience as Code
Level 3 → 4: AI-driven experiments, auto-remediation, chaos platform
```

### Governance framework

```
Pre-experiment:
1. Risk assessment
2. CAB approval (для Level 2+)
3. Runbook creation
4. Blast radius definition
5. Stop-switch configuration

During experiment:
1. Real-time monitoring
2. Emergency stop availability
3. Team notification
4. Metrics collection

Post-experiment:
1. Post-mortem
2. Audit trail
3. Metrics analysis
4. Documentation update
5. Action items
```

## Практические сценарии

### Сценарий 1: Maturity assessment

**Цель:** Оценить текущий уровень зрелости программы Chaos Engineering.

**Checklist:**

| Категория | Level 0 | Level 1 | Level 2 | Level 3 | Level 4 |
|:---|:---|:---|:---|:---|:---|
| **Automation** | Ручное | Ручное в staging | Автоматизация через Chaos Mesh | CI/CD integration | Autonomous |
| **Stop-switch** | Нет | Таймаут | Metric-based | Multi-layer | AI-predicted |
| **Probes** | Нет | Basic HTTP | HTTP/GRPC/DB | Custom business | Predictive |
| **Blast Radius** | Не контролируется | 1 под | 1-5% traffic | Progressive | Adaptive |
| **Documentation** | Ad hoc | Runbook | Templated runbook | GitOps | Automated |
| **Frequency** | Раз в квартал | Раз в месяц | Раз в неделю | Постоянно | Real-time |
| **Coverage** | <10% | 10-30% | 30-60% | 60-90% | 90-100% |

**Оценка:**

```bash
# Подсчет баллов
SCORE=0

# Automation
if [ -f "chaos-experiments/*.yaml" ]; then SCORE=$((SCORE+1)); fi
if grep -q "Chaos Mesh" CI-CD/*.yaml; then SCORE=$((SCORE+1)); fi

# Stop-switch
if grep -q "stop-switch" chaos_engineering_overview.md; then SCORE=$((SCORE+1)); fi

# Probes
if grep -q "probe" chaos_engineering_practical.md; then SCORE=$((SCORE+1)); fi

# Blast Radius
if grep -q "mode: one" chaos_engineering_tools.md; then SCORE=$((SCORE+1)); fi
if grep -q "progressive" chaos_advanced_blast_radius.md; then SCORE=$((SCORE+1)); fi

echo "Maturity Score: $SCORE / 6"
# → Level 2: Automated & Guardrails
```

### Сценарий 2: Risk assessment framework

**Цель:** Оценить риски перед экспериментом и определить допустимый blast radius.

**Risk Assessment Matrix:**

| Сервис | Влияние на бизнес | Сложность | Риск | Допустимый blast radius |
|:---|:---|:---|:---|:---|
| payment-service | Высокое | Среднее | Высокий | 1 под, canary |
| catalog-service | Среднее | Низкое | Средний | 5% трафика |
| recommendation-service | Низкое | Высокое | Низкий | 20% трафика |

**Risk Assessment Template:**

```markdown
# Risk Assessment: Experiment network-delay-payment-service

## Сервис
- Название: payment-service
- Namespace: production
- Зависимости: core-banking (critical), analytics (non-critical)

## Влияние
- Пользователи: 100K DAU
- Доход: $10K/hour
- SLA: 99.9%

## Риски
- Data loss: Нет (read-only delay)
- Financial impact: Средний (timeout = fallback to cache)
- Reputation: Высокий (пользователи увидят задержку)

## Допустимый blast radius
- Max: 1 под (mode: one)
- Duration: 5 минут
- Stop condition: error rate > 1%

## Emergency stop
- Кто: @platform-team-lead
- Как: `kubectl delete -f network-delay.yaml`
- Rollback: автоматический (stop-switch)

## Approval
- CAB approval required: Да (critical service)
- Уведомлены: #team-platform, #team-payments
```

### Сценарий 3: Experiment documentation standard

**Цель:** Единый формат документирования всех экспериментов.

**Runbook Template:**

```markdown
# Chaos Experiment Runbook

## Experiment Info
- ID: exp-2024-001
- Name: network-delay-payment-service
- Created: 2024-01-15
- Author: @platform-team
- Status: planned / running / completed / failed

## Objective
Проверить, что Circuit Breaker срабатывает при задержке 500ms на payment-service.

## Hypothesis
При задержке 500ms на 10% трафика Circuit Breaker откроется за <10s, error rate < 5%.

## Safety
- Blast Radius: 1 под
- Duration: 5 минут
- Emergency stop: @platform-team-lead
- Stop condition: error rate > 5%

## Metrics
- Baseline latency p99: 180ms
- Baseline error rate: 0.05%
- Baseline RPS: 500

## Procedure
1. Apply experiment manifest
2. Monitor metrics for 5 minutes
3. If steady state upheld → PASS
4. If stop condition triggered → FAIL, stop experiment

## Success Criteria
- [ ] Circuit Breaker opened within 10s
- [ ] Error rate < 5%
- [ ] Fallback (cache) served requests
- [ ] No data loss

## Results
| Metric | Baseline | During | After |
|--------|----------|--------|-------|
| Latency p99 | 180ms | 450ms | 185ms |
| Error rate | 0.05% | 2.1% | 0.06% |
| RPS | 500 | 480 | 500 |

## Post-mortem
- What went well: Circuit Breaker activated correctly
- What went wrong: Fallback cache miss rate was higher than expected
- Action items:
  - [ ] Increase cache TTL for payment data
  - [ ] Add cache warming on startup

## Audit
- Started: 2024-01-15 10:00:00Z
- Stopped: 2024-01-15 10:05:00Z
- Triggered stop: No
- Observability: Grafana dashboard, Jaeger traces, Loki logs
```

### Сценарий 4: Chaos program KPIs

**Цель:** Измерять эффективность программы Chaos Engineering.

**Core KPIs:**

| KPI | Формула | Target | Частота |
|:---|:---|:---|:---|
| **Experiment Coverage** | (Покрытые сценарии / Все сценарии) * 100% | > 80% | Ежемесячно |
| **MTTR Improvement** | (MTTR до - MTTR после) / MTTR до * 100% | > 30% | Ежеквартально |
| **False Positive Rate** | (False positive алерты / Все алерты) * 100% | < 10% | Ежемесячно |
| **Stop-switch Effectiveness** | (Эксперименты, остановленные stop-switch / Все деградации) * 100% | 100% | Постоянно |
| **Experiment Success Rate** | (Успешные эксперименты / Все эксперименты) * 100% | > 70% | Ежемесячно |
| **Time to Signal** | Время от инъекции до первого алерта | < 60s | Постоянно |
| **Game Day Frequency** | Количество Game Days в квартал | >= 1 | Ежеквартально |
| **Resilience Score** | (Успешные эксперименты / Все сценарии) * вес | > 80% | Ежеквартально |

**KPI Dashboard:**

```promql
# Experiment Coverage
chaos_experiments_total{status="completed"} / chaos_scenarios_total * 100

# MTTR Improvement
(chaos_mttr_before - chaos_mttr_after) / chaos_mttr_before * 100

# False Positive Rate
chaos_alerts_false_positive_total / chaos_alerts_total * 100

# Time to Signal
chaos_experiment_duration_seconds{phase="detection"} < 60
```

### Сценарий 5: Change Advisory Board (CAB) для хаоса

**Цель:** Создать процесс approve экспериментов в production для критичных сервисов.

**CAB Composition:**
- SRE Lead (chair)
- Platform Engineer
- Service Owner
- Security Engineer
- Observability Engineer

**CAB Process:**

```
1. Experiment proposal submitted (runbook, risk assessment)
2. CAB reviews: blast radius, stop conditions, emergency plan
3. CAB approves / requests changes / rejects
4. Experiment executed
5. Post-mortem presented to CAB
6. Action items tracked
```

**CAB Review Checklist:**

```markdown
- [ ] Runbook complete: objective, hypothesis, procedure
- [ ] Risk assessment: impact, blast radius, rollback plan
- [ ] Stop conditions defined: metrics, thresholds, timeout
- [ ] Observability ready: dashboards, alerts, traces
- [ ] Emergency stop tested: dry-run successful
- [ ] Team notified: all stakeholders aware
- [ ] Staging tested: experiment passed in staging
- [ ] Compliance: no PII, no regulatory impact
```

### Сценарий 6: Compliance и audit

**Цель:** Обеспечить compliance для regulated industries (finance, healthcare).

**Audit Requirements:**

| Requirement | Implementation |
|:---|:---|
| **Experiment history** | Git repository с runbook и результатами |
| **Access control** | RBAC для Chaos Engineering tools, audit log |
| **Data privacy** | Obfuscation PII в staging, no production data leaks |
| **Change management** | CAB approval для production experiments |
| **Incident correlation** | Связь между chaos experiment и incident (если есть) |
| **Metrics retention** | Prometheus retention 90 days, Grafana snapshots |

**Audit Trail Automation:**

```bash
#!/bin/bash
# post-experiment-audit.sh

EXPERIMENT_ID=$1
EXPERIMENT_NAME=$2
START_TIME=$3
END_TIME=$4
STATUS=$5

cat > audit/${EXPERIMENT_ID}.yaml <<EOF
experiment_id: ${EXPERIMENT_ID}
name: ${EXPERIMENT_NAME}
start_time: ${START_TIME}
end_time: ${END_TIME}
status: ${STATUS}
created_by: $(git config user.name)
commit: $(git rev-parse HEAD)
metrics:
  error_rate: $(curl -s http://prometheus:9090/api/v1/query?query=sum(rate(http_requests_total{experiment_id="${EXPERIMENT_ID}",status=~"5.."}[5m]))/sum(rate(http_requests_total{experiment_id="${EXPERIMENT_ID}"}[5m])) | jq '.data.result[0].value[1]' -r)
  latency_p99: $(curl -s http://prometheus:9090/api/v1/query?query=histogram_quantile(0.99,sum(rate(http_request_duration_seconds_bucket{experiment_id="${EXPERIMENT_ID}"}[5m]))) | jq '.data.result[0].value[1]' -r)
EOF

git add audit/${EXPERIMENT_ID}.yaml
git commit -m "chaos: audit ${EXPERIMENT_ID} ${STATUS}"
git push
```

## Операции и команды

### Maturity assessment script

```bash
#!/bin/bash
# chaos-maturity-assessment.sh

SCORE=0

# Level 1: Manual & Staging
if [ -d "chaos-experiments" ]; then SCORE=$((SCORE+1)); fi
if grep -q "staging" chaos_*.md; then SCORE=$((SCORE+1)); fi

# Level 2: Automated & Guardrails
if grep -q "Chaos Mesh" chaos_engineering_tools.md; then SCORE=$((SCORE+1)); fi
if grep -q "stop-switch" chaos_engineering_overview.md; then SCORE=$((SCORE+1)); fi
if grep -q "probe" chaos_engineering_practical.md; then SCORE=$((SCORE+1)); fi

# Level 3: Continuous Production
if grep -q "progressive" chaos_advanced_blast_radius.md; then SCORE=$((SCORE+1)); fi
if [ -f ".gitlab-ci.yml" ] && grep -q "chaos" .gitlab-ci.yml; then SCORE=$((SCORE+1)); fi

echo "Maturity Score: $SCORE / 7"
case $SCORE in
  0-2) echo "Level: 0-1 (Ad Hoc / Manual)" ;;
  3-4) echo "Level: 2 (Automated & Guardrails)" ;;
  5-6) echo "Level: 3 (Continuous Production)" ;;
  7) echo "Level: 4 (Autonomous)" ;;
esac
```

### KPI collection

```bash
#!/bin/bash
# chaos-kpi-collection.sh

# Experiment Coverage
TOTAL_SCENARIOS=50
COMPLETED_EXPERIMENTS=$(curl -s http://prometheus:9090/api/v1/query?query=chaos_experiments_total{status="completed"} | jq '.data.result[0].value[1]' -r)
COVERAGE=$(echo "scale=2; $COMPLETED_EXPERIMENTS / $TOTAL_SCENARIOS * 100" | bc)
echo "Experiment Coverage: ${COVERAGE}%"

# MTTR Improvement
MTTR_BEFORE=45  # minutes
MTTR_AFTER=$(curl -s http://prometheus:9090/api/v1/query?query=chaos_mttr_seconds / 60 | jq '.data.result[0].value[1]' -r)
MTTR_IMPROVEMENT=$(echo "scale=2; ($MTTR_BEFORE - $MTTR_AFTER) / $MTTR_BEFORE * 100" | bc)
echo "MTTR Improvement: ${MTTR_IMPROVEMENT}%"

# Time to Signal
TIME_TO_SIGNAL=$(curl -s http://prometheus:9090/api/v1/query?query=chaos_experiment_duration_seconds{phase="detection"} | jq '.data.result[0].value[1]' -r)
echo "Time to Signal: ${TIME_TO_SIGNAL}s"

# False Positive Rate
FALSE_POSITIVES=$(curl -s http://prometheus:9090/api/v1/query?query=chaos_alerts_false_positive_total | jq '.data.result[0].value[1]' -r)
TOTAL_ALERTS=$(curl -s http://prometheus:9090/api/v1/query?query=chaos_alerts_total | jq '.data.result[0].value[1]' -r)
FALSE_POSITIVE_RATE=$(echo "scale=2; $FALSE_POSITIVES / $TOTAL_ALERTS * 100" | bc)
echo "False Positive Rate: ${FALSE_POSITIVE_RATE}%"
```

### CAB approval workflow

```bash
#!/bin/bash
# chaos-cab-approval.sh

EXPERIMENT_ID=$1
RUNBOOK=runbooks/${EXPERIMENT_ID}.md

# Проверка runbook
if [ ! -f "$RUNBOOK" ]; then
  echo "ERROR: Runbook not found"
  exit 1
fi

# Проверка risk assessment
if ! grep -q "Risk Assessment" $RUNBOOK; then
  echo "ERROR: Risk assessment missing"
  exit 1
fi

# Проверка stop conditions
if ! grep -q "Stop condition" $RUNBOOK; then
  echo "ERROR: Stop conditions missing"
  exit 1
fi

# CAB approval (manual)
echo "Runbook: $RUNBOOK"
echo "Please review and approve via:"
echo "  git commit -m 'chaos: approve $EXPERIMENT_ID'"
echo "Or reject with:"
echo "  git commit -m 'chaos: reject $EXPERIMENT_ID - <reason>'"
```

## Устранение неполадок

| Проблема | Вероятная причина | Решение |
|:---|:---|:---|
| **Maturity assessment не отражает реальность** | Чеклист слишком общий или устаревший | Обновите чеклист под конкретные инструменты и процессы |
| **KPI не собираются** | Метрики chaos не экспортируются | Добавьте chaos_experiment_* метрики в Prometheus |
| **CAB approval bottleneck** | Слишком много экспериментов или медленный review | Автоматизируйте low-risk эксперименты, оставьте CAB для critical |
| **Audit trail не ведется** | Нет automation или Git process | Настройте post-experiment hook, автоматический commit |
| **Compliance violation** | Эксперимент без approval или в restricted timeframe | Добавьте pre-flight compliance check в CI/CD |
| **Risk assessment игнорируется** | Нет enforcement или penalties | Интегрируйте risk assessment в deployment pipeline |
| **Documentation outdated** | Runbooks не обновляются после экспериментов | Настройте post-experiment reminder, assign action items |
| **Metrics retention expired** | Prometheus retention < 90 days | Увеличьте `--storage.tsdb.retention.time=90d` |

## Лучшие практики

### Maturity Model

1. **Оценивайте зрелость регулярно** — раз в квартал.
2. **Фокусируйтесь на одном уровне за раз** — не перескакивайте через уровень.
3. **Автоматизируйте на уровне 2+** — ручные эксперименты не масштабируются.
4. **Ведите metrics-driven approach** — измеряйте покрытие, MTTR, success rate.

### Governance

5. **Создайте Chaos Engineering policy** — документ, описывающий процессы, роли, approval workflow.
6. **Назначьте Chaos Engineering owner** — ответственный за программу.
7. **Настройте CAB для критичных сервисов** — approval workflow для Level 2+.
8. **Имейте emergency stop procedure** — документированный, протестированный.
9. **Ведите audit trail** — все эксперименты в Git, с метриками и post-mortem.

### Risk Assessment

10. **Оценивайте риск перед каждым экспериментом** — даже для Level 3.
11. **Определите допустимый blast radius** — на основе бизнес-влияния.
12. **Планируйте rollback** — автоматический откат при stop condition.
13. **Уведомляйте команду** — все stakeholders должны знать о эксперименте.

### Documentation

14. **Используйте единый runbook template** — все эксперименты документируются одинаково.
15. **Включите objective, hypothesis, procedure, success criteria** — минимальный набор.
16. **Фиксируйте timeline** — время начала, алертов, остановки, восстановления.
17. **Проводите post-mortem** — даже для успешных экспериментов.

### Compliance

18. **Соответствуйте regulatory requirements** — PCI DSS, HIPAA, GDPR.
19. **Не используйте production PII** — staging с обезличенными данными.
20. **Храните audit trail 90+ days** — для compliance audits.

## Дополнительная информация

### Связанные модели зрелости

- **DevSecOps Maturity Model (DSEC)** — для программ безопасности.
- **DORA Metrics** — для DevOps performance.
- **SRE Maturity Model** — для reliability programs.

### См. также

- [Chaos Engineering — обзор](chaos_engineering_overview.md) — Chaos Maturity Model (кратко).
- [Chaos Engineering — практическое руководство](chaos_engineering_practical.md) — Game Days.
- [Chaos Engineering — метрики](chaos_engineering_metrics.md) — KPIs для программы.
