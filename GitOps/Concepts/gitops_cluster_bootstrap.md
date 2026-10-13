# Первичная инициализация кластера в GitOps: решение проблемы «курицы и яйца» (Day-0 / Day-1 Bootstrap)

**Актуально для:** Kubernetes 1.28–1.32+ (On-Premise / Bare-Metal), Argo CD v2.10–v3.x, Flux v2.2–v2.4+, Helm v3.14–v3.16+

Руководство для SRE, DevOps-инженеров и системных администраторов по проектированию и автоматизации процесса первичной инициализации (bootstrap) bare-metal кластеров Kubernetes. Рассматривается преодоление проблемы «курицы и яйца», разграничение этапов Day-0, Day-1 и Day-2, безопасная доставка первичных секретов до старта реконсиляции и построение идемпотентного конвейера развертывания базовой инфраструктуры.

---

## Определения

| Термин | Определение |
| :--- | :--- |
| **Day-0 Provisioning** | Этап развертывания физической или виртуальной инфраструктуры: подготовка операционной системы серверов, сети, ядра, дисковых подсистем и базовых компонентов Kubernetes Control Plane (`kubeadm`, Kubespray, Talos). |
| **Day-1 Bootstrapping** | Процесс развертывания критических системных компонентов кластера (CNI, CSI, Cert-Manager) и самого GitOps-движка с последующей передачей ему контроля над кластером. |
| **Day-2 Operations** | Непрерывная штатная эксплуатация кластера: доставка прикладных микросервисов, мониторинг, ротация учетных записей, резервное копирование и масштабирование под управлением GitOps. |
| **Проблема «курицы и яйца» (Chicken-and-Egg Dilemma)** | Парадокс инициализации: GitOps-оператор должен развернуть инфраструктуру кластера из Git, но сам оператор не может функционировать без работающей сети (CNI), подключенных секретов для доступа к приватному репозиторию и API Kubernetes. |
| **Root Application (Корневое приложение)** | Единственный первичный манифест Argo CD (`Application`) или Flux (`Kustomization`), который создается вручную/скриптом на этапе Day-1 и запускает каскадную синхронизацию всех остальных манифестов кластера (паттерн App of Apps). |
| **Bootstrap Secrets Injection** | Процедура безопасной доставки начальных криптографических ключей (приватный ключ SOPS/Age, SSH deploy key к GitLab, токен AppRole для HashiCorp Vault) в кластер до старта первой итерации GitOps-синхронизации. |
| **Pre-GitOps Addons** | Набор низкоуровневых драйверов и сервисов (например, Calico/Cilium CNI, Ceph CSI, MetalLB), без которых поды контроллеров GitOps не могут получить IP-адреса и сетевую связность. |

---

## Архитектура и базовые концепции

### 1. Трехуровневая модель жизненного цикла кластера

В On-Premise и Bare-Metal инфраструктурах попытка управлять абсолютно всеми компонентами исключительно через GitOps с первой секунды приводит к блокировкам (дедлокам). Устойчивая архитектура опирается на строгое разделение этапов:

```text
┌────────────────────────────────────────────────────────────────────────┐
│                        Day-0: Provisioning                             │
│  Инструменты: Ansible / Kubespray / Terraform / PXE Boot               │
│  Результат: Подготовлены ноды ОС, запущен etcd, kube-apiserver, kubelet │
│  Статус: Ноды в статусе NotReady (нет CNI)                             │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ Передача kubeconfig
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                        Day-1: Cluster Bootstrap                        │
│  Инструменты: Bash / Helmfile / Kustomize CLI                          │
│  1. Установка CNI (Cilium/Calico) ──► Ноды переходят в Ready           │
│  2. Установка Storage CSI (Ceph-CSI / Local Storage)                   │
│  3. Инъекция Bootstrap-секретов (SSH Key, SOPS Age Key, Vault Token)  │
│  4. Установка GitOps Engine (Argo CD / Flux)                           │
│  5. Применение манифеста Root App-of-Apps                              │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ Передача управления
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                        Day-2: Pure GitOps Operations                   │
│  Инструменты: Argo CD / Flux CD Controller Loop                        │
│  Результат: Декларативная доставка мониторинга, Ingress, БД, бизнес-ПО │
│  Статус: Полный self-healing и синхронизация из ветки main             │
└────────────────────────────────────────────────────────────────────────┘
```

---

