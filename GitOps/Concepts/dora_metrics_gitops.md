# DORA-метрики в GitOps: измерение скорости и стабильности доставки

> **Актуальность (2026):** Четыре ключевые метрики DORA (Deployment Frequency, Lead Time for Changes, Change Failure Rate, MTTR) остаются стандартным языком разговора о зрелости доставки — в том числе на собеседованиях. GitOps-стек дает все сигналы для их измерения «бесплатно»: каждая доставка — это событие синхронизации с фиксацией ревизии, а не строка в логах CI.

## Предварительные требования

| Компонент | Требование |
| :--- | :--- |
| Метрики агентов | Prometheus с экспозицией Argo CD (`argocd_app_*`) или Flux (`gotk_*`) |
| События | Notifications → Loki/webhook; либо экспорт событий контроллеров ([аудит](./audit_logs.md)) |
| Метаданные Git | Доступ к истории репозиториев (время мерджей, авторы) |
| Визуализация | Grafana-дашборд или специализированный инструмент (DevLake и др.) |

## Определения

- **Deployment Frequency (DF)**: Как часто организация/команда выкатывает изменения в продакшен. Единица измерения — успешный деплой, а не коммит и не запуск пайплайна.
- **Lead Time for Changes**: Время от коммита (мерджа в основную ветку) до его работы в продакшене. Меряет скорость конвейера целиком, включая ожидания и гейты.
- **Change Failure Rate (CFR)**: Доля деплоев, приведших к деградации продакшена (откат, hotfix, инцидент), от общего числа деплоев.
- **MTTR / Failed Deployment Recovery Time**: Среднее время восстановления после неудачного изменения — от обнаружения до работоспособного состояния.
- **Тире производительности** (ориентировочные пороги ежегодных отчетов Accelerate/DORA; границы смещаются год от года):

| Тир | DF | Lead Time | CFR | MTTR |
| :--- | :--- | :--- | :--- | :--- |
| Elite | по требованию (несколько раз в день) | < 1 дня | ~5% | < 1 часа |
| High | ежедневно–еженедельно | 1 день – 1 неделя | ~10% | < 1 дня |
| Medium | еженедельно–ежемесячно | 1–4 недели | ~15% | 1–7 дней |
| Low | реже раза в месяц | > месяца | > 30%? (варьируется) | > недели |

Пороговые значения — ориентир для самооценки, а не KPI: слепая гонка за тирями искажает поведение системы доставки.

## Базовые концепции

### GitOps дает сигналы бесплатно

В push-моделях «деплой» приходится реконструировать из логов CI, которые ничего не знают о фактическом состоянии кластера. В GitOps деплой — это наблюдаемое событие:

| Сигнал | Argo CD | Flux |
| :--- | :--- | :--- |
| Успешный деплой ревизии R | `argocd_app_sync_total{phase="Succeeded"}`, история `argocd app history` | Статус Kustomization/HelmRelease + `lastAppliedRevision`, метрики `gotk_reconcile_*` |
| Время синхронизации | `argocd_app_sync_duration_seconds` | длительность reconcile в метриках контроллера |
| Неудачный деплой | `phase="Failed"/"Error"`, статус Degraded | Ready=False, `gotk_suspend/reconcile` ошибки |
| Откат | UI/CLI rollback события + revert-коммит | revert-коммит → новая синхронизация |
| Журнал изменений | История Git = полный лог того, что и когда должно было примениться | то же |

### Соответствие метрик и источников

1. **DF** = количество успешных синхронизаций prod-приложений на новую ревизию за период. Фильтровать только целевые среды (project/env) и исключать bot-коммиты, если они завышают цифру.
2. **Lead Time** = `t(первая успешная prod-синхронизация, содержащая SHA)` − `t(merge этого SHA)`. Ключевая операция — корреляция commit SHA между Git и историей приложения.
3. **CFR** = деплои, после которых в окне N часов произошел rollback/hotfix/алерт Degraded, деленные на все деплои. Окно корреляции выбирается явно (обычно 1–24 ч).
4. **MTTR** = `t(работоспособное состояние)` − `t(обнаружения)`; при откате через git revert — время revert-мержа до зеленого Health.

### Подводные камни измерений

- **Не те деплои**: без фильтра сред DF считает dev-раскатки — цифра красивая и бесполезная.
- **Squash/cherry-pick ломают SHA-корреляцию**: lead time считается по deploy-SHA (тому, что реально в кластере), а не по PR-номерам.
- **Rollforward ≠ провал**: если исправление ошибки выкатывается новым деплоем за минуты, это может быть как низкий MTTR, так и высокий CFR — определите классификацию один раз и письменно.
- **Bot-шум**: автоматические обновления (Renovate/Image Updater) увеличивают DF и могут снижать perceived lead time. Либо исключайте ботов, либо считайте отдельной серией.
- **Vanity metrics**: рост DF сам по себе не цель; смотреть четыре метрики вместе (DF↑ при CFR↑ — сигнал о слабых гейтах).

## Практические сценарии

### Сценарий 1: Deployment Frequency из метрик Argo CD (Grafana)

```promql
# Деплои в прод за последние 30 дней (по проекту production)
sum(increase(argocd_app_sync_total{project="production", phase="Succeeded"}[30d]))

# Средняя длительность синхронизации (тренд производительности конвейера)
avg(rate(argocd_app_sync_duration_seconds_sum{project="production"}[7d]))
 /
avg(rate(argocd_app_sync_duration_seconds_count{project="production"}[7d]))
```

