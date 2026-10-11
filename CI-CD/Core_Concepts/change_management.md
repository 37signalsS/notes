# Управление изменениями и Change Advisory Board (CAB)

**Актуально для:** self-hosted CI/CD (GitLab CI, GitHub Actions, Jenkins) 2024–2026

> Область применения: практики DevOps, SRE и SysAdmin при эксплуатации самостоятельно развёрнутых систем. Материалы, относящиеся к публичным облакам и технологиям искусственного интеллекта, не рассматриваются.
>
> **Примечание:** Общие определения Change Management, типы изменений и связь с SDLC описаны в **[SDLC Overview](./sdlc_overview.md)**. Данный файл фокусируется на практической интеграции Change Management и CAB непосредственно в CI/CD-пайплайны.

## Определения

- **Change Management в CI/CD** — встроенный в пайплайн набор контролей, обеспечивающих баланс между скоростью поставки и контролем рисков. В отличие от классического ITIL, в DevOps большая часть проверок выполняется автоматически, а CAB выступает advisory органом.
- **Change Advisory Board (CAB)** — коллегиальный орган, оценивающий риски значимых изменений. В CI/CD CAB не утверждает каждый деплой; его роль — стратегический обзор паттернов, оценка новых типов рисков, улучшение процессов.
- **Emergency CAB (ECAB)** — усечённый состав CAB для экстренных изменений (incident response, security patch). Действует по упрощённой процедуре с пост-фактум ревью.
- **Standard Change (Стандартное изменение)** — низкорисковое, повторяющееся изменение с заранее утверждённой процедурой. Не требует согласования на каждом запуске; примеры: деплой через проверенный пайплайн, rotation сертификатов.
- **Normal Change (Обычное изменение)** — изменение, требующее оценки риска и утверждения через CAB или делегированный Change Authority. Примеры: новый сервис в production, миграция БД, изменение network policy.
- **Change Authority (Уполномоченный)** — лицо или роль, имеющая право утверждать изменения определённого типа без полного собрания CAB. Обычно Tech Lead / Staff Engineer / DBA.
- **RFC (Request for Change)** — формальная заявка на изменение, содержащая описание, обоснование, план отката, окно выполнения и оценку риска.
- **Change Window (Окно изменений)** — заблагуновременно согласованный интервал времени для выполнения изменений с потенциальным влиянием на business.
- **Rollback Plan (План отката)** — документированная процедура возврата системы в предыдущее стабильное состояние. Обязателен для всех Normal и Emergency изменений.
- **Change Failure Rate** — доля deployments, приведших к инциденту или requiring immediate fix/rollback. Ключевая метрика DORA и CAB-аналитики.
- **Deployment Frequency** — частота deployments в production. DORA-метрика, на которую влияет эффективность Change Management.

## Основные концепции

### Теоретические основы для CI/CD

Change Management в контексте CI/CD опирается на несколько математических и системных принципов:

- **Закон Литтла для Change Management:** связь между параллельными изменениями в системе (L), скоростью их подачи (λ) и средним временем прохождения approval (W): `L = λ × W`. Применяется для расчёта количества Change Authority, необходимого для обслуживания текущей частоты deployments.
- **USE-методология для Change Management:**
  - **Utilization:** процент времени Change Authority, занятого approval'ами
  - **Saturation:** пиковая длина очереди на approval при Release Burst
  - **Errors:** доля изменений, застрявших в approval дольше SLA
- **Change Failure Budget:** лимит на количество failed deployments в unit времени. При исчерпании — автоматический change freeze или downgrade deploy frequency. Аналогия с SLO error budget.
- **Queueing Theory для approval gates:** Время ожидания approval растёт экспоненциально при подходе утилизации Change Authority к 100%. При 70% утилизации среднее время ожидания в 2–3 раза ниже, чем при 90%.

### Эволюция Change Management: от ITIL 3 к DevOps

Классический ITIL 3 подход подразумевал, что каждое изменение проходит через CAB. В условиях CI/CD, где elite-команды деплоят по запросу несколько раз в день, такой подход становится узким местом (bottleneck) и противоречит цели автоматизации.

ITIL 4 переименовал практику в **Change Enablement**, смещая фокус с контроля на облегчение безопасных изменений. Ключевые принципы:

