# Канареечное обновление Istio (Revision-based Canary Upgrade)

**Актуально для:** Istio 1.31.x

## Определения

**Revision-based Upgrade (обновление по ревизиям)** — стратегия обновления Istio, при которой новая версия Control Plane устанавливается параллельно со старой под отдельным именем (ревизией). Трафик постепенно переключается на новую ревизию, что позволяет обнаружить проблемы до полного переключения.

**Revision (ревизия)** — именованная версия Control Plane (istiod), управляемая через метку `istio.io/rev`. Каждая ревизия имеет собственный Deployment istiod, Service и MutatingWebhook Configuration для инъекции сайдкаров.

**Canary Control Plane** — новая версия istiod, развернутая параллельно со стабильной, для тестирования перед полным переключением.

**Traffic Shift (переключение трафика)** — поэтапное переключение подов со старой ревизии на новую через обновление метки `istio.io/rev` на namespace или deployment.

**Revision Tag** — стабильный идентификатор (alias), указывающий на конкретную ревизию (например, `prod-stable`, `prod-canary`). Namespace помечается тегом, а не версией ревизии напрямую. Переназначение тега на новую ревизию мигрирует все привязанные namespace одним действием, без переэтикетки.

**Default Tag** — специальный тег `default`, который: (1) инъектирует сайдкары для namespace с меткой `istio-injection=enabled`, `sidecar.istio.io/inject=true` и `istio.io/rev=default`; (2) валидирует ресурсы Istio; (3) захватывает лидер-лок для выполнения singleton-задач mesh.

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
│  istiod-1-30-1 (текущая версия)     │
│  → Обслуживает все поды в mesh      │
│  → Метка namespace: rev=1-30-1      │
└─────────────────────────────────────┘

Во время обновления:
┌────────────────────┐ ┌────────────────────┐
│  istiod-1-30-1     │ │  istiod-1-31-2     │
│  (стабильная)      │ │  (canary)          │
│  → 90% подов       │ │  → 10% подов       │
└────────────────────┘ └────────────────────┘

После обновления:
┌─────────────────────────────────────┐
│  istiod-1-31-2 (новая версия)       │
│  → Обслуживает все поды в mesh      │
│  → Метка namespace: rev=1-31-2      │
└─────────────────────────────────────┘
```

### Механизм привязки подов к ревизии

Поды привязываются к ревизии через метку:
- **Namespace-level:** `istio.io/rev: 1-31-2` на namespace — все поды в namespace используют эту ревизию (при автоматической инъекции).
- **Deployment-level:** `istio.io/rev: 1-31-2` на `template` пода deployment — только этот deployment использует ревизию.
- **Pod-level:** та же метка на поде (при ручной инъекции).

Важно: метка `istio-injection=enabled` имеет приоритет над `istio.io/rev` для обратной совместимости. При переключении на revision-based режим необходимо удалить `istio-injection=enabled` и установить `istio.io/rev`.

При изменении метки поды перезапускаются с sidecar'ом новой ревизии (через `kubectl rollout restart`).

### Revision Tags

Revision tags позволяют менять целевую ревизию для группы namespace без переэтикетки. Это рекомендуемый подход для production-сред, где canary-переключение выполняется часто.

**Преимущества revision tags:**
- Одной командой (`istioctl tag set`) переключаются все namespace с этим тегом.
- Нет риска опечаток при ручной переэтикетке.
- Canary и prod могут использовать разные теги, управляемые независимо.

| Команда | Описание |
| :--- | :--- |
| `istioctl tag set <tag> --revision <rev>` | Создаёт тег, указывающий на ревизию. |
| `istioctl tag set <tag> --revision <rev> --overwrite` | Переназначает существующий тег на новую ревизию. |
| `istioctl tag list` | Показывает соответствие тегов → ревизий и привязанные namespace. |
| `istioctl tag remove <tag>` | Удаляет тег. |
| `istioctl ps` | Показывает карту workload → istiod (какая ревизия обслуживает каждый pod). |

### Порядок операций

1. Проверить готовность кластера (`istioctl x precheck`).
2. Установить новую ревизию alongside старой.
3. Проверить работоспособность новой ревизии (`istioctl analyze`, `proxy-status`).
4. Настроить revision tag для canary (опционально, но рекомендуется для production).
5. Переключить один namespace на новую ревизию (canary).
6. Валидировать: метрики, логи, ошибки.
7. Переключить остальные namespace (через переназначение тега или метку).
8. Удалить старую ревизию и очистить теги.

---

## Требования и предусловия

**Предварительные требования:**
- Кластер Kubernetes 1.29+ (совместимость проверяется через `istioctl x precheck`).
- Текущая версия Istio, установленная через ревизии (revision-based installation), а не in-place.
- Доступ к `istioctl` версии, соответствующей целевой ревизии (или новее).
- Настроенный мониторинг (Prometheus + Grafana) для проверки golden signals после переключения.

**Подготовка кластера:**

```bash
# 1. Проверьте совместимость кластера перед обновлением
istioctl x precheck
# → No issues found when checking the cluster. Istio is safe to install or upgrade!