### 2. Анатомия проблемы «курицы и яйца» и ее декомпозиция

При инициализации кластера с нуля возникают четыре взаимосвязанные зависимости:

```text
               ┌────────────────────────────────────────┐
               │         Git-сервер (GitLab On-Prem)    │
               └───────────────────▲────────────────────┘
                                   │ Требует SSH Deploy Key
                                   │ и сетевой доступ к DNS
               ┌───────────────────┴────────────────────┐
               │     GitOps-оператор (Argo CD / Flux)   │
               └───────────────────▲────────────────────┘
                                   │ Требует Running статус подов,
                                   │ IP-адреса и монтирование томов
        ┌──────────────────────────┴──────────────────────────┐
        │                                                     │
 ┌──────┴──────────────┐                              ┌───────┴─────────────┐
 │ CNI (Cilium/Calico) │                              │ CSI (Ceph-CSI/Rook) │
 └─────────────────────┘                              └─────────────────────┘
```

1. **Зависимость сети (Network Deadlock):** Поды Argo CD / Flux требуют IP-адресов внутрикластерной сети (Pod CIDR) и доступа к CoreDNS. Без предварительно запущенного CNI контроллеры останутся в состоянии `Pending`.
2. **Зависимость аутентификации в Git (Credentials Deadlock):** Контроллер должен выкачать манифесты из защищенного приватного репозитория GitLab. Он не может получить deploy-ключ из самого репозитория, пока у него нет доступа к этому репозиторию.
3. **Зависимость расшифровки секретов (Decryption Key Deadlock):** Если манифесты зашифрованы с помощью SOPS/Age, контроллер не сможет распарсить их, пока в namespace `flux-system` или `argocd` не смонтирован приватный ключ шифрования.
4. **Зависимость Custom Resource Definitions (CRD Race Condition):** Бизнес-манифесты содержат кастомные ресурсы (`PrometheusRule`, `CertManager`, `ApplicationSet`). Если Root-приложение попытается применить их одновременно с установкой самих операторов, API-сервер вернет ошибку: `no matches for kind "..." in version "..."`.

---

### 3. Архитектура решения: Пре-инициализация и фаза передачи управления

Для гарантированной и повторяемой инициализации используется **двухфазный переход (Hand-off)**:

* **Императивно-декларативная фаза Day-1:** Минимальный скрипт автоматизации запускается один раз администратором или раннером пайплайна развертывания кластера. Он готовит плацдарм: накладывает CNI, монтирует локальные секреты доступа и инсталлирует сам GitOps-оператор.
* **Чистая декларативная фаза Day-2:** После появления в кластере оператора скрипт применяет единственный манифест — **Root Application**. Как только манифест принят API-сервером, скрипт завершает работу. Далее контроллер сам загружает дочерние приложения, соблюдая волны синхронизации (Sync Waves) или цепочки зависимостей (`dependsOn`).

---

## Практические сценарии и конфигурация

### Сценарий 1: Автоматизированный Day-1 Bootstrap скрипт для On-Premise кластера

Скрипт развертывания базовой платформы, запускаемый после завершения работы `kubeadm` / Kubespray:

```bash
#!/usr/bin/env bash
# bootstrap-cluster.sh — первичная инициализация bare-metal кластера
set -euo pipefail

CLUSTER_NAME="dc1-k8s-prod-01"
GITOPS_REPO="ssh://git@git.internal.corp/infrastructure/fleet-gitops.git"
SOPS_AGE_KEY_FILE="/etc/kubernetes/bootstrap-keys/sops-age.key"
GIT_DEPLOY_KEY_FILE="/etc/kubernetes/bootstrap-keys/gitlab-deploy.key"

echo "=== Шаг 1: Проверка базовой доступности API-сервера ==="
kubectl cluster-info > /dev/null

echo "=== Шаг 2: Установка CNI (Cilium) ==="
# CNI устанавливается до всех остальных компонентов, чтобы ноды перешли в Ready
helm upgrade --install cilium oci://harbor.internal.corp/charts/cilium \
  --version 1.16.2 \
  --namespace kube-system \
  --set ipam.mode=kubernetes \
  --set operator.replicas=2 \
  --wait --timeout=300s

echo "=== Шаг 3: Ожидание готовности CoreDNS ==="
kubectl wait --namespace kube-system \
  --for=condition=Available deployment/coredns \
  --timeout=120s

echo "=== Шаг 4: Подготовка namespace и первичных секретов для Argo CD ==="
kubectl create namespace argocd --dry-run=client -o yaml | kubectl apply -f -

# Инъекция SSH deploy key для доступа к Git
kubectl create secret generic argocd-git-creds \
  --namespace argocd \
  --from-file=sshPrivateKey="${GIT_DEPLOY_KEY_FILE}" \
  --dry-run=client -o yaml | \
  kubectl label -f - --dry-run=client -o yaml \
    argocd.argoproj.io/secret-type=repository | \
  kubectl apply -f -

# Инъекция приватного ключа SOPS/Age для расшифровки секретов
kubectl create secret generic sops-age \
  --namespace argocd \
  --from-file=age.agekey="${SOPS_AGE_KEY_FILE}" \
  --dry-run=client -o yaml | kubectl apply -f -

echo "=== Шаг 5: Установка базового Argo CD через Helm ==="
helm upgrade --install argocd oci://harbor.internal.corp/charts/argo-cd \
  --version 7.5.2 \
  --namespace argocd \
  --values /etc/kubernetes/bootstrap/argocd-bootstrap-values.yaml \
  --wait --timeout=300s

echo "=== Шаг 6: Применение Root App-of-Apps (Передача управления GitOps) ==="
kubectl apply -f /etc/kubernetes/bootstrap/root-application.yaml

echo "✔ Первичный Bootstrap завершен. Кластер передан под управление GitOps."
```

---

### Сценарий 2: Конфигурация корневого приложения (Root App-of-Apps) с Sync Waves

Чтобы избежать гонок между операторами и их кастомными ресурсами, корневое приложение использует **Sync Waves** (волны синхронизации):

```yaml
# /etc/kubernetes/bootstrap/root-application.yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: root-bootstrap
  namespace: argocd
  finalizers:
    - resources-finalizer.argocd.argoproj.io
spec:
  project: default
  source:
    repoURL: 'ssh://git@git.internal.corp/infrastructure/fleet-gitops.git'
    targetRevision: main
    path: clusters/dc1-k8s-prod-01/bootstrap
  destination:
    server: 'https://kubernetes.default.svc'
    namespace: argocd
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - CreateNamespace=true
      - ServerSideApply=true
```

Манифест дочерних приложений, управляемых корневым приложением:

```yaml
# clusters/dc1-k8s-prod-01/bootstrap/infrastructure-apps.yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: app-storage-csi
  namespace: argocd
  annotations:
    argocd.argoproj.io/sync-wave: "-2"   # Волна -2: Базовые драйверы блочного хранилища Ceph
spec:
  project: default
  source:
    repoURL: 'ssh://git@git.internal.corp/infrastructure/fleet-gitops.git'
    path: infrastructure/ceph-csi
  destination:
    server: 'https://kubernetes.default.svc'
    namespace: ceph-csi
---
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: app-cert-manager
  namespace: argocd
  annotations:
    argocd.argoproj.io/sync-wave: "-1"   # Волна -1: Контроллер сертификатов и базовые CRD
spec:
  project: default
  source:
    repoURL: 'ssh://git@git.internal.corp/infrastructure/fleet-gitops.git'
    path: infrastructure/cert-manager
  destination:
    server: 'https://kubernetes.default.svc'
    namespace: cert-manager
---
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: app-platform-workloads
  namespace: argocd
  annotations:
    argocd.argoproj.io/sync-wave: "0"    # Волна 0: Прикладные сервисы, Ingress и БД
spec:
  project: default
  source:
    repoURL: 'ssh://git@git.internal.corp/infrastructure/fleet-gitops.git'
    path: clusters/dc1-k8s-prod-01/apps
  destination:
    server: 'https://kubernetes.default.svc'
    namespace: apps
```

---

### Сценарий 3: Декларативный Bootstrap во Flux v2 с предсозданными секретами

Если целевым GitOps-агентом выбран Flux, процедура bootstrap выполняется встроенным CLI, однако для решения проблемы курицы и яйца секреты расшифровки SOPS обязаны быть внедрены **до** старта команды `flux bootstrap`:

```bash
# Предварительное создание namespace
kubectl create namespace flux-system --dry-run=client -o yaml | kubectl apply -f -

# Предсоздание секрета с приватным ключом age
cat /etc/kubernetes/bootstrap-keys/age.key | \
  kubectl create secret generic sops-age \
  --namespace flux-system \
  --from-file=age.agekey=/dev/stdin \
  --dry-run=client -o yaml | kubectl apply -f -

# Запуск bootstrap Flux (установит контроллеры и подтянет зашифрованный репозиторий)
flux bootstrap git \
  --url=ssh://git@git.internal.corp/infrastructure/fleet-gitops.git \
  --branch=main \
  --path=clusters/dc1-k8s-prod-01 \
  --private-key-file=/etc/kubernetes/bootstrap-keys/gitlab-deploy.key \
  --silent
# → ► connecting to ssh://git@git.internal.corp/...
# → ✔ cloned repository
# → ✔ components are ready
# → ✔ bootstrap finished
```

---

## Операции и команды

### 1. Верификация этапов готовности кластера при инициализации

Системный администратор контролирует последовательное завершение фаз bootstrap:

```bash
# 1. Проверка перехода нод в состояние Ready после подъема CNI
kubectl get nodes -o wide
# → NAME         STATUS   ROLES           AGE   VERSION   INTERNAL-IP
# → worker-01    Ready    <none>          5m    v1.32.2   192.168.10.21
# → worker-02    Ready    <none>          5m    v1.32.2   192.168.10.22

# 2. Проверка состояния контроллеров GitOps
kubectl get pods -n argocd -l app.kubernetes.io/name=argocd-application-controller
# → NAME                                             READY   STATUS    RESTARTS   AGE
# → argocd-application-controller-0                  1/1     Running   0          3m

# 3. Инспекция синхронизации корневого приложения
argocd app get root-bootstrap
# → Name:               argocd/root-bootstrap
# → Server:             https://kubernetes.default.svc
# → Sync Status:        Synced to main@sha1:4a12f8c
# → Health Status:      Healthy
```

### 2. Экстренный перезапуск процесса Bootstrap (Hard Reset)

В случае прерывания сетевой связности во время bootstrap и зависания ресурсов:

```bash
# Удаление зависшего корневого приложения без каскадного удаления инфраструктуры
kubectl delete application root-bootstrap -n argocd --cascade=orphan

# Повторное наложение манифеста после устранения сетевых неполадок
kubectl apply -f /etc/kubernetes/bootstrap/root-application.yaml
```

---

## Диагностика и устранение неполадок

| Симптом | Причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **Поды Argo CD / Flux висят в статусе `Pending`** | CNI не установлен; ноды в статусе `NotReady`; CoreDNS не запущен | `kubectl describe pod -n argocd <pod>` показывает `0/X nodes available: node(s) had untolerated taint {node.kubernetes.io/not-ready}` | Установить CNI (Cilium/Calico) на этапе Day-1 до развертывания контроллеров GitOps. |
| **Ошибка аутентификации Git: `Permission denied (publickey)`** | SSH deploy key не смонтирован либо публичная часть не добавлена в GitLab | Логи `argocd-repo-server` или `source-controller` во Flux | Проверить наличие секрета `argocd-git-creds` / `flux-system` и права ключа в GitLab Deploy Keys. |
| **Ошибка расшифровки манифестов: `age: no matching keys found`** | Секрет `sops-age` отсутствует или содержит ключ с несовпадающим публичным отпечатком | Логи `kustomize-controller`: `failed to decrypt` | Внедрить актуальный приватный ключ через `kubectl create secret generic sops-age` до запуска реконсиляции. |
| **CRD Race Condition: `no matches for kind "..."`** | Кастомный ресурс выкатывается одновременно с оператором до регистрации CRD | Статус `SyncFailed` в Argo CD: `the server could not find the requested resource` | Разнести установку операторов и CR-манифестов по разным фазам через `sync-wave` или `spec.dependsOn`. |

---

## Рекомендации и Best Practices

1. **Строгая идемпотентность Day-1 скрипта:** Скрипт первичной инициализации должен быть безопасным для повторного запуска (`helm upgrade --install`, `kubectl apply`, флаги `--dry-run=client`).
2. **Минимум логики вне Git:** Задача Day-1 скрипта — поднять сеть, прокинуть ключи и запустить GitOps-агента. Никакие прикладные манифесты, мониторинг или базы данных не должны ставиться скриптом в обход GitOps.
3. **Изоляция ключей шифрования:** Закрытые ключи age и токены Vault не должны храниться в открытом виде на нодах. Передавайте их через переменные CI/CD-пайплайна или оперативные защищенные носители.
4. **Норматив Disaster Recovery:** Время полного пересоздания упавшего bare-metal кластера из чистого Git («GitOps Re-bootstrap») не должно превышать 15–20 минут.