1. **Не каждое изменение требует CAB.** Standard changes выполняются по pre-approved template.
2. **CAB — advisory, не approval board.** Его роль — стратегический обзор паттернов, оценка новых рисков, улучшение процессов, а не утверждение каждого деплоя.
3. **Делегирование Authority.** Change Authority decentralizes approval для типовых изменений, разгружая CAB.
4. **Автоматизация в качестве контроля.** Патч, прошедший проверенный пайплайн с guardrails, сам является change control. Audit trail (Git history, CI logs) заменяет бумажный RFC.
5. **Риск-ориентированный подход.** Изменения классифицируются по риску, а не по формальному признаку. Высокорисковые (сеть, DNS, конфигурация контроллеров) проходят CAB; низкорисковые (tag update, scheduled deployment) — автоматически.

### Интеграция Change Management с CI/CD

В зрелой DevOps-организации Change Management не отдельный процесс, а встроенный в пайплайн набор контролей:

```
Commit → Lint → Test → Security Scan → Approval Gate → Deploy → Verify → Rollback
                         ↑                                       ↑
                    Change Authority                        Automated SLO Check
```

- **Approval Gate:** встроенный в пайплайн шаг требующий approve от Change Authority. В GitLab — `approval_rules`, в GitHub — `required_reviewers`.
- **Automated Controls:** SAST, SCA, линтинг, тесты — выполняются автоматически и служат первыми фильтрами.
- **Audit Trail:** Git history + CI logs + deployment records = полноценный change log без бумажных форм.
- **Change Calendar:** интеграция пайплайна с ITSM-инструментом для визуализации запланированных деплоев.
- **Fast Rollback:** автоматический откат при нарушении SLO — главный контрольный механизм для high-frequency deployments.

### Паттерны нагрузки на Change Management

| Паттерн | Описание | Влияние на CAB/Authority |
|:---|:---|:---|
| **Commit Storm** | Много small PRs в короткий период | Standard changes → auto-approve, CAB не затрагивается |
| **Merge Wave** | Bulk merge после code review sprint | Spike в approval queue → нужен backup approver |
| **Nightly Batch** | Nightly builds с deployments | Pre-approved window → автоматически |
| **Release Burst** | Coordinated multi-service release | ECAB или pre-planned CAB session |
| **Flaky Retry Storm** | Автоперезапуски failing jobs, создающие мусор в approval queue | Rate-limit auto-approvals, alert на аномалии |

### CAB в современных практиках

Современный CAB — это не еженедельное 2-часовое собрание для утверждения деплоев, а:

- **Ad-hoc встречи:** CAB собирается только для significant changes или при новых типах рисков.
- **Async review:** изменения отправляются на ревью заранее; представление занимает 1–2 минуты на пункт.
- **Metrics-driven:** CAB анализирует агрегированные паттерны (change failure rate по типам, blast radius), а не отдельные RFC.
- **Continuous Improvement:** каждый постмортем и RCA feeding back в change policies.

### Роли и ответственность

| Роль | Обязанности |
|:---|:---|
| **Change Manager** | Управление процессом, календарём, коммуникация. Принимает окончательное решение о green light. |
| **Change Authority** | Утверждение изменений определённого типа без полного CAB. Обычно Tech Lead / Staff Engineer. |
| **CAB** | Стратегический обзор, оценка новых типов рисков, улучшение процессов. Собирается по необходимости, а не по расписанию. |
| **Change Owner** | Инициатор и ответственный за изменение от бизнеса/технической стороны. Подготовка RFC, тестирование, план отката. |
| **IC (Incident Commander)** | В emergency change координирует выполнение и пост-фактум ревью. |

## Практические сценарии

### Сценарий 1: Классификация изменений и матрица approval

#### Предпосылки
- Команда использует GitLab CI с protected environments.
- Есть реестр standard changes.

#### Матрица approval

| Тип изменения | Approval механизм | Требуется CAB |
|:---|:---|:---|
| Deploy в staging | Автоматически (пайплайн) | Нет |
| Deploy в production (canary < 5%) | Auto-approve при SLO green | Нет |
| Deploy в production (full rollout) | Change Owner + Tech Lead | ECAB для emergency |
| Изменение network policy | Change Owner + Security Lead | CAB (async) |
| Новая БД миграция (большой ALTER) | DBA + Change Owner | CAB (async) |
| Emergency hotfix | IC + single approver | ECAB (post-review) |