# 2. Проверьте текущую версию и ревизии
istioctl version
kubectl get pods -n istio-system -l app=istiod -o wide
```

> **Примечание:** переход через две minor-версии поддерживается (например, 1.30 → 1.31). При in-place upgrade промежуточные версии обязательны.

---

## Практические сценарии

### Сценарий 1: Установка новой ревизии alongside старой

```bash
# 0. Проверьте совместимость кластера перед обновлением
istioctl x precheck
# → No issues found when checking the cluster. Istio is safe to install or upgrade!

# 1. Проверьте текущую версию
istioctl version
# → client version: 1.30.1
# → control plane version: 1.30.1

# 2. Скачайте новую версию
curl -L https://istio.io/downloadIstio | ISTIO_VERSION=1.31.2 sh -
cd istio-1.31.2
export PATH=$PWD/bin:$PATH

# 3. Установите новую ревизию с именем, соответствующим версии
#    Точки в имени ревизии заменяются дефисами: 1.31.2 → 1-31-2
istioctl install --revision=1-31-2 \
  --set profile=default \
  --skip-confirmation

# 4. Проверьте, что обе ревизии работают
kubectl get pods -n istio-system -l app=istiod
# → NAME                             READY   STATUS    RESTARTS   AGE
# → istiod-1-30-1-abc123             1/1     Running   0          30d
# → istiod-1-31-2-def456             1/1     Running   0          5m

# 5. Проверьте, что webhook для новой ревизии создан
kubectl get mutatingwebhookconfigurations | grep istio
# → istio-sidecar-injector-1-30-1
# → istio-sidecar-injector-1-31-2
```

### Сценарий 2: Создание revision tags для управления Canary

Вместо ручной переэтикетки namespace используйте revision tags. Это позволяет переключить все namespace с одним тегом одной командой.

```bash
# 1. Создайте теги для стабильной и canary-ревизий
istioctl tag set prod-stable --revision 1-30-1
istioctl tag set prod-canary --revision 1-31-2

# 2. Переключите namespace на теги (а не на ревизию напрямую)
kubectl label namespace my-app istio-injection- istio.io/rev=prod-stable --overwrite
kubectl label namespace test-ns istio-injection- istio.io/rev=prod-canary --overwrite

# 3. Перезапустите поды для применения
kubectl rollout restart deployment -n my-app
kubectl rollout restart deployment -n test-ns

# 4. Проверьте сопоставление workload → istiod
istioctl ps
# → NAME                                CLUSTER   CDS        LDS        EDS        RDS        ECDS       ISTIOD                    VERSION
# → my-app-v1-abc123.my-app             K8s       SYNCED     SYNCED     SYNCED     SYNCED     NOT SENT   istiod-1-30-1-...          1.30.1
# → curl-78ff.test-ns                   K8s       SYNCED     SYNCED     SYNCED     SYNCED     NOT SENT   istiod-1-31-2-...          1.31.2

