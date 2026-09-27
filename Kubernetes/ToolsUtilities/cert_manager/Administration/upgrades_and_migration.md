# Обновление и миграция cert-manager

## Определения

**Upgrades cert-manager** — процесс обновления версий контроллера, CRD и Helm-чарта в Production-среде. Требует осторожности из-за тесной интеграции с Kubernetes API: некорректное обновление может заблокировать создание любых ресурсов в кластере (webhook failure).

**Breaking Change** — изменение в новой версии, несовместимое с предыдущей. В cert-manager的主要 источники breaking changes: удаление API-versions (v1beta1 → v1), изменение CRD-схем и изменение RBAC-политик Helm-чарта.

**CRD Migration** — обновление Custom Resource Definitions при апгрейде. CRD содержат OpenAPI-схемы, определяющие допустимые поля ресурсов. Если CRD не обновлены до версии Helm-чарта, контроллер может не распознавать новые поля или отклонять валидные манифесты.

**Canary Upgrade** — стратегия обновления, при которой сначала обновляется одна реплика контроллера для проверки совместимости, а затем — остальные. Минимизирует的影响 при обнаружении проблем.

---

## Основные концепции

### Порядок компонентов при обновлении

При обновлении cert-manager критически важен порядок применения манифестов:

1. **CRD** — обновляются ПЕРВЫМИ (новые схемы должны быть в кластере до контроллера)
2. **Webhook** — обновляется ВТОРЫМ (валидирует новые CRD)
3. **Controller** — обновляется ТРЕТЬИМ (начинает использовать новые CRD)
4. **CA Injector** — обновляется ЧЕТВЕРТЫМ

> **Ошибка:** Если обновить контроллер ДО CRD, он будет пытаться работать с неизвестными полями и падать с `OOMKilled` или `CrashLoopBackOff`.

### Риски при обновлении

| Риск | Вероятность | Влияние | Митигация |
| :--- | :--- | :--- | :--- |
| **Webhook timeout** | Средняя | Блокировка API-сервера | HA webhook (3 реплики), `failurePolicy: Fail` |
| **CRD schema mismatch** | Низкая | Ошибки валидации ресурсов | Обновлять CRD первыми |
| **API deprecation** | Средняя | Ошибки `method not supported` | Мигрировать все ресурсы на v1 заранее |
| **Leader election failure** | Низкая | Контроллер не обрабатывает события | Проверить `--leader-election-namespace` |
| **RBAC changes** | Средняя | `Forbidden` ошибки | Проверить changelog версии |

### Версионная совместимость

| Версия cert-manager | Мин. Kubernetes | CRD API | Статус |
| :--- | :--- | :--- | :--- |
| **1.21.x** | 1.25+ | `cert-manager.io/v1` | Текущая稳定ная |
| 1.20.x | 1.25+ | `cert-manager.io/v1` | Поддерживается |
| 1.19.x | 1.24+ | `cert-manager.io/v1` | EOL (не получает исправлений) |
| 1.18.x | <1.24 | `v1beta1` + `v1` | Устарела |

### Типичные Breaking Changes по версиям

| Переход | Изменение | Действие |
| :--- | :--- | :--- |
| **1.18 → 1.19** | Удалены некоторые `v1beta1` API | Мигрировать все ресурсы на `cert-manager.io/v1` |
| **1.19 → 1.20** | Изменения в webhook timeout | Проверить `webhook.timeoutSeconds` |
| **1.20 → 1.21** | Удалены права на создание ServiceAccount токенов из Helm-чарта | Добавить `serviceaccounts/token: create` в ClusterRole при использовании IRSA/GCP WI |
| **1.21+** | Включение ARI по умолчанию | Удалить `renewBefore` из Certificate, если используется ARI |

---

## Практические сценарии

### Сценарий 1: Мажорное обновление (1.19 → 1.21)

#### Шаг 1: Предварительная подготовка

```bash
# 1. Проверка текущей версии
helm list -n cert-manager
# → NAME          REVISION  STATUS   CHART            APP VERSION
# → cert-manager  3         deployed cert-manager-1.19.0  v1.19.0

# 2. Проверка версий CRD
kubectl get crd certificates.cert-manager.io -o jsonpath='{.spec.versions[*].name}'
# → v1

# 3. Поиск ресурсов на устаревших API
kubectl get issuers,clusterissuers,certificates -A -o yaml | grep "apiVersion:" | sort | uniq -c
# → Должны быть только cert-manager.io/v1

# 4. Бэкап ВСЕХ ресурсов
kubectl get issuers,clusterissuers,certificates,certificaterequests,orders,challenges -A -o yaml > cert-manager-full-backup.yaml
kubectl get secret -n cert-manager -o yaml > cert-manager-secrets-backup.yaml
kubectl get bundles -A -o yaml > trust-manager-backup.yaml

# 5. Проверка статуса всех сертификатов
cmctl status certificate -A
# → Все должны быть Ready: True

# 6. Проверка доступности webhook
cmctl check api
# → All checks passed
```