#### Пошаговая инструкция
1. Завести реестр standard changes в runbook.
2. Настроить GitLab approval rules для protected environments.
3. Для значимых изменений создавать RFC в формате Markdown в MR.
4. CAB собирается async: комментарии в MR + optional call при разногласиях.

#### Валидация
- Все production deployments имеют audit trail в GitLab.
- Standard changes проходят без задержки.
- CAB участвует только в significant changes.

#### Устранение неполадок
- **CAB bottleneck:** Слишком many changes идут на CAB. **Решение:** Переclassify как standard; делегировать authority; automated pre-checks.
- **Change freeze перед релизом:** Слишком много concurrent changes. **Решение:** Change calendar, deployment freezes исключительно для критичных периодов.

---

### Сценарий 2: Approval Gate в пайплайне (GitLab CI)

#### Предпосылки
- GitLab 17.x+.
- Protected environments настроены.

#### Пример конфигурации

```yaml
stages:
  - build
  - test
  - security
  - deploy

deploy_production:
  stage: deploy
  environment:
    name: production
    url: https://app.internal
  rules:
    - if: $CI_COMMIT_BRANCH == "main"
  script:
    - kubectl apply -f k8s/
  when: manual
  allow_failure: false
```

#### Approval Rules (GitLab UI)
1. **Production deployment:** минимум 1 approve от Tech Lead.
2. **Infrastructure changes:** минимум 1 approve от SRE + 1 от Security.
3. **Database migrations:** DBA approval required.

#### Валидация
- Деплой невозможен без approve.
- Audit log в GitLab содержит кто, когда, почему approve.

---

### Сценарий 3: Post-Incident Change Review (ECAB workflow)

#### Предпосылки
- Произошёл production incident.
- Требуется emergency change для фикса.

#### Workflow
1. **Detect:** Incident Commander назначен.
2. **Triage:** Оценка SEV. Если SEV1/SEV2 — ECAB.
3. **ECAB:** IC + DBA + Security Lead (async call или чат). Обсуждают: blast radius, rollback plan, need for CAB later.
4. **Implement:** Hotfix deploy через пайплайн с expedited approval.
5. **Post-review:** Через 48 часов — полный CAB review изменения, RCA, action items.

#### Валидация
- Hotfix deployed за < 30 минут.
- ECAB decision documented в incident ticket.
- Post-review scheduled на следующую неделю.

---

### Сценарий 4: Change Calendar и Thunderclap Prevention

#### Предпосылки
- Несколько команд деплоят в одну инфраструктуру.
- Есть risk коллизий изменений (thunderclap).

#### Решение
1. Внедрить shared Change Calendar (календарь изменений).
2. Каждая команда помечает planned deployments за неделю.
3. Автоматические проверки: если >3 deployments в одном окне — alert CAB.
4. Разделить deployment windows по командам (например, Team A — вторник/четверг, Team B — среда/пятница).

#### Валидация
- Нет коллизий deployments.
- CAB aware всех planned changes.
- Change Failure Rate снижается при снижении concurrency.

#### Устранение неполадок
- **Thunderclap detected:** Слишком много deployments в одно окно. **Решение:** Stagger windows, automated conflict detection.

---

### Сценарий 5: Automated Change Validation (Shift-Left Controls)

#### Предпосылки
- Команда хочет минимизировать нагрузку на CAB.
- Паттерн: 80% изменений — standard, 15% — normal, 5% — emergency.

#### Решение
1. Настроить пайплайн с automated pre-checks:
   - SAST/SCA/линтинг
   - Unit/integration tests
   - Infrastructure diff validation (terraform plan, kubeconform)
   - Security policy check (OPA/Gatekeeper)
2. Если все automated checks pass → auto-approve как standard change.
3. Если fail → change owner получает feedback, исправляет, повторяет.
4. CAB видит только changes, которые прошли automated gates.

#### Валидация
- CAB workload снизился на 70–80%.
- Mean Time To Approval (MTTA) для standard changes < 5 минут.
- Change Failure Rate для auto-approved changes < 1%.

#### Устранение неполадок
- **Auto-approve для risky change:** Automated checks пропустили проблему. **Решение:** Добавить canary deployment с automated SLO check, быстрый rollback при нарушении.
- **Flaky tests блокируют approvals:** Tests иногда fail без причины. **Решение:** Flaky test quarantine, quarantine period before removing from pre-checks.

---

### Сценарий 6: Metrics-driven CAB Review