# 5. Просмотр соответствия тегов → ревизий
istioctl tag list
# → TAG         REVISION   NAMESPACES
# → prod-stable 1-30-1     my-app
# → prod-canary 1-31-2     test-ns
```

### Сценарий 3: Канареечное переключение namespace

```bash
# 1. Выберите тестовый namespace для canary
kubectl get ns my-app --show-labels
# → NAME    LABELS                     AGE
# → my-app  istio-injection=enabled   30d

# 2. Удалите метку istio-injection (она имеет приоритет над istio.io/rev)
#    и установите метку istio.io/rev на новую ревизию
kubectl label namespace my-app istio-injection- istio.io/rev=1-31-2 --overwrite
# → namespace/my-app labeled

# 3. Перезапустить поды для применения новой ревизии
kubectl rollout restart deployment -n my-app

# 4. Дождитесь перезапуска
kubectl rollout status deployment -n my-app

# 5. Проверьте, что поды используют новую ревизию
kubectl get pods -n my-app -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.metadata.annotations.istio\.io/rev}{"\n"}{end}'
# → my-app-v1-abc123    1-31-2
# → my-app-v2-def456    1-31-2

# 6. Проверьте статус синхронизации
istioctl proxy-status | grep my-app
# → my-app-v1-abc123.my-app.svc.cluster.local   SYNCED  SYNCED  SYNCED  SYNCED
# → my-app-v2-def456.my-app.svc.cluster.local   SYNCED  SYNCED  SYNCED  SYNCED
```

### Сценарий 4: Валидация после переключения

```bash
# 1. Анализ конфигурации на ошибки
istioctl analyze -n my-app
# → No validation issues found.

# 2. Проверка метрик (доля 5xx не должна увеличиваться)
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

### Сценарий 5: Откат на предыдущую ревизию

Если обнаружены проблемы на новой ревизии:

```bash
# 1. Переключите namespace обратно на старую ревизию
kubectl label namespace my-app istio.io/rev=1-30-1 --overwrite
# → namespace/my-app labeled

# 2. Перезапустить поды
kubectl rollout restart deployment -n my-app

# 3. Дождитесь перезапуска
kubectl rollout status deployment -n my-app

# 4. Проверьте, что поды вернулись на старую ревизию
kubectl get pods -n my-app -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.metadata.annotations.istio\.io/rev}{"\n"}{end}'
# → my-app-v1-abc123    1-30-1
# → my-app-v2-def456    1-30-1

# 5. Проверьте статус
istioctl proxy-status | grep my-app
# → my-app-v1-abc123.my-app.svc.cluster.local   SYNCED  SYNCED  SYNCED  SYNCED
```

### Сценарий 6: Массовое переключение через revision tags

После успешного canary на тестовом namespace переключите остальные namespace через переназначение тега:

```bash
# 1. Убедитесь, что все поды используют текущие ревизии
kubectl get pods --all-namespaces -o jsonpath='{range .items[*]}{.metadata.namespace}{"\t"}{.metadata.annotations.istio\.io/rev}{"\n"}{end}' | sort | uniq -c | sort -rn
# →    150 prod     1-30-1
# →     50 staging  1-30-1
# →     30 my-app   1-30-1
# →       0         1-31-2

# 2. Переназначьте prod-stable на новую ревизию (без переэтикетки namespace!)
istioctl tag set prod-stable --revision 1-31-2 --overwrite
# → Revision tag "prod-stable" updated to revision "1-31-2".

# 3. Перезапустите поды для применения новой ревизии
for ns in prod staging my-app; do
  kubectl rollout restart deployment -n $ns
done

# 4. Дождитесь перезапуска всех deployment'ов
for ns in prod staging my-app; do
  kubectl rollout status deployment -n $ns --timeout=300s
done

# 5. Проверьте общий статус — все поды должны быть SYNCED
istioctl proxy-status | grep -v SYNCED
# → (пусто — все поды синхронизированы)
```

### Сценарий 7: Удаление старой ревизии и cleanup

