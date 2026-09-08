# NetworkPolicy: Откат и управление инцидентами

## Определения

**Rollback (Откат)** — процесс возврата NetworkPolicy к предыдущему рабочему состоянию после обнаружения проблем. В Kubernetes реализуется через `kubectl apply -f <previous-manifest>` или `git revert` в GitOps-пайплайне.

**Incident Response (Реагирование на инцидент)** — процесс быстрой локализации и устранения последствий неправильной конфигурации NetworkPolicy, которая привела к нарушению доступности сервисов.

**Blast Radius (Радиус поражения)** — масштаб нарушений, вызванных неправильной NetworkPolicy. Определяется количеством затронутых сервисов, подов и пользователей.

**Change Management (Управление изменениями)** — процесс предложения, рассмотрения, тестирования и применения изменений NetworkPolicy в production.

## Базовые Концепции

### Причины необходимости отката

| Причина | Симптом | Срочность |
| :--- | :--- | :--- |
| Политика блокирует критический сервис | Connection timeout к API/БД | SEV-1 |
| DNS заблокирован для группы подов | `nslookup` fails | SEV-1 |
| Массовая блокировка трафика | >10% подов недоступны | SEV-1 |
| Медленные соединения | Timeout 1-5сек, conntrack race | SEV-2 |
| Частичная блокировка | Недоступны некоторые эндпоинты | SEV-2 |

### Процесс отката

```
1. Обнаружение проблемы (Alert/User report)
   └─ Определение SEV-уровня
2. Сбор доказательств (Before changes)
   └─ kubectl get networkpolicy -A -o yaml > backup.yaml
3. Быстрый откат
   └─ kubectl delete networkpolicy <problematic-policy>
   ИЛИ
   └─ kubectl apply -f previous-version.yaml
4. Верификация
   └─ Тест связности из подов
5. Анализ причины (Root Cause)
   └─ Почему политика была неправильной?
6. Исправление и повторное применение
   └─ После тестирования в staging
```

## Практические сценарии

### Сценарий 1: Экстренный откат через kubectl

Политика `deny-all-production` заблокировала все сервисы в namespace:

```bash
# Шаг 1: Сбор доказательств
kubectl get networkpolicy -n production -o yaml > /tmp/backup-$(date +%Y%m%d-%H%M%S).yaml

# Шаг 2: Быстрое удаление проблемной политики
kubectl delete networkpolicy deny-all-production -n production

# Шаг 3: Верификация восстановления
kubectl run debug --image=busybox --rm -it -n production -- \
  wget -qO- --timeout=5 http://api-server.production.svc.cluster.local
# → OK (response received)

# Шаг 4: Проверка всех сервисов
for svc in api-server frontend database; do
  kubectl exec -n production debug-pod -- curl -s --timeout=3 http://$svc.production.svc.cluster.local/health
done
```

### Сценарий 2: GitOps откат через ArgoCD

```bash
# Шаг 1: Поиск коммита с проблемной политикой
git log --oneline -- kubernetes/networkpolicy/production/
# → a1b2c3d Add deny-all policy (PROBLEMATIC)
# → e4f5g6h Allow DNS for production
# → i7j8k9l Initial network policies

# Шаг 2: Откат к предыдущему коммиту
git revert a1b2c3d --no-edit

# Шаг 3: Пуш изменений
git push origin main

# Шаг 4: ArgoCD автоматически синхронизирует
# Мониторинг статуса синхронизации
argocd app get network-policies-production
# → Status: Synced
# → Health: Healthy
```

### Сценарий 3: Карантин пода через NetworkPolicy

Изоляция скомпрометированного пода с сохранением доступа для forensic:

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: quarantine-compromised-pod
  namespace: production
  labels:
    purpose: security-incident
    incident-id: "INC-2026-001"