#### Предпосылки
- CAB встречается раз в месяц, но не знает, что анализировать.
- Нет данных для continuous improvement.

#### Решение
1. Внедрить дашборд CAB Metrics:
   - Change Failure Rate по типам изменений
   - Deployment Frequency и Lead Time for Changes
   - Mean Time To Restore (MTTR)
   - % changes requiring CAB approval
   - Approval latency (среднее время от создания RFC до approval)
2. На каждом CAB meeting разбирать только outliers и trends.
3. Action items feeding back в runbook и approval policies.

#### Валидация
- CAB meeting time сократился с 2 часов до 30 минут.
- Change Failure Rate снижается на 10–15% каждый квартал.
- Документированные lessons learned.

#### Устранение неполадок
- **CAB has no data:** Нет метрик. **Решение:** Подключить Prometheus/Grafana к CI/CD logs, агрегировать deployment events.
- **Metrics не actionable:** Есть данные, но непонятно, что с ними делать. **Решение:** Добавить annotation к метрикам (что произошло в этот день).

---

### Сценарий 7: ECAB War Room Playbook

#### Предпосылки
- SEV1 incident требует emergency change.
- ECAB должен собраться за 15 минут.

#### Playbook
1. **Alert:** PagerDuty/OpsGenie alert IC + ECAB members.
2. **Async War Room:** Slack/Matrix канал #ecab-war-room.
3. **ECAB Decision Template:**
   - Blast radius: какие сервисы/данные затронуты?
   - Rollback plan: что, если фикс не сработает?
   - Approval: кто approves emergency change?
   - Communication: кто оповещает stakeholders?
4. **Post-review:** Через 48 часов — полный CAB review.

#### Валидация
- Hotfix deployed за < 30 минут.
- ECAB decision documented в incident ticket.
- Post-review scheduled на следующую неделю.

#### Устранение неполадок
- **ECAB members unavailable:** Backup approvers не определены. **Решение:** Pre-approved backup list, escalation policy.
- **No rollback plan:** Неясно, как откатиться. **Решение:** Pre-written rollback runbook для каждого типа changes.

## Рекомендации

- **Shift left:** большая часть контроля — в автоматических проверках пайплайна, а не в CAB.
- **Document standard changes:** чем больше изменений классифицировано как standard, тем меньше нагрузка на CAB.
- **Async over sync:** CAB review через comments/MR, а не встречи.
- **Measure:** отслеживайте Lead Time для approvals, % changes requiring CAB, change failure rate по типам.
- **Rollback first:** план отката пишется до начала изменения, а не после.
- **Change calendar:** визуализируйте запланированные изменения, чтобы избегать «thunderclap» (много изменений одновременно).
- **Delegation over centralization:** Change Authority ближе к команде — меньше overhead.
- **Audit trail by default:** Используйте Git + CI logs как primary source of truth; бумажные формы только для compliance.
- **Continuous learning:** Каждый RCA feeding back в change policies и standard change registry.

## Ограничения и крайние случаи

- **Multi-tenancy и честность:** Общий флот между командами требует Fair Share политик, иначе одна команда может monopolise capacity Change Authority.
- **Регулируемые отрасли:** В финансовом/медицинском секторе CAB может быть обязательным (SOC 2, HIPAA, PCI DSS). Автоматизация не отменяет требования к documented approval.
- **Legacy системы:** Для систем без CI/CD Change Management остаётся mostly manual. Измеряйте Lead Time от approval ticket до деплоя.
- **Эффект масштаба:** При >1000 deployments в неделю CAB должен стать полностью async и metrics-driven; встречи только для anomalies.
- **Конфликт Deployment Frequency и Stability:** Агрессивное увеличение Deployment Frequency без improvement automated controls приводит к росту Change Failure Rate. CAB не компенсирует плохие пайплайны.

## См. также

* **[SDLC Overview](./sdlc_overview.md)** — общие концепции Change Management, типы изменений, связь с жизненным циклом разработки.
* **[Incident Response (SRE)](./incident_response_sre.md)** — процедуры реагирования на инциденты, включая ECAB.
* **[Compliance and Audit](../GitLab_CI/Advanced/compliance_and_audit.md)** — контроль изменений в регулируемых отраслях.
* **[DORA Metrics](./dora_metrics.md)** — влияние Change Management на Deployment Frequency и Lead Time.