```bash
# 1. Убедитесь, что все поды используют новую ревизию
kubectl get pods --all-namespaces -o jsonpath='{range .items[*]}{.metadata.namespace}{"\t"}{.metadata.annotations.istio\.io/rev}{"\n"}{end}' | sort | uniq -c | sort -rn
# →    150 prod     1-31-2
# →     50 staging  1-31-2
# →     30 my-app   1-31-2
# →       0         1-30-1  ← старая ревизия не используется

# 2. Удалите старые revision tags
istioctl tag remove prod-stable
istioctl tag remove prod-canary

# 3. Удалите старую ревизию
istioctl uninstall --revision=1-30-1 -y

# 4. Проверьте, что старая ревизия удалена
kubectl get pods -n istio-system -l app=istiod
# → NAME                             READY   STATUS    RESTARTS   AGE
# → istiod-1-31-2-def456             1/1     Running   0          1h

# 5. Удалите webhook старой ревизии (автоматически при uninstall)
kubectl get mutatingwebhookconfigurations | grep istio
# → istio-sidecar-injector-1-31-2
```

### Сценарий 8: Обновление через Helm с revision и tags

```bash
# 1. Добавьте репозиторий Istio
helm repo add istio https://istio-release.storage.googleapis.com/charts
helm repo update

# 2. Установите новую ревизию через Helm
helm install istiod-1-31-2 istio/istiod -n istio-system \
  --set revision=1-31-2 \
  --set pilot.autoscaleEnabled=true \
  --set pilot.resources.requests.cpu=500m \
  --set pilot.resources.requests.memory=1Gi

# 3. Проверьте установку
kubectl get pods -n istio-system -l app=istiod
# → istiod-1-30-1-abc123   1/1     Running   0   30d
# → istiod-1-31-2-def456   1/1     Running   0   5m

# 4. Создайте revision tag для удобного переключения
istioctl tag set prod-stable --revision 1-31-2

# 5. Переключите namespace на тег
kubectl label namespace my-app istio-injection- istio.io/rev=prod-stable --overwrite
kubectl rollout restart deployment -n my-app
```

---

## Типичные ошибки и устранение неполадок

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| **Pod не перезапускается после смены rev** | Namespace имеет метку `istio-injection=enabled`, которая имеет приоритет над `istio.io/rev` | Удалите метку `istio-injection` (`kubectl label namespace ns istio-injection-`), затем установите `istio.io/rev`. |
| **Новая ревизия не видит поды старой** | MutatingWebhook для новой ревизии не создан | Проверьте `kubectl get mutatingwebhookconfigurations | grep istio`. Каждая ревизия должна иметь свой webhook `istio-sidecar-injector-<rev>`. |
| **mTLS не работает между ревизиями** | Сертификаты разных ревизий не доверяют друг другу | Убедитесь, что обе ревизии используют одинаковый `trustDomain` и trust bundle (Kubernetes Secret `cacerts` в `istio-system`). |
| **`istioctl analyze` показывает ошибки** | Конфликтующие ресурсы между ревизиями | Проверьте, что VirtualService/DestinationRule не привязаны к конкретной ревизии через labels. |
| **Старая ревизия не удаляется** | Поды все ещё используют старую ревизию | Проверьте `kubectl get pods --all-namespaces -o jsonpath='{.items[*].metadata.annotations.istio\.io/rev}'`. Убедитесь, что ни один pod не использует старую ревизию. |
| **Canary namespace возвращает 503** | Новая ревизия не успела синхронизироваться | Увеличьте timeout при rollout. Проверьте `istioctl proxy-status` — поды должны быть SYNCED. |
| **Revision tag не применяется** | Тег не назначен на ревизию или опечатка в имени | Проверьте `istioctl tag list`. Убедитесь, что namespace помечена на тег (`istio.io/rev=prod-stable`), а не на ревизию напрямую. |
| **Gateway не переключается на новую ревизию** | Ingress gateway не имеет revision-specific инстансов | Проверьте, что gateway использует ту же ревизию, что и istiod. Для revision-specific gateway используйте `--revision` при установке. |

---

## Лучшие практики эксплуатации