#### Шаг 2: Обновление CRD

```bash
# Обновление CRD ДО Helm-чарта (критический порядок!)
kubectl apply -f https://github.com/cert-manager/cert-manager/releases/download/v1.21.0/cert-manager.crds.yaml

# Верификация CRD
kubectl get crd | grep cert-manager
kubectl get crd certificates.cert-manager.io -o jsonpath='{.spec.versions[*].name}'
# → v1
```

#### Шаг 3: Обновление Helm-чарта

```bash
# Обновление с сохранением текущих значений
helm upgrade cert-manager jetstack/cert-manager \
  --namespace cert-manager \
  --version v1.21.0 \
  --reuse-values \
  --wait \
  --timeout 5m

# Проверка подов
kubectl get pods -n cert-manager
# → Все поды должны быть Running и Ready (1/1)

# Проверка webhook
cmctl check api --wait=2m
# → All checks passed
```

#### Шаг 4: Пост-обновление

```bash
# 1. Проверка логов контроллера на ошибки
kubectl logs -n cert-manager -l app.kubernetes.io/component=controller --tail=50 | grep -i error

# 2. Проверка статуса всех сертификатов
cmctl status certificate -A

# 3. Тестовый выпуск self-signed сертификата
kubectl apply -f - <<EOF
apiVersion: cert-manager.io/v1
kind: Issuer
metadata:
  name: test-upgrade
  namespace: default
spec:
  selfSigned: {}
---
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: test-upgrade-cert
  namespace: default
spec:
  secretName: test-upgrade-secret
  dnsNames: ["test.example.com"]
  issuerRef:
    name: test-upgrade
    kind: Issuer
EOF

# 4. Ожидание выпуска
cmctl status certificate test-upgrade-cert -n default
# → Ready: True

# 5. Очистка тестовых ресурсов
kubectl delete issuer test-upgrade -n default
kubectl delete certificate test-upgrade-cert -n default
```

### Сценарий 2: Rollback при проблемах

```bash
# 1. Просмотр истории релизов
helm history cert-manager -n cert-manager
# → REVISION  STATUS     DESCRIPTION
# → 1         superseded Previous release
# → 2         superseded Previous release
# → 3         deployed   Current release (broken)

# 2. Откат на предыдущую ревизию
helm rollback cert-manager 2 -n cert-manager --wait --timeout 5m

# 3. Если CRD были обновлены — откат CRD вручную
# Найти версию старых CRD в GitHub releases
kubectl apply -f https://github.com/cert-manager/cert-manager/releases/download/v1.20.0/cert-manager.crds.yaml

# 4. Проверка после отката
cmctl check api --wait=2m
kubectl get certificate -A | grep False
# → Не должно быть False

# 5. Проверка логов
kubectl logs -n cert-manager -l app.kubernetes.io/component=controller --tail=50
```

### Сценарий 3: Миграция API-версий (v1beta1 → v1)

```bash
# 1. Поиск ресурсов на устаревшем API
kubectl get issuers,clusterissuers,certificates -A -o json | \
  jq -r '.items[] | select(.apiVersion != "cert-manager.io/v1") | "\(.apiVersion) \(.kind) \(.metadata.namespace)/\(.metadata.name)"'

# 2. Экспорт и конвертация каждого ресурса
# Пример для Issuer:
kubectl get issuer my-issuer -n my-namespace -o yaml | \
  sed 's|apiVersion: cert-manager.io/v1beta1|apiVersion: cert-manager.io/v1|' | \
  kubectl apply -f -

# 3. Массовая миграция всех ресурсов
for kind in issuer clusterissuer certificate; do
  kubectl get $kind -A -o json | \
    jq -r ".items[] | select(.apiVersion != \"cert-manager.io/v1\") | .metadata.name" | \
    while read name; do
      ns_flag=""
      if [ "$kind" != "clusterissuer" ]; then
        ns_flag="-n $(kubectl get $kind $name -A -o jsonpath='{.metadata.namespace}')"
      fi
      kubectl get $kind $name $ns_flag -o yaml | \
        sed 's|apiVersion: cert-manager.io/v1beta1|apiVersion: cert-manager.io/v1|' | \
        kubectl apply -f -
      echo "Migrated: $kind/$name"
    done
done

# 4. Проверка — не должно остаться ресурсов на v1beta1
kubectl get issuers,clusterissuers,certificates -A -o yaml | grep "v1beta1"
# → Не должно быть вывода
```

### Сценарий 4: Обновление в HA-среде (пошагово)

В кластерах с 3+ репликами webhook обновление должно быть постепенным:

