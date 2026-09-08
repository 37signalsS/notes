# Продвинутые стратегии отката Deployment

Практическое руководство по стратегиям отката в Kubernetes: от простого `rollout undo` до автоматического отката на основе метрик и GitOps-подхода.

## Предварительные требования (Prerequisites)

- Рабочий кластер Kubernetes (v1.16+).
- Установленный `kubectl` с доступом к кластеру.
- Базовое понимание [Deployment](./index.md), [Lifecycle Management](./lifecycle_management.md).

## 1. Определения

**Rollback (Откат)** — возврат приложения к предыдущей работоспособной версии после обнаружения проблем в новой версии. В Kubernetes откат — это не «перемотка времени», а создание новой ревизии с восстановленным шаблоном пода.

**Automated Rollback** — автоматический откат, инициируемый системой мониторинга или CI/CD при обнаружении проблем (ошибки, латентность, метрики бизнес-логики).

**Blast Radius Control** — управление областью поражения при откате: от полного отката (все реплики) до частичного (только порция трафика).

> Автоматический откат на основе метрик (Argo Rollouts, AnalysisTemplate) см. в [Progressive Delivery](./progressive_delivery.md). GitOps-based откат — в [Deployment с GitOps](./deployment_with_gitops.md).

## 2. Базовые концепции

### Уровни отката

| Уровень | Механизм | Скорость | Точность |
|:--------|:---------|:---------|:---------|
| **Ручной** | `kubectl rollout undo` | Мгновенно | По всей версии |
| **CI/CD автоматизация** | Pipeline + `rollout undo` | Секунды | По всей версии |
| **Метрики-based** | Prometheus + Argo Rollouts | Секунды-минуты | По Canary-долям |
| **GitOps-based** | `git revert` + sync | Минуты | По конфигурации |

### Когда нужен откат

| Ситуация | Типичная причина | Рекомендуемый уровень |
|:---------|:-----------------|:----------------------|
| **Полная недоступность** | Баг в коде, ошибка конфигурации | Ручной немедленный |
| **Частичные 5xx** | Регрессия в бизнес-логике | Автоматический по метрикам |
| **Увеличение latency** | Неоптимальный запрос к БД | Автоматический по метрикам |
| **Зависший rollout** | Ошибка в readinessProbe | Ручной с анализом |
| **Безопасность** | CVE в зависимостях | Немедленный ручной |

## 3. Практические сценарии

### Базовый откат через kubectl

```bash
# Откат к предыдущей ревизии (самый быстрый)
kubectl rollout undo deployment/my-app

# Проверка результата
kubectl rollout status deployment/my-app --timeout=5m

# Откат к конкретной ревизии
kubectl rollout history deployment/my-app
# → REVISION  CHANGE-CAUSE
# → 1         v1.0.0
# → 2         v1.1.0
# → 3         v1.2.0 (проблемная)

kubectl rollout undo deployment/my-app --to-revision=1

# Предварительный просмотр отката (ничего не меняет)
kubectl rollout undo deployment/my-app --dry-run=server -o yaml
```

### Откат в CI/CD pipeline

```yaml
# GitLab CI: автоматический откат при ошибке rollout
deploy:
  stage: deploy
  script:
    - kubectl set image deployment/my-app app=my-registry.com/app:$TAG
    - kubectl annotate deployment/my-app kubernetes.io/change-cause="$TAG" --overwrite
    - |
      if ! kubectl rollout status deployment/my-app --timeout=5m; then
        echo "ERROR: Rollout failed, initiating rollback"
        kubectl rollout undo deployment/my-app
        kubectl rollout status deployment/my-app --timeout=2m
        echo "Rollback completed"
        exit 1
      fi
    - echo "Rollout successful"
  after_script:
    - kubectl get pods -l app=my-app -o wide
  rules:
    - if: $CI_COMMIT_BRANCH == "main"
```

### GitOps-based откат

```bash
# 1. Откат через git revert (рекомендуемый способ)
git revert HEAD
git push origin main

# 2. ArgoCD/Flux автоматически синхронизирует предыдущее состояние

# 3. Или откат к конкретному коммиту
git log --oneline -5
# → abc1234 v1.2.0 (проблемная версия)
# → def5678 v1.1.0 (стабильная версия)

git revert abc1234
git push origin main

# 4. Или принудительная синхронизация к определенному коммиту
git checkout def5678 -- deployment/
git commit -m "rollback to v1.1.0"
git push origin main
```

> Детали GitOps rollback см. в [Deployment с GitOps](./deployment_with_gitops.md).

### Откат с уведомлениями

```bash
# Откат с аннотацией причины
kubectl annotate deployment/my-app \
  kubernetes.io/change-cause="ROLLBACK: откат с v1.2.0 на v1.1.0 из-за 5xx ошибок" \
  --overwrite

# Уведомление в Slack
kubectl rollout undo deployment/my-app && \
  curl -X POST -H 'Content-type: application/json' \
  --data '{"text":"Rollback: my-app откачен с v1.2.0 на v1.1.0"}' \
  $SLACK_WEBHOOK_URL
```

### Хранение и управление ревизиями

```bash
# Просмотр всех ревизий с деталями
kubectl rollout history deployment/my-app --revision=3

# Проверка лимита истории
kubectl get deployment my-app -o jsonpath='{.spec.revisionHistoryLimit}'
# → 10

# Установка лимита (рекомендуется 3-5 для prod)
kubectl patch deployment my-app -p '{"spec":{"revisionHistoryLimit":5}}'

# Экспорт манифеста конкретной ревизии
kubectl rollout undo deployment/my-app --to-revision=2 --dry-run=server -o yaml > rollback-v2.yaml
```

### Чеклист отката

| Шаг | Действие | Команда |
|:----|:---------|:--------|
| 1 | Определить проблему | `kubectl logs <pod> --previous` |
| 2 | Проверить метрики | Grafana/Prometheus dashboard |
| 3 | Решить: откатывать? | Анализ severity инцидента |
| 4 | Выполнить откат | `kubectl rollout undo deployment/my-app` |
| 5 | Дождаться завершения | `kubectl rollout status deployment/my-app --timeout=5m` |
| 6 | Проверить здоровье | `kubectl get pods -l app=my-app` |
| 7 | Проверить метрики | Error rate, latency должны вернуться к норме |
| 8 | Уведомить команду | Slack, email, ticket |
| 9 | Задокументировать | RCA, change-cause |
| 10 | Запланировать фикс | Создать тикет на исправление |

## 4. Дополнительная информация

### См. также
- [Lifecycle Management](./lifecycle_management.md) — rollout, rollback, пауза.
- [Troubleshooting](./troubleshooting.md) — диагностика при сбоях.
- [Progressive Delivery](./progressive_delivery.md) — Argo Rollouts, Flagger, AnalysisTemplate.
- [Deployment с GitOps](./deployment_with_gitops.md) — откат через Git (ArgoCD/Flux).
- [Incident Response](../../../CI-CD/GitLab_CI/Advanced/incident_response_cicd.md) — реагирование на инциденты.