1. **Тестовый namespace first:** всегда начинайте canary с не-критичного namespace (test, dev). Переключайте prod только после валидации.
2. **Одна ревизия на namespace:** не смешивайте поды разных ревизий в одном namespace без необходимости. Это упрощает диагностику.
3. **Revision tags для production:** используйте `istioctl tag set` вместо ручной переэтикетки namespace. Это снижает риск ошибок и позволяет мигрировать все namespace одним действием.
4. **Мониторинг:** перед переключением настройте алерты на golden signals (errors, latency, RPS) для отслеживания регрессий.
5. **Откат за секунды:** при проблемах переключите `istio.io/rev` обратно и выполните `kubectl rollout restart`. Это не требует переустановки Istio.
6. **Удаление старых ревизий:** не оставляйте старые ревизии дольше необходимого. Они потребляют ресурсы и создают путаницу.
7. **Helm vs istioctl:** для production используйте Helm для управления ревизиями — это обеспечивает reproducibility и интеграцию с GitOps.
8. **Временные рамки:** установка новой ревизии занимает ~2-5 минут, переключение namespace — ~1-3 минуты (зависит от rollout strategy). Планируйте maintenance window.
9. **CRD-совместимость:** при обновлении с major-версии (например, 1.30 → 1.31) CRD обновляются автоматически. При откате CRD не откатываются — это может вызвать несовместимость.
10. **Валидация конфигурации:** перед переключением выполните `istioctl analyze -A` для проверки всех ресурсов mesh.
11. **Проверка перед обновлением:** всегда запускайте `istioctl x precheck` перед установкой новой ревизии — он проверяет совместимость кластера с целевой версией Istio.

---

## Дополнительная информация

### Сравнение стратегий обновления

| Стратегия | Время простоя | Риск | Сложность | Рекомендуется для |
| :--- | :--- | :--- | :--- | :--- |
| **In-place upgrade** (`istioctl upgrade`) | Минимальный (rolling restart) | Высокий (нет canary) | Низкая | Dev/test среды |
| **Revision-based** | Нулевой (параллельные CP) | Низкий (canary + откат) | Средняя | Production |
| **Multi-cluster** | Нулевой (кластер за кластером) | Минимальный | Высокая | Критичные системы |

### Автоматизация через GitOps

Для автоматизации revision-based upgrades в GitOps-пайплайнах используйте revision tags. Вместо переэтикетки каждого namespace, переназначайте тег через `istioctl tag set`:

```yaml
# ArgoCD Application для управления Istio ревизиями
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

```bash
# Шаг 1: Установить новую ревизию (через Helm/ArgoCD или вручную)
istioctl install --revision=1-31-2 --skip-confirmation

# Шаг 2: Переназначить prod-stable на новую ревизию
istioctl tag set prod-stable --revision 1-31-2 --overwrite

# Шаг 3: Перезапустить поды в namespace с тегом prod-stable
kubectl rollout restart deployment -n prod
kubectl rollout restart deployment -n staging
kubectl rollout restart deployment -n my-app

# Шаг 4: Проверить синхронизацию
istioctl proxy-status | grep -v SYNCED
# → (пусто — все поды синхронизированы)

# Шаг 5: Удалить старую ревизию
istioctl uninstall --revision=1-30-1 -y
```

### Canary upgrade для Gateway

При использовании revision-specific gateway (рекомендуется для production) canary-апгрейд gateway выполняется аналогично: устанавливаете новую ревизию gateway параллельно со старой, переключаете трафик через Service или Gateway API, затем удаляете старую. Подробности см. в [Istio Upgrade Guide](https://istio.io/latest/docs/setup/upgrade/canary/).

### Связанные темы

- [Установка и базовая настройка Istio](./istio_installation.md) — установка через istioctl/Helm
- [Архитектура Istio](./istio_architecture.md) — компоненты Control Plane
- [Наблюдаемость в Istio](./istio_observability_and_tools.md) — мониторинг после обновления
- [Мультикластерная архитектура Istio](./istio-multicluster.md) — канареечные апгрейды отдельных кластеров

Документация: [Istio Upgrade Guide](https://istio.io/latest/docs/setup/upgrade/), [Canary Upgrades](https://istio.io/latest/docs/setup/upgrade/canary/).