```bash
# 1. Снижение количества реплик webhook до 1
helm upgrade cert-manager jetstack/cert-manager \
  --namespace cert-manager \
  --reuse-values \
  --set webhook.replicaCount=1 \
  --wait --timeout 3m

# 2. Обновление CRD
kubectl apply -f https://github.com/cert-manager/cert-manager/releases/download/v1.21.0/cert-manager.crds.yaml

# 3. Обновление Helm-чарта
helm upgrade cert-manager jetstack/cert-manager \
  --namespace cert-manager \
  --version v1.21.0 \
  --reuse-values \
  --wait --timeout 5m

# 4. Восстановление HA-реплик
helm upgrade cert-manager jetstack/cert-manager \
  --namespace cert-manager \
  --reuse-values \
  --set webhook.replicaCount=3 \
  --wait --timeout 3m

# 5. Верификация
cmctl check api --wait=2m
kubectl get pods -n cert-manager
```

### Сценарий 5: Обновление с изменением RBAC (1.20 → 1.21)

Начиная с v1.21, Helm-чарт не включает права на создание ServiceAccount токенов. Если cert-manager интегрирован с AWS IRSA или GCP Workload Identity:

```bash
# 1. До обновления — проверить, используется ли IRSA/WI
kubectl get clusterrole cert-manager -o yaml | grep "serviceaccounts/token"
# → Если есть — эти права будут удалены при обновлении

# 2. Создать дополнительный ClusterRole
kubectl apply -f - <<EOF
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: cert-manager-extra
rules:
- apiGroups: [""]
  resources: ["serviceaccounts/token"]
  verbs: ["create"]
EOF

# 3. Привязать к ServiceAccount cert-manager
kubectl apply -f - <<EOF
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: cert-manager-extra-binding
subjects:
- kind: ServiceAccount
  name: cert-manager
  namespace: cert-manager
roleRef:
  kind: ClusterRole
  name: cert-manager-extra
  apiGroup: rbac.authorization.k8s.io
EOF

# 4. Обновить cert-manager
helm upgrade cert-manager jetstack/cert-manager \
  --namespace cert-manager \
  --version v1.21.0 \
  --reuse-values \
  --wait --timeout 5m
```

---

## Дополнительная информация

### Чеклист перед обновлением

- [ ] Проверить текущую версию: `helm list -n cert-manager`
- [ ] Проверить версию CRD: `kubectl get crd certificates.cert-manager.io -o jsonpath='{.spec.versions[*].name}'`
- [ ] Проверить совместимость API: `kubectl get issuers,clusterissuers,certificates -A -o yaml | grep apiVersion`
- [ ] Сделать бэкап CA-секретов: `kubectl get secret -n cert-manager -o yaml > backup.yaml`
- [ ] Сделать бэкап всех ресурсов: `kubectl get issuers,clusterissuers,certificates -A -o yaml > resources.yaml`
- [ ] Проверить статус всех сертификатов: `cmctl status certificate -A`
- [ ] Убедиться, что webhook доступен: `cmctl check api`
- [ ] Прочитать release notes целевой версии
- [ ] Проверить наличие breaking changes

### Чеклист после обновления

- [ ] Проверить статус всех сертификатов: `cmctl status certificate -A`
- [ ] Проверить логи контроллера: `kubectl logs -n cert-manager -l app.kubernetes.io/component=controller --tail=50`
- [ ] Проверить webhook: `cmctl check api`
- [ ] Проверить trust-manager: `kubectl get bundles -A`
- [ ] Протестировать выпуск self-signed сертификата
- [ ] Проверить метрики: `certmanager_certificate_ready_status == 0`
- [ ] Проверить Leader Election: `kubectl get endpoints -n cert-manager cert-manager-controller`

### Автоматизация обновлений через CI/CD

```yaml
# Пример GitLab CI stage для обновления cert-manager
cert-manager-upgrade:
  stage: deploy
  image: bitnami/kubectl:latest
  script:
  - |
    # Проверка текущей версии
    CURRENT=$(helm list -n cert-manager -o json | jq -r '.[0].chart_version')
    TARGET="1.21.0"
    
    if [ "$CURRENT" = "$TARGET" ]; then
      echo "Already at version $TARGET, skipping"
      exit 0
    fi
    
    # Бэкап
    kubectl get secret -n cert-manager -o yaml > backup-$(date +%s).yaml
    kubectl get issuers,clusterissuers,certificates -A -o yaml > resources-$(date +%s).yaml
    
    # Обновление CRD
    kubectl apply -f https://github.com/cert-manager/cert-manager/releases/download/v${TARGET}/cert-manager.crds.yaml
    
    # Обновление Helm
    helm upgrade cert-manager jetstack/cert-manager \
      --namespace cert-manager \
      --version v${TARGET} \
      --reuse-values --wait --timeout 5m
    
    # Верификация
    cmctl check api --wait=2m
    cmctl status certificate -A
  rules:
  - if: $CI_COMMIT_BRANCH == "main"
```

### Смотрите также

- **[Операции cert-manager](./operations.md)** — мониторинг и резервное копирование.
- **[Администрирование cert-manager](./index.md)** — HA, RBAC и Garbage Collection.
- **[Приватный CA: Операции](../Private_CA/operations.md)** — чеклист миграции для Private CA.
- **[Production Playbooks](./production_playbooks.md)** — реагирование на инциденты.
