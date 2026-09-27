# Канареечное обновление Istio (Revision-based Canary Upgrade)

## Определения

**Revision-based Upgrade (обновление по ревизиям)** — стратегия обновления Istio, при которой новая версия Control Plane устанавливается параллельно со старой под отдельным именем (ревизией). Трафик постепенно переключается на новую ревизию, что позволяет обнаружить проблемы до полного переключения.

**Revision (ревизия)** — именованная версия Control Plane (istiod), управляемая через аннотацию `istio.io/rev`. Каждая ревизия имеет собственный Deployment istiod и может обслуживать свою группу подов.

**Canary Control Plane** — новая версия istiod, развернутая параллельно со стабильной, для тестирования перед полным переключением.

**流量转移 (Traffic Shift)** — поэтапное переключение подов со старой ревизии на новую через обновление аннотации `istio.io/rev` на namespace или deployment.

---

## Основные концепции

### Зачем использовать revision-based upgrade

| Подход | Преимущества | Недостатки |
| :--- | :--- | :--- |
| **In-place upgrade** (`istioctl upgrade`) | Простота, один шаг | Нет отката без бэкапа, весь кластер обновляется сразу |
| **Revision-based upgrade** | Контролируемый rollout, откат за секунды, canary-тестирование | Сложнее в управлении, временно два Control Plane |

### Архитектура revision-based upgrade

```
До обновления:
┌─────────────────────────────────────┐
│  istiod-v1.31 (текущая версия)      │
│  → Обслуживает все поды в mesh      │
│  → Аннотация namespace: rev=v1.31   │
└─────────────────────────────────────┘

Во время обновления:
┌────────────────────┐ ┌────────────────────┐
│  istiod-v1.31      │ │  istiod-v1.32      │
│  (стабильная)      │ │  (canary)          │
│  → 90% подов       │ │  → 10% подов       │
└────────────────────┘ └────────────────────┘

После обновления:
┌─────────────────────────────────────┐
│  istiod-v1.32 (новая версия)        │
│  → Обслуживает все поды в mesh      │
│  → Аннотация namespace: rev=v1.32   │
└─────────────────────────────────────┘
```

### Механизм привязки подов к ревизии

Поды привязываются к ревизии через аннотацию:
- **Namespace-level:** `istio.io/rev: v1-32-0` на namespace — все поды в namespace используют эту ревизию.
- **Deployment-level:** `istio.io/rev: v1-32-0` на template пода deployment — только этот deployment использует ревизию.
- **Pod-level:** та же аннотация на поде (при ручной инъекции).

При изменении аннотации поды перезапускаются с sidecar'ом новой ревизии (через `kubectl rollout restart`).

### Порядок операций

1. Установить новую ревизию alongside старой.
2. Проверить работоспособность новой ревизии (istioctl analyze, proxy-status).
3. Переключить один namespace на новую ревизию (canary).
4. Валидировать: метрики, логи, ошибки.
5. Переключить остальные namespace.
6. Удалить старую ревизию.

---

## Практические сценарии

### Сценарий 1: Установка новой ревизии alongside старой

```bash
# 1. Проверьте текущую версию
istioctl version
# → client version: 1.31.0
# → control plane version: 1.31.0

# 2. Скачайте новую версию
curl -L https://istio.io/downloadIstio | ISTIO_VERSION=1.32.0 sh -
cd istio-1.32.0
export PATH=$PWD/bin:$PATH

# 3. Установите новую ревизию с уникальным именем
istioctl install --set profile=default \
  --set revision=v1-32-0 \
  -y

# 4. Проверьте, что обе ревизии работают
kubectl get pods -n istio-system -l app=istiod
# → NAME                             READY   STATUS    RESTARTS   AGE
# → istiod-v1-31-0-abc123            1/1     Running   0          30d
# → istiod-v1-32-0-def456            1/1     Running   0          5m

# 5. Проверьте, что webhook для новой ревизии создан
kubectl get mutatingwebhookconfigurations | grep istio
# → istio-sidecar-injector-v1-31-0
# → istio-sidecar-injector-v1-32-0
```

### Сценарий 2: Канареечное переключение namespace

```bash
# 1. Выберите тестовый namespace для canary
kubectl get ns my-app --show-labels
# → NAME    LABELS                     AGE
# → my-app  istio-injection=enabled   30d

# 2. Переключите namespace на новую ревизию
kubectl label namespace my-app istio.io/rev=v1-32-0 --overwrite
# → namespace/my-app labeled

# 3. Перезапустить поды для применения новой ревизии
kubectl rollout restart deployment -n my-app

# 4. Дождитесь перезапуска
kubectl rollout status deployment -n my-app

# 5. Проверьте, что поды используют новую ревизию
kubectl get pods -n my-app -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.metadata.annotations.istio\.io/rev}{"\n"}{end}'
# → my-app-v1-abc123    v1-32-0
# → my-app-v2-def456    v1-32-0

# 6. Проверьте статус синхронизации
istioctl proxy-status | grep my-app
# → my-app-v1-abc123.my-app.svc.cluster.local   SYNCED  SYNCED  SYNCED  SYNCED
# → my-app-v2-def456.my-app.svc.cluster.local   SYNCED  SYNCED  SYNCED  SYNCED
```