---

## Дополнительная информация

**Связанные документы:**
- [Паттерн App of Apps в Argo CD](../ArgoCD/argocd_app_of_apps.md) — детальная архитектура корневых и дочерних приложений.
- [Аварийное восстановление и DR в Argo CD](../ArgoCD/argocd_disaster_recovery.md) — регламенты восстановления кластера из Git с нуля.
- [Шифрование секретов в GitOps](../secrets_encryption.md) — интеграция SOPS, Age и External Secrets Operator.
- [Организация Flux CD monorepo](./flux_monorepo_organization.md) — структура монорепозитория для мультикластерного парка.

---

## Вопросы для собеседования

### 1. В чем заключается проблема «курицы и яйца» при развертывании кластера Kubernetes через GitOps и как она решается на практике?
**Ответ:** Проблема заключается в том, что GitOps-агент должен декларативно развернуть всю платформу из Git, но сам агент не может запуститься и функционировать без базовой сети (CNI), драйверов томов (CSI) и учетных данных (SSH-ключи или токены расшифровки SOPS/Vault) для чтения репозитория. Решение строится на разделении процесса на две фазы: **Day-1 Bootstrap** (императивно-декларативный скрипт разворачивает CNI, монтирует базовые секреты и ставит сам GitOps-агент) и **Day-2 Operations** (агент подхватывает Root App-of-Apps и переводит всю дальнейшую инфраструктуру в режим непрерывной GitOps-реконсиляции).

### 2. Почему CNI (Cilium или Calico) часто исключают из основного GitOps-пайплайна приложений и ставят на фазе Day-1?
**Ответ:** Без установленного CNI ноды кластера находятся в состоянии `NotReady`, а сетевой стек подов не инициализирован. Поды GitOps-контроллеров (`argocd-server`, `argocd-repo-server`, `source-controller`) не могут запуститься, получить IP-адреса и обратиться к DNS для резолва адреса корпоративного Git-сервера. Если CNI попытаться развернуть через GitOps-агента, возникнет дедлок: агент не может запуститься без сети, а сеть не может развернуться без агента.

### 3. Как предотвратить ошибку отсутствия CRD («no matches for kind»), если оператор и его кастомные ресурсы находятся в одном Git-репозитории?
**Ответ:** В Argo CD эта проблема решается механизмом **Sync Waves**: CRD и операторы помещаются в отрицательные волны (например, `sync-wave: "-2"` или `"-1"`), а ресурсы, зависящие от этих CRD — в нулевую или положительные волны (`sync-wave: "0"`). Argo CD ожидает перехода ресурсов предыдущей волны в статус `Healthy` перед переходом к следующей. Во Flux v2 используется директива `spec.dependsOn` в ресурсах `Kustomization`, которая блокирует применение прикладного оверлея до завершения синхронизации инфраструктурного оверлея с CRD.

### 4. Каким образом приватный ключ SOPS/Age попадает в кластер при холодном старте (Cold Bootstrap)?
**Ответ:** Приватный ключ никогда не хранится в Git. На этапе Day-1 раннер автоматизации развертывания кластера (например, защищенный GitLab Runner или локальный скрипт инженера с правами `admin`) считывает закрытый ключ из защищенного хранилища (HashiCorp Vault, переменная CI/CD с маскированием или KMS) и выполняет команду `kubectl create secret generic sops-age -n flux-system --from-file=age.agekey=...`. Только после создания этого секрета запускается контроллер GitOps, который использует смонтированный ключ для расшифровки всех остальных зашифрованных файлов репозитория.

### 5. Что такое «Pure GitOps Disaster Recovery» и сколько времени занимает восстановление кластера?
**Ответ:** Это процедура ликвидации последствий полной потери кластера (выход из строя etcd или разрушение всех control plane нод). Поскольку всё целевое состояние кластера зафиксировано в Git, для восстановления достаточно развернуть новый чистый control plane (`kubeadm init` или запуск плейбука Kubespray), накатить Day-1 скрипт с CNI и секретами доступа, и применить манифест Root Application. Argo CD или Flux автоматически скачают манифесты и восстановят все 100% сервисов, ингрессов и конфигураций до эталонного состояния за 15–25 минут.