spec:
  podSelector:
    matchLabels:
      security-incident: "INC-2026-001"
  policyTypes:
  - Ingress
  - Egress
  ingress: []  # Полная блокировка входящего
  egress:
  # Разрешить доступ только к forensic-серверу
  - to:
    - podSelector:
        matchLabels:
          app: forensic-collector
    ports:
    - protocol: TCP
      port: 22
  # DNS (для анализа)
  - to:
    - namespaceSelector:
        matchLabels:
          kubernetes.io/metadata.name: kube-system
      podSelector:
        matchLabels:
          k8s-app: kube-dns
    ports:
    - protocol: UDP
      port: 53
```

```bash
# Применение карантинной политики
kubectl label pod compromised-pod-abc security-incident=INC-2026-001 -n production
kubectl apply -f quarantine-policy.yaml

# Проверка изоляции
kubectl exec -n production legitimate-pod -- curl -s --timeout=3 http://compromised-pod.production.svc
# → Connection timed out

# Сбор данных с compromised pod
kubectl exec -n production compromised-pod-abc -- cat /tmp/malicious_script.sh
```

### Сценарий 4: Поэтапное изменение политик

Безопасное обновление NetworkPolicy без downtime:

```bash
# Этап 1: Создание резервной копии
kubectl get networkpolicy -n production -o yaml > backup.yaml

# Этап 2: Применение в staging
kubectl apply -f new-policy.yaml -n staging
kubectl exec -n staging debug-pod -- curl -v --timeout=5 http://api-server.staging.svc
# → Проверка что все работает

# Этап 3: Применение в canary (1 узел)
kubectl label node worker-1 env=canary
kubectl apply -f new-policy.yaml -n production
# Мониторинг 15 минут

# Этап 4: Полное применение
kubectl apply -f new-policy.yaml -n production
# Мониторинг 30 минут

# Этап 5: Очистка
kubectl label node worker-1 env-
```

## Дополнительная информация

### Runbook: Быстрый откат NetworkPolicy

```bash
#!/bin/bash
# quick-rollback.sh — быстрый откат NetworkPolicy
NAMESPACE=${1:-production}
BACKUP_DIR="/tmp/netpol-backup/$(date +%Y%m%d-%H%M%S)"

# 1. Бэкап текущего состояния
mkdir -p $BACKUP_DIR
kubectl get networkpolicy -n $NAMESPACE -o yaml > $BACKUP_DIR/current.yaml

# 2. Удаление всех политик (если нужен полный откат)
kubectl delete networkpolicy --all -n $NAMESPACE

# 3. Проверка связности
echo "Testing connectivity..."
kubectl run test --image=busybox --rm -it -n $NAMESPACE -- \
  wget -qO- --timeout=5 http://kubernetes.default.svc.cluster.local

# 4. Вывод бэкапа
echo "Backup saved to: $BACKUP_DIR/current.yaml"
echo "To restore: kubectl apply -f $BACKUP_DIR/current.yaml"
```

### Критерии ESCALATION

| Уровень | Действие | Время |
| :--- | :--- | :--- |
| **SEV-1** | Удалить проблемную политику немедленно | 0-5 мин |
| **SEV-2** | Откатить к предыдущей версии | 5-15 мин |
| **SEV-3** | Исправить политику и повторить | 15-60 мин |
| **SEV-4** | Запланировать исправление | Вне SLA |

### Правила Change Management для NetworkPolicy

1. **Все изменения через PR** с code review минимум от 2 человек
2. **Валидация в CI** (conftest, kubeconform) перед merge
3. **Dry-run в staging** перед production
4. **Поэтапное применение** (canary → full)
5. **Мониторинг 30 минут** после каждого изменения
6. **Бэкап перед изменением** (kubectl get networkpolicy -A -o yaml)

### См. также

* [NetworkPolicy: Лучшие практики](./best_practices.md) — рекомендации по управлению
* [NetworkPolicy: CI/CD и GitOps](./gitops_ci_cd.md) — автоматизация
* [Реагирование на инциденты](../../../Security/incident_response.md) — общий процесс