### Сценарий 3: Валидация после переключения

```bash
# 1. Анализ конфигурации на ошибки
istioctl analyze -n my-app
# → No validation issues found.

# 2. Проверка метрик (ошибки不应 увеличиться)
kubectl exec -n monitoring prometheus-0 -- wget -qO- 'http://localhost:9090/api/v1/query?query=sum(rate(istio_requests_total{response_code=~"5..",destination_workload_namespace="my-app"}[5m]))'
# → {"status":"success","data":{"resultType":"vector","result":[{"value":[1695379200,"0.001"]}]}}
# → Доля 5xx < 1% — норма

# 3. Проверка access-логов на ошибки
kubectl logs -l app=my-app -c istio-proxy -n my-app --tail=100 | grep -E "502|503|504"
# → (пусто или единичные ошибки — норма)

# 4. Проверка сертификатов новой ревизии
istioctl proxy-config secret deploy/my-app-v1 -n my-app -o json | jq '.dynamicActiveSecrets[0].secret.tlsCertificate.certificateChain.inlineBytes' | base64 -d | openssl x509 -noout -subject -issuer
# → subject: CN=spiffe://cluster.local/ns/my-app/sa/my-app
# → issuer: CN=spiffe://cluster.local/ns/istio-system/sa/istiod-service-account
```

### Сценарий 4: Откат на предыдущую ревизию

Если обнаружены проблемы на новой ревизии:

```bash
# 1. Переключите namespace обратно на старую ревизию
kubectl label namespace my-app istio.io/rev=v1-31-0 --overwrite
# → namespace/my-app labeled

# 2. Перезапустить поды
kubectl rollout restart deployment -n my-app

# 3. Дождитесь перезапуска
kubectl rollout status deployment -n my-app

# 4. Проверьте, что поды вернулись на старую ревизию
kubectl get pods -n my-app -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.metadata.annotations.istio\.io/rev}{"\n"}{end}'
# → my-app-v1-abc123    v1-31-0
# → my-app-v2-def456    v1-31-0

# 5. Проверьте статус
istioctl proxy-status | grep my-app
# → my-app-v1-abc123.my-app.svc.cluster.local   SYNCED  SYNCED  SYNCED  SYNCED
```

### Сценарий 5: Массовое переключение всех namespace

После успешного canary на тестовом namespace:

```bash
# 1. Получите список namespace с текущей ревизией
kubectl get ns -l istio-injection=enabled -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.metadata.labels.istio\.io/rev}{"\n"}{end}'
# → my-app    v1-31-0
# → prod      v1-31-0
# → staging   v1-31-0

# 2. Переключите все namespace на новую ревизию
for ns in prod staging my-app; do
  kubectl label namespace $ns istio.io/rev=v1-32-0 --overwrite
  kubectl rollout restart deployment -n $ns
done

# 3. Дождитесь перезапуска всех deployment'ов
for ns in prod staging my-app; do
  kubectl rollout status deployment -n $ns --timeout=300s
done

# 4. Проверьте общий статус
istioctl proxy-status | grep -v SYNCED
# → (пусто — все поды синхронизированы)
```

### Сценарий 6: Удаление старой ревизии

```bash
# 1. Убедитесь, что все поды используют новую ревизию
kubectl get pods --all-namespaces -o jsonpath='{range .items[*]}{.metadata.namespace}{"\t"}{.metadata.annotations.istio\.io/rev}{"\n"}{end}' | sort | uniq -c | sort -rn
# →    150 prod    v1-32-0
# →     50 staging v1-32-0
# →     30 my-app  v1-32-0
# →       0         v1-31-0  ← старая ревизия не используется

# 2. Удалите старую ревизию
istioctl uninstall --revision=v1-31-0 -y

# 3. Проверьте, что старая ревизия удалена
kubectl get pods -n istio-system -l app=istiod
# → NAME                             READY   STATUS    RESTARTS   AGE
# → istiod-v1-32-0-def456            1/1     Running   0          1h

# 4. Удалите webhook старой ревизии (автоматически при uninstall)
kubectl get mutatingwebhookconfigurations | grep istio
# → istio-sidecar-injector-v1-32-0
```

### Сценарий 7: Обновление через Helm с revision