Для Flux эквивалент — счетчики reconcile по Kustomization/HelmRelease с метками namespace/path прод-окружения. Дашборд: DF по дням с разбивкой по сервисам + линия тренда 90 дней.

Ограничение подхода: метрики считают **синхронизации**, а не уникальные изменения — несколько правок одним коммитом считаются одним деплоем, а suspend/resume и повторные sync одной ревизии надо отфильтровывать по revision history.

### Сценарий 2: Lead Time корреляцией Git ↔ история синхронизаций

```bash
# 1. Экспорт истории деплоев приложения (SHA → время)
argocd app history billing-prod -o json \
  | jq -r '.[] | [.revision, .deployedAt] | @tsv' > /tmp/syncs.tsv

# 2. Мержи основной ветки (SHA → unixtime)
git log --merges --pretty=format:'%H\t%ct' origin/main > /tmp/merges.tsv
```

```python
#!/usr/bin/env python3
# join_leadtime.py — lead time для каждого мержа
import csv, sys

syncs = {}                                  # sha -> время первого деплоя
with open("/tmp/syncs.tsv") as f:
    for sha, deployed_at in csv.reader(f, delimiter="\t"):
        from datetime import datetime
        t = datetime.fromisoformat(deployed_at.replace("Z", "+00:00")).timestamp()
        syncs.setdefault(sha[:12], t)       # первое попадание SHA в прод

latencies = []
with open("/tmp/merges.tsv") as f:
    for sha, merged_at in csv.reader(f, delimiter="\t"):
        if sha[:12] in syncs:
            latencies.append(syncs[sha[:12]] - int(merged_at))

if latencies:
    latencies.sort()
    p50 = latencies[len(latencies)//2] / 3600
    print(f"lead time p50: {p50:.1f} h, n={len(latencies)}")
else:
    print("нет корреляции SHA — проверьте squash-политики")
```

Если история приложения хранит только агрегированные ревизии (squash-мерджи, rendered manifests), коррелируйте по digest образа: CI записывает соответствие SHA→digest, а digest виден в манифестах ревизии.

### Сценарий 3: Change Failure Rate из событий

Правило [уведомлений](../gitops_notifications.md) отправляет каждый неудачный sync/rollback в Loki с метками приложения:

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  annotations:
    notifications.argoproj.io/subscribe.on-sync-failed.loki: ""
    notifications.argoproj.io/subscribe.on-sync-running.loki: ""
```

```logql
# CFR = failed / total за окно (скелет запроса)
sum(count_over_time({source="argocd", project="production", event="sync-failed"}[30d]))
/
sum(count_over_time({source="argocd", project="production", event="sync-running"}[30d]))
```

Дополните окном корреляции с алертами Degraded (Alertmanager → тот же Loki): деплой считается «неудачным», если за ним последовал алерт здоровья в течение N часов — так ловятся «успешные» синхронизации сломанного кода.

### Сценарий 4: Специализированные инструменты (обзорно)

- **Four Keys** (Google) — референсная архитектура: webhooks GitHub/GitLab + события деплоев → BigQuery → дашборды. Проект заархивирован, но схема «events → warehouse → SQL-метрики» остается полезным шаблоном.
- **Apache DevLake** — поддерживаемый open-source сборщик: коннекторы Git/GitLab/Jira + плагины для данных деплоя; подходит, когда хочется готовых дашбордов вместо самописных LogQL/PromQL.
- Самописный вариант на Grafana/Loki из сценариев 1–3 обычно достаточен для одного-двух десятков сервисов и не добавляет инфраструктуры.

## Типовые проблемы и их решение

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| DF аномально высокая | Считаются dev-среды и bot-коммиты | Фильтр по project/env; серия «bot-updates» отдельно |
| Lead time отрицательный/нулевой у части мержей | Fast-forward без merge-коммитов, cherry-picks | Считать по первому появлению deploy-SHA; включить merge-политику |
| CFR ≈ 0 при постоянных инцидентах | Инциденты не связаны с деплоями в данных | Корреляционное окно + привязка инцидент-тикетов к ревизиям |
| Метрики есть, решений нет | Цифры смотрят раз в квартал | Дашборд на командный ретро; алерт на тренды (CFR растет 2 недели подряд) |
| После перехода на rendered manifests пропала гранулярность | Ревизия = батч многих PR | Записывать список исходных SHA в аннотации артефакта при гидратации |
| Разные команды считают по-разному | Нет общего определения деплоя | Зафиксировать глоссарий (что такое деплой/фailure/окно) рядом с дашбордом |

## Дополнительная информация

- **Связь с практиками стека**: kill-switch'и снижают MTTR ([feature flags](./feature_flags_gitops.md)), verification-гейты Kargo дают честный CFR ([Kargo](./kargo_promotion_pipelines.md)), а экспорт событий решает проблему TTL событий Kubernetes ([аудит](./audit_logs.md)).
- **Метрики самих агентов**: полный список метрик Argo CD и Flux — в [диагностике и мониторинге](../ArgoCD/argocd_troubleshooting_and_monitoring.md).

### См. также

- [Диагностика и мониторинг Argo CD](../ArgoCD/argocd_troubleshooting_and_monitoring.md) — источники PromQL.
- [Уведомления в GitOps](../gitops_notifications.md) — доставка событий в Loki/webhook.
- [Журналы аудита](./audit_logs.md) — долгосрочное хранение событий для ретроспективных метрик.