```bash
# 1. Добавьте репозиторий Istio
helm repo add istio https://istio-release.storage.googleapis.com/charts
helm repo update

# 2. Установите новую ревизию через Helm
helm install istiod-v1-32-0 istio/istiod -n istio-system \
  --set revision=v1-32-0 \
  --set pilot.autoscaleEnabled=true \
  --set pilot.resources.requests.cpu=500m \
  --set pilot.resources.requests.memory=1Gi

# 3. Проверьте установку
kubectl get pods -n istio-system -l app=istiod
# → istiod-v1-31-0-abc123   1/1     Running   0   30d
# → istiod-v1-32-0-def456   1/1     Running   0   5m

# 4. Обновите namespace
kubectl label namespace my-app istio.io/rev=v1-32-0 --overwrite
kubectl rollout restart deployment -n my-app
```

---

## Типичные ошибки и устранение неполадок

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| **Pod не перезапускается после смены rev** | Deployment не имеет аннотации `istio.io/rev` | Добавьте аннотацию на template пода deployment или используйте `kubectl rollout restart`. |
| **Новая ревизия не видит поды старой** | Webhook не настроен для обеих ревизий | Проверьте `kubectl get mutatingwebhookconfigurations`. Обе ревизии должны иметь свои webhook'и. |
| **mTLS не работает между ревизиями** | Сертификаты разных ревизий не доверяют друг другу | Убедитесь, что обе ревизии используют одинаковый trustDomain и trust bundle. |
| **`istioctl analyze` показывает ошибки** | Конфликтующие ресурсы между ревизиями | Проверьте, что VirtualService/DestinationRule не привязаны к конкретной ревизии через labels. |
| **Старая ревизия не удаляется** | Поды все еще используют старую ревизию | Проверьте `kubectl get pods -o jsonpath='{.items[*].metadata.annotations.istio\.io/rev}'`. Убедитесь, что ни один pod не использует старую ревизию. |
| **Canary namespace возвращает 503** | Новая ревизия не успела синхронизироваться | Увеличьте timeout при rollout. Проверьте `istioctl proxy-status` — поды должны быть SYNCED. |

---

## Лучшие практики эксплуатации

1. **Тестовый namespace first:** всегда начинайте canary с не-критичного namespace (test, dev). Переключайте prod только после валидации.
2. **Одна ревизия на namespace:** не смешивайте поды разных ревизий в одном namespace без необходимости. Это упрощает диагностику.
3. **Мониторинг:** перед переключением настройте алерты на golden signals (errors, latency, RPS) для отслеживания регрессий.
4. **Откат за секунды:** при проблемах переключите `istio.io/rev` обратно и выполните `kubectl rollout restart`. Это не требует переустановки Istio.
5. **Удаление старых ревизий:** не оставляйте старые ревизии дольше необходимого. Они потребляют ресурсы и создают путаницу.
6. **Helm vs istioctl:** для production используйте Helm для управления ревизиями — это обеспечивает reproducibility и интеграцию с GitOps.
7. **Временные рамки:** установка новой ревизии занимает ~2-5 минут, переключение namespace — ~1-3 минуты (dependent от rollout strategy). Планируйте maintenance window.
8. **CRD-совместимость:** при обновлении с major-версии (например, 1.31 → 1.32) CRD обновляются автоматически. При откате CRD не откатываются — это может вызвать несовместимость.
9. **Валидация конфигурации:** перед переключением выполните `istioctl analyze -A` для проверки всех ресурсов mesh.

---

## Дополнительная информация

### Сравнение стратегий обновления

| Стратегия | Время простоя | Риск | Сложность | Рекомендуется для |
| :--- | :--- | :--- | :--- | :--- |
| **In-place upgrade** | Минимальный (rolling restart) | Высокий (нет canary) | Низкая | Dev/test среды |
| **Revision-based** | Нулевой (параллельные CP) | Низкий (canary + откат) | Средняя | Production |
| **Multi-cluster** | Нулевой (кластер за кластером) | Минимальный | Высокая | Критичные системы |

### Автоматизация через GitOps

Для автоматизации revision-based upgrades в GitOps-пайплайнах:

```yaml
# ArgoCD Application для управления ревизиями Istio
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: istio-revision
  namespace: argocd
spec:
  project: default
  source:
    repoURL: https://github.com/org/istio-config.git
    targetRevision: HEAD
    path: overlays/prod/istio-revision
  destination:
    server: https://kubernetes.default.svc
    namespace: istio-system
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
```

### Связанные темы

- [Установка и базовая настройка Istio](./istio_installation.md) — установка через istioctl/Helm
- [Архитектура Istio](./istio_architecture.md) — компоненты Control Plane
- [Наблюдаемость в Istio](./istio_observability_and_tools.md) — мониторинг после обновления

Документация: [Istio Upgrade Guide](https://istio.io/latest/docs/setup/upgrade/), [Revision-based Upgrades](https://istio.io/latest/docs/setup/upgrade/canary/).
