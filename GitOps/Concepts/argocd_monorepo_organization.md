# Организация монорепозитория Argo CD: архитектурный паттерн для ~20 кластеров

**Актуально для:** Argo CD v3.5+ (структура monorepo и архитектура оверлеев применимы ко всей линейке Argo CD v3.x)

Документ систематизирует инженерный опыт и практический кейс организации распределенной инфраструктуры (~20 Kubernetes-кластеров в корпоративных дата-центрах и bare-metal контурах) с использованием единого централизованного GitOps-монорепозитория и паттерна **App of Apps** в Argo CD.

Общие сведения о концепциях и архитектуре Argo CD приведены в [обзоре Argo CD](../ArgoCD/argocd_overview.md); мультикластерные топологии и классификация pull/push подходов — в [мульти-кластерных паттернах](./multi_cluster_patterns.md); паттерн App of Apps — в [App of Apps](../ArgoCD/argocd_app_of_apps.md); управление секретами — в [шифровании секретов в GitOps](../secrets_encryption.md).

---

## 1. Определения

- **Monorepo Argo CD** — единый Git-репозиторий, содержащий как конфигурации целевых кластеров, так и переиспользуемые шаблоны базовых инфраструктурных и прикладных компонентов. В рассматриваемой архитектуре состоит из двух корневых директорий: `clusters/` и `components/`.
- **`clusters/`** — директория экземпляров кластеров. Содержит по одной поддиректории на каждый обслуживаемый кластер, внутри которого выделены каталоги `custom-resources/` и `sync-code/`.
- **`components/`** — библиотека базовых деклараций и шаблонов (системные сервисы, CNI/NetworkPolicy, мониторинг, ingress, прикладные сервисы), совместно используемых парком кластеров.
- **`custom-resources/`** — кластерные переопределения, оверлеи Kustomize, ConfigMap с локальными параметрами (IP-диапазоны, имена ЦОД, реплики) и зашифрованные секреты конкретного кластера.
- **`sync-code/`** — декларации манифестов `Application` (CRD Argo CD), связывающие кластер с базовыми компонентами и оверлеями в `custom-resources/`. Точка входа синхронизации для Argo CD Application Controller.
- **Сквозной нейминг (Uniform Naming Convention)** — строгое правило соответствия имен: имя директории пространства имен, имя подключающего ресурса `Application` в `sync-code/` и имя целевого ресурса (например, `HelmRelease` или Deployment) совпадают.
- **Заглушка невалидного ключа (Fail-Safe Stub)** — паттерн защиты шаблонов безопасности (например, NetworkPolicy), при котором в базовый манифест закладывается заведомо некорректное значение (например, `namespace: "__PLACEHOLDER_INVALID_NAMESPACE__"`), блокирующее случайное применение сырого шаблона без кластерного оверлея.
- **Reconciliation Loop (Цикл сверки)** — непрерывный процесс сравнения объявленного в Git состояния (Desired State) с фактическим состоянием объектов в etcd Kubernetes-кластера (Actual State) с автоматическим исправлением расхождений.
- **Blast Radius (Радиус поражения)** — масштаб потенциального сбоя при внесении некорректных изменений в базовый компонент, затрагивающий зависимые кластеры.

---

## 2. Базовые концепции и архитектура

### 2.1 Исходные предпосылки и проблематика парка кластеров

Исходное состояние инфраструктуры:
- Около 20 автономных Kubernetes-кластеров (bare-metal серверы в основных и резервных корпоративных ЦОД, тестовые и стейджинг-зоны).
- Архитектура «один кластер — один Git-репозиторий».
- Шаблонизация через Git-субмодули поверх общих модулей Terraform: высокое зацепление, рассинхронизация коммитов субмодулей между репозиториями, невозможность централизованного аудита.
- Отсутствие единых корпоративных стандартов сетевой изоляции (NetworkPolicy) и ролевого доступа (RBAC).
- Требования регуляторов и аудита ISO 27001 / Disaster Recovery: обязательное детерминированное развертывание чистых bare-metal кластеров с нуля за фиксированное время.

**Ключевые требования к целевому дизайну:**
1. Единый источник правды (SSoT) для всех кластеров без дублирования манифестов.
2. Прозрачное версионирование компонентов и поэтапный ввод изменений в эксплуатацию.
3. Низкий порог входа для инженеров платформы и системных администраторов.
4. Отсутствие внешних облачных зависимостей: работа в изолированных контурах (on-premise / bare-metal).

### 2.2 Архитектурные особенности Argo CD для монорепозитория

Argo CD реализует **централизованную pull-модель** на основе паттерна App of Apps, что делает его естественным выбором для монорепозитория с ~20 кластерами:

- **Паттерн App of Apps:** один root `Application` в bootstrap-директории разворачивает дочерние `Application` для каждого компонента и окружения. Каждое дочернее приложение может иметь собственный тип источника (Git, Helm, OCI) и параметры синхронизации.
- **Sync Waves:** аннотация `argocd.argoproj.io/sync-wave` задает строгую очередность развертывания между приложениями, обеспечивая корректный порядок: CRD → системные сервисы → прикладные компоненты.
- **Централизованная точка управления:** контрольная плоскость Argo CD работает на hub-кластере и управляет всеми spoke-кластерами через kubeconfig (по модели Hub-and-Spoke), что позволяет централизованно аудитовать все изменения и конфликты слияний.
- **Гибрид pull и push:** Argo CD использует pull-модель для синхронизации состояния (контроллер инициирует соединение с целевыми кластерами), но также поддерживает webhook-доставку изменений через `argocd-notification` для оперативного триггера синхронизации.

Подробное описание паттерна App of Apps и структуры репозитория — в [App of Apps](../ArgoCD/argocd_app_of_apps.md).

### 2.3 Анализ первой неудавшейся структуры monorepo

При первой попытке миграции была скопирована стандартная референсная структура Argo CD:
```text
repo/
├── clusters/
├── apps/
└── infrastructure/
```

**Причины неудачи на парке из ~20 кластеров:**
- **Массовый Copy-Paste:** инженеры копировали директории соседних кластеров целиком. Манифесты мониторинга и инфраструктурных операторов насчитывали тысячи строк. В результате в кластерах возникали несовместимые лимиты ресурсов, неверные адреса внутренних DNS и порты.
- **Неконтролируемое обновление CRD:** при использовании Helm-чартов операторов (Prometheus Operator, Cert-Manager) `argocd-application-controller` не обновлял существующие CRD при апгрейде чарта (штатное поведение Helm для предотвращения потери данных в etcd). Без разделения CRD на отдельный sync wave синхронизация ломалась.
- **Когнитивная перегрузка:** команда платформы тратила часы на поиск различий между кластерами из-за запутанных взаимных ссылок между `apps/` и `infrastructure/`.

### 2.4 Целевая архитектура: Двухдиректориальный Monorepo

Итоговая архитектура устраняет дублирование за счет жесткого разделения на глобальные компоненты (`components/`) и кластерные инстансы (`clusters/`):

```text
argo-monorepo/
├── .sops.yaml                             # Правила шифрования секретов age для ЦОД
├── clusters/                              # Конфигурации целевых кластеров
│   ├── dc1-prod-01/                       # Продакшен-кластер в ЦОД-1
│   │   ├── custom-resources/              # Оверлеи Kustomize и кластерные переменные
│   │   │   ├── infrastructure-crds/
│   │   │   ├── network-system/
│   │   │   └── monitoring/
│   │   └── sync-code/                     # Application CRD (точки входа Argo CD)
│   │       ├── infrastructure-crds.yaml
│   │       ├── network-system.yaml
│   │       └── monitoring.yaml
│   ├── dc2-prod-02/                       # Продакшен-кластер в ЦОД-2
│   └── dc1-stage-01/                      # Стейджинг-кластер
└── components/                            # Единая библиотека базовых шаблонов
    ├── base-crds/                         # Шаблоны CRD (Prometheus, Cert-Manager)
    ├── bootstrap/                         # Манифесты установки Argo CD по версиям
    │   ├── v3.5.x-prod/
    │   └── v3.5.x-stage/
    ├── network-policies/                  # Базовый каркас сетевой безопасности
    ├── monitoring/                        # Стек мониторинга (Prometheus + Grafana)
    └── ingress-nginx/                     # Ingress-контроллер bare-metal
```

**Фундаментальные принципы архитектуры:**
1. **Плоская иерархия по пространствам имен:** имя поддиректории в `custom-resources/` строго соответствует целевому Namespace и имени файла в `sync-code/`.
2. **Связывание через относительные пути:** `custom-resources/<ns>/kustomization.yaml` ссылается на базовый шаблон `../../../components/<component>/` и накладывает только локальные диффы (patches, configMapGenerator).
3. **Изоляция контуров:** тестовые (dev/stage) и боевые (prod) окружения никогда не совмещаются на одном физическом кластере. Кластер целиком принадлежит определенному контуру.
4. **Ветка как селектор среды:** объект `Application` кластера может ссылаться на долгоживущую ветку (`main`, `staging`) или на сервисную ветку обслуживания (`maintenance/upgrade-monitoring`) для безопасного тестирования изменений на выделенном кластере.

---

## 3. Практические сценарии и конфигурация

### 3.1 Сценарий 1: Декларативный Bootstrap и установка Argo CD на Bare-Metal

Установка Argo CD в изолированных кластерах дата-центра выполняется через генерацию манифестов с последующим применением через корпоративный IaC (Terraform/OpenTofu или локальный оркестратор). Это исключает необходимость предоставления утилите `argocd` прямого сетевого доступа к кластерам из внешней сети.

#### Шаг 1: Экспорт манифестов Argo CD в monorepo

Манифесты генерируются и фиксируются в репозитории:

```bash
# Экспорт манифестов Argo CD v3.5.5 в директорию monorepo
argocd install \
  --version=v3.5.5 \
  --client-side \
  > components/bootstrap/v3.5.x-prod/argocd-install.yaml

# Экспорт Application CR для кластерного bootstrap
cat <<EOF > components/bootstrap/v3.5.x-prod/cluster-bootstrap.yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: cluster-bootstrap
  namespace: argocd
  finalizers:
    - resources-finalizer.argocd.argoproj.io
spec:
  project: default
  source:
    repoURL: ssh://git@git.internal.corp/infrastructure/argo-monorepo.git
    targetRevision: main
    path: clusters/dc1-prod-01/sync-code
  destination:
    server: https://kubernetes.default.svc
    namespace: default
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - CreateNamespace: true
      - ServerSideApply: true
EOF
```

#### Шаг 2: Создание базового Application в кластере

Каждый кластер настраивается на чтение монорепозитория через локальный SSH-ключ (`deploy-key`), обладающий правами read-only:

```yaml
# clusters/dc1-prod-01/sync-code/bootstrap.yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: infra-bootstrap
  namespace: argocd
  finalizers:
    - resources-finalizer.argocd.argoproj.io
spec:
  project: default
  source:
    repoURL: ssh://git@git.internal.corp/infrastructure/argo-monorepo.git
    targetRevision: main
    path: clusters/dc1-prod-01/sync-code
  destination:
    server: https://kubernetes.default.svc
    namespace: default
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
```

#### Шаг 3: Верификация установки в кластере

После применения стартовых манифестов выполняется диагностика:

```bash
argocd server version
# → v3.5.5+latest

kubectl -n argocd get pods -l app.kubernetes.io/part-of=argocd
# → NAME                                     READY   STATUS    RESTARTS   AGE
# → argocd-application-controller-0          1/1     Running   0          5m
# → argocd-repo-server-5d4c7f8b9c-xl2m4     1/1     Running   0          5m
# → argocd-server-6c7d9f4c8c-9m5wq          1/1     Running   0          5m

argocd app list
# → NAME              SERVER                      NAMESPACE  PATH  ...
# → cluster-bootstrap https://kubernetes.default.svc  argocd    clusters/dc1-prod-01/sync-code
```

---

### 3.2 Сценарий 2: Подключение инфраструктурного компонента и разрешение проблем CRD

Классическая проблема при обновлении Prometheus Operator в bare-metal парке: Helm не обновляет CRD при апгрейде чарта. В архитектуре monorepo эта задача решается жестким разделением на два независимых sync wave: CRD-приложение (wave `-10`) разворачивается раньше оператора (wave `0`).

#### Шаг 1: Декларация CRD-компонента в sync-code

```yaml
# clusters/dc1-prod-01/sync-code/infrastructure-crds.yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: monitoring-crds
  namespace: argocd
  finalizers:
    - resources-finalizer.argocd.argoproj.io
  annotations:
    argocd.argoproj.io/sync-wave: "-10"
spec:
  project: default
  source:
    repoURL: ssh://git@git.internal.corp/infrastructure/argo-monorepo.git
    targetRevision: main
    path: ./components/monitoring/crds
  destination:
    server: https://kubernetes.default.svc
    namespace: monitoring
  syncPolicy:
    automated:
      prune: false                        # Защита от случайного удаления CRD при переименованиях
      selfHeal: true
```

#### Шаг 2: Декларация основного оператора с явной зависимостью через sync wave

```yaml
# clusters/dc1-prod-01/sync-code/monitoring.yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: monitoring
  namespace: argocd
  finalizers:
    - resources-finalizer.argocd.argoproj.io
  annotations:
    argocd.argoproj.io/sync-wave: "0"
spec:
  project: default
  source:
    repoURL: ssh://git@git.internal.corp/infrastructure/argo-monorepo.git
    targetRevision: main
    path: ./clusters/dc1-prod-01/custom-resources/monitoring
  destination:
    server: https://kubernetes.default.svc
    namespace: monitoring
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
```

#### Шаг 3: Кластерный оверлей (custom-resources)

Внутри `clusters/dc1-prod-01/custom-resources/monitoring/kustomization.yaml` подключается базовый компонент и подставляются параметры конкретного дата-центра:

```yaml
# clusters/dc1-prod-01/custom-resources/monitoring/kustomization.yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
namespace: monitoring
resources:
  - ../../../../components/monitoring/base
configMapGenerator:
  - name: cluster-variables
    literals:
      - CLUSTER_NAME=dc1-prod-01
      - DATACENTER=dc-1-spb
      - RETENTION_TIME=30d
      - STORAGE_CLASS=local-nvme-sc
patches:
  - path: patches/resources-patch.yaml
```

Патч ресурсов для подгонки под аппаратный профиль узлов конкретного кластера:
```yaml
# clusters/dc1-prod-01/custom-resources/monitoring/patches/resources-patch.yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: monitoring
  namespace: argocd
spec:
  source:
    helm:
      values: |
        prometheus:
          prometheusSpec:
            resources:
              requests:
                cpu: 4000m
                memory: 16Gi
              limits:
                cpu: 8000m
                memory: 32Gi
```

---

### 3.3 Сценарий 3: Сетевая безопасность — Заглушка невалидного ключа в NetworkPolicy

Для соблюдения жестких требований безопасности в дата-центрах все входящие соединения по умолчанию заблокированы. При этом базовый шаблон NetworkPolicy не должен быть случайно применен в кластере без указания специфичных сетевых диапазонов (CIDR) площадки.

#### Шаг 1: Базовый шаблон с невалидной заглушкой
```yaml
# components/network-policies/base/deny-ingress-default.yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: default-deny-all-ingress
  namespace: "__PLACEHOLDER_INVALID_NAMESPACE__"   # Срабатывает синтаксическая ошибка при попытке прямого применения
spec:
  podSelector: {}
  policyTypes:
    - Ingress
```

#### Шаг 2: Базовый шаблон разрешения DNS для локального CoreDNS
```yaml
# components/network-policies/base/allow-dns.yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-coredns-egress
  namespace: "__PLACEHOLDER_INVALID_NAMESPACE__"
spec:
  podSelector: {}
  policyTypes:
    - Egress
  egress:
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
        - protocol: TCP
          port: 53
```

#### Шаг 3: Кластерный оверлей с подстановкой локальных CIDR и валидного Namespace
```yaml
# clusters/dc1-prod-01/custom-resources/network-system/kustomization.yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
namespace: production-apps
resources:
  - ../../../../components/network-policies/base
patches:
  - target:
      kind: NetworkPolicy
    patch: |-
      - op: replace
        path: /metadata/namespace
        value: production-apps
  - target:
      kind: NetworkPolicy
      name: allow-datacenter-internal
    patch: |-
      - op: add
        path: /spec/egress/0/to/-
        value:
          ipBlock:
            cidr: 10.120.0.0/16       # Корпоративная локальная сеть ЦОД-1
```

Если инженер попытается применить `components/network-policies/base` напрямую в кластер в обход оверлея, валидатор API Kubernetes немедленно отклонит операцию:
```bash
kubectl apply -k components/network-policies/base
# → The NetworkPolicy "default-deny-all-ingress" is invalid: metadata.namespace: Invalid value: "__PLACEHOLDER_INVALID_NAMESPACE__": a lowercase RFC 1123 label must consist of lower case alphanumeric characters or '-'
```

---

### 3.4 Сценарий 4: Безопасное управление секретами через SOPS и age в изолированных ЦОД

В bare-metal кластерах отсутствуют облачные сервисы KMS (AWS KMS, GCP KMS). Хранение паролей баз данных, сертификатов и токенов реализуется через связку **SOPS + age** с нативной поддержкой Argo CD через секрет `argocd-secret`.

#### Шаг 1: Конфигурация `.sops.yaml` в корне репозитория

Каждый кластер или группа кластеров дата-центра получает собственный открытый ключ `age`:

```yaml
# .sops.yaml (корень monorepo)
creation_rules:
  - path_regex: clusters/dc1-prod-01/.*\.enc\.yaml$
    age: "age1ql3z7hjy54pw3hyww5ayyfg7zqgvc7w3j2elw8zmrj2kg5sfn9aqmcac8p"
  - path_regex: clusters/dc2-prod-02/.*\.enc\.yaml$
    age: "age1h895xumvd332z7t2g7e4z4z3j9xql2g6q5h7l8m9n0p1q2r3s4t5u6v7w8"
  - path_regex: clusters/dc1-stage-01/.*\.enc\.yaml$
    age: "age1stage9876543210abcdef0123456789abcdef0123456789abcdef01234567"
```

#### Шаг 2: Создание Secret с приватным ключом в кластере

Приватный ключ генерируется администратором и передается в кластер при инициализации:

```bash
# Генерация ключа администратором (выполняется один раз на кластер)
age-keygen -o dc1-prod-01.age.key
# → Public key: age1ql3z7hjy54pw3hyww5ayyfg7zqgvc7w3j2elw8zmrj2kg5sfn9aqmcac8p

# Добавление приватного ключа в argocd-secret для нативной расшифровки SOPS
kubectl -n argocd patch secret argocd-secret \
  --type merge -p "{\"stringData\":{\"data.agekey\":\"$(cat dc1-prod-01.age.key)\"}}"
# → secret/argocd-secret patched
```

#### Шаг 3: Шифрование секретов в Git
```bash
# Создание открытого секрета
cat <<EOF > clusters/dc1-prod-01/custom-resources/monitoring/grafana-creds.enc.yaml
apiVersion: v1
kind: Secret
metadata:
  name: grafana-admin-credentials
  namespace: monitoring
type: Opaque
stringData:
  admin-user: admin
  admin-password: SuperSecretInternalPassword123!
EOF

# Шифрование на месте
sops --encrypt --in-place clusters/dc1-prod-01/custom-resources/monitoring/grafana-creds.enc.yaml
```

#### Шаг 4: Нативная поддержка SOPS в Argo CD

С момента добавления ключа в `argocd-secret` любые SOPS-зашифрованные YAML/JSON-файлы в репозитории Git расшифровываются автоматически на стороне `argocd-repo-server` во время синхронизации. Дополнительных манифестов настройки не требуется.

Для Helm-чартов с зашифрованными `values` используйте [CMP v2 плагин](../ArgoCD/helm_integration.md#сценарий-6-шифрование-секретов-поверх-helm-через-cmp-v2-и-sops).

---

### 3.5 Сценарий 5: CI/CD автоматизация валидации Monorepo (DevOps Pre-merge Gates)

Главный риск монорепозитория на ~20 кластеров — синтаксическая ошибка в каталоге `components/`, способная заблокировать реконсиляцию всего парка. Для защиты мастер-ветки в локальном CI (GitLab CI / Gitea Actions) настраивается строгий конвейер валидации.

#### Пайплайн валидации репозитория
```yaml
# .gitlab-ci.yml (пример для bare-metal GitLab Runner)
stages:
  - lint
  - test-build

yaml-lint:
  stage: lint
  image: alpine/k8s:1.32.2
  script:
    - yamllint -c .yamllint.yaml .

validate-kustomize-and-schemas:
  stage: test-build
  image: alpine/k8s:1.32.2
  before_script:
    - curl -s https://raw.githubusercontent.com/yannh/kubeconform/master/scripts/install.sh | sh
  script:
    - echo "=== Проверка Kustomize сборки для всех 20 кластеров ==="
    - |
      for cluster_dir in clusters/*; do
        if [ -d "$cluster_dir/custom-resources" ]; then
          for ns_dir in "$cluster_dir/custom-resources"/*; do
            if [ -f "$ns_dir/kustomization.yaml" ]; then
              echo "Сборка оверлея: $ns_dir"
              kubectl kustomize "$ns_dir" | kubeconform -strict -summary -ignore-missing-schemas
            fi
          done
        fi
      done
```

---

## 4. Операции и регламентные команды

Сводная таблица повседневных команд SRE и системных администраторов при эксплуатации парка Argo CD:

| Задача | Команда | Назначение / Ожидаемый результат |
| :--- | :--- | :--- |
| **Проверка статуса кластера** | `argocd app list` | Вывод всех приложений, их статусов синхронизации и состояний |
| **Список всех Application** | `kubectl get applications -n argocd` | Список всех ресурсов Application с текущими статусами (Synced, OutOfSync, Healthy) |
| **Принудительный sync Git** | `argocd app sync <app-name>` | Немедленная синхронизация приложения с состоянием в Git |
| **Приостановка синхронизации** | `argocd app suspend <app-name>` | Заморозка реконсиляции при аварийных работах |
| **Возобновление синхронизации** | `argocd app resume <app-name>` | Разморозка и приведение кластера к состоянию в Git |
| **Проверка расхождений (Diff)** | `argocd app diff <app-name>` | Сравнение желаемого состояния из Git с реальным состоянием объектов в API |
| **Трассировка событий** | `kubectl describe application <name> -n argocd` | Подробный вывод событий синхронизации и статуса |
| **Форсированный пересчет** | `argocd app hard-refresh <app-name>` | Перечитывает манифесты из Git и пересинхронизирует (без очистки кэша) |

### Примеры выполнения типовых операций

#### Форсированное применение изменений после коммита
```bash
argocd app sync cluster-bootstrap
# → Enter the server address (press enter for http://localhost:8080):
# → Enter username of admin:
# → Enter password:
# → ...
# → Sync application cluster-bootstrap? (y/n): y
# → ✅ Sync operation to cluster-bootstrap completed

argocd app wait monitoring --health --sync --timeout 300
# → Waiting for application syncing and health: cluster-bootstrap...
# → Application syncing succeeded. Current sync: Synced, Health: Healthy
```

#### Приостановка реконсиляции при проведении планового обслуживания (Maintenance Window)
```bash
argocd app suspend monitoring
# → Application 'monitoring' suspended

argocd app list
# → NAME        SERVER                      NAMESPACE  PATH                          ...  SUSPENDED
# → monitoring  https://kubernetes.default.svc  argocd  clusters/dc1-prod-01/...      ...  True
```

---

## 5. Диагностика и устранение неполадок

| Проблема / Симптом | Первопричина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **CRD не обновляются при апгрейде Helm-чарта оператора** | Дизайн Helm: `helm upgrade` не накатывает новые CRD из чарта во избежание порчи схемы в etcd | `kubectl get crd <name> -o yaml` (версия устарела); ошибки `validation error: unknown field` в логах | Вынести CRD в отдельный `Application` в `components/base-crds/` с `sync-wave: "-10"` и связать с основным оператором через `syncPolicy.requires` |
| **Ошибка невалидного Namespace (`RFC 1123 label`)** | Сработала заглушка `__PLACEHOLDER_INVALID_NAMESPACE__` в базовом NetworkPolicy | `argocd app get monitoring` → статус `OutOfSync`; `kubectl describe application monitoring -n argocd` → событие `ValidationError` | В `custom-resources/<ns>/kustomization.yaml` добавить патч, заменяющий `/metadata/namespace` на валидное имя |
| **`failed to decrypt: no matching age key found`** | Отсутствует ключ `age` в `argocd-secret` или ключ не соответствует получателю в `.sops.yaml` | `kubectl describe secret argocd-secret -n argocd`<br>`kubectl logs -n argocd deploy/argocd-repo-server --tail=50` | Проверить наличие ключа: `kubectl -n argocd get secret argocd-secret -o jsonpath='{.data.agekey}'`. Убедиться, что публичный ключ в `.sops.yaml` совпадает с ключом в `argocd-secret`. Перезапустить `argocd-repo-server`: `kubectl rollout restart deployment/argocd-repo-server -n argocd`. |
| **Циклическая зависимость (Cyclic Dependency)** | Взаимные ссылки в `sync-wave` между объектами `Application` при неверной аннотации | `argocd app list` показывает статус `Error` или `Unknown`; `kubectl describe application <name>` выводит событие о циклической зависимости | Построить направленный ациклический граф (DAG); развязать циклические ссылки путем разнесения sync-wave на 10+ пунктов |
| **Таймаут синхронизации (apiserver timeout / throttling)** | Одновременный запуск синхронизации десятков тяжелых компонентов перегружает control-plane | Высокий CPU на мастерах; в логах контроллера: `context deadline exceeded` | Разнести `spec.syncPolicy.syncOptions` по времени; ограничить `--concurrent` у `argocd-application-controller` |
| **Случайное удаление ресурсов (Pruning)** | Опечатка в пути оверлея или имени namespace при `spec.prune: true` | Argo CD удаляет рабочие Pods/Deployments: статус `deleted resource ...` | Временно выставить `prune: false` в `syncPolicy`; восстановить манифесты; настроить CI-валидацию |

### Пример отладки сбоя синхронизации Application
```bash
# 1. Быстрый просмотр статуса
argocd app list
# → NAME        SERVER                      STATUS    HEALTH   ...  MESSAGE
# → monitoring  https://kubernetes.default.svc  OutOfSync  Progressing  kustomize build failed: missing file cluster-variables.yaml

# 2. Получение расширенной информации из Kubernetes Events
kubectl describe application monitoring -n argocd
# → Type     Reason          Age   Message
# → Warning  ResourceOutOfSync  2m   kustomize-controller failed: accumulating resources: accumulation err='accumulating resources from 'custom-resources/monitoring': missing file'

# 3. Анализ логов соответствующего контроллера
kubectl logs -n argocd deploy/argocd-repo-server --tail=50
```

---

## 6. Рекомендации и Best Practices (SRE / DevOps / Sysadmin)

### 6.1 Архитектурные стандарты
1. **Строго две директории верхнего уровня:** `clusters/` (экземпляры) и `components/` (шаблоны). Не создавать смешанные каталоги `apps/`, `infra/` на верхнем уровне monorepo во избежание лавинообразного копирования кода.
2. **Изоляция окружений на физическом уровне:** продакшен и стейджинг размещаются в раздельных кластерах. Запрещено использовать общие физические worker-узлы для prod и dev с разделением только по Namespace.
3. **Единый сквозной нейминг:** если компонент называется `monitoring`, то директория в `components/` называется `monitoring`, подкаталоги в `clusters/<cluster>/` — `monitoring/`, а ресурс в `sync-code/` — `monitoring.yaml`.

### 6.2 Надежность и отказоустойчивость (SRE)
1. **Канареечное развертывание платформенных компонентов:** перед обновлением версии базового компонента (например, Ingress или CNI) в ветке `main` переключите один стейджинг-кластер на сервисную ветку через параметр `spec.source.targetRevision` в его `Application`. После стабилизации изменения сливаются в `main`.
2. **Защита от каскадного удаления (Prune Safety):** критически важные кластерные ресурсы (CRD, PersistentVolumeClaim, внешние базы данных) должны сопровождаться аннотацией:
   ```yaml
   metadata:
     annotations:
       argocd.argoproj.io/sync-options: Prune=false
   ```
3. **Оптимизация интервала синхронизации:** при наличии 20 кластеров одновременный запрос к Git-серверу каждые 3 минуты создает пиковую нагрузку. Рекомендуется установить `spec.syncPolicy.syncOptions: [SyncTimeoutHardSubtract=true]` и использовать webhook-триггеры для оперативной синхронизации при коммитах вместо периодического опроса.

### 6.3 Эксплуатация и безопасность (Sysadmin)
1. **Минимальные привилегии (Impersonation):** не позволять `argocd-application-controller` применять ресурсы под дефолтным суперпользователем `cluster-admin`. Назначать выделенные `ServiceAccount` для каждого Application через `spec.destination.serviceAccountName: team-billing` с ограниченными RBAC-правами в рамках конкретного namespace.
2. **Локальное шифрование SOPS + age:** полностью отказаться от хранения незашифрованных секретов в Git. Использовать раздельные ключи age для каждой локации/ЦОД, чтобы компрометация одного узла не ставила под угрозу весь парк.
3. **Ограничение concurrency на слабых узлах control-plane:** если узлы управления кластера имеют ограниченные ресурсы CPU, настройте флаги `argocd-application-controller`:
   ```yaml
   args:
     - --plugins=
     - --application-resource-tracking-method=annotation
     - --enable-gca-discovery=false
     - --concurrent=2    # По умолчанию 4
   ```

---

## 7. Дополнительная информация

**Связанные документы в базе знаний:**
- [App of Apps](../ArgoCD/argocd_app_of_apps.md) — паттерн управления десятками и сотнями приложений через корневой Application.
- [ApplicationSet](../ArgoCD/argocd_applicationsets.md) — автоматическое создание Application по шаблонам (массовый деплой по множеству кластеров).
- [Шифрование секретов в GitOps](../secrets_encryption.md) — руководство по SOPS, age, ротации ключей и External Secrets Operator.
- [Сравнение Argo CD и Flux](../argo_vs_flux_manifests.md) — архитектурные различия и спецификации манифестов.
- [NetworkPolicy: CI/CD и GitOps](../../Kubernetes/Networking/Network/NetworkPolicy/gitops_ci_cd.md) — конвейеры автоматической валидации сетевых политик.

**Официальные источники и спецификации:**
- [Официальная документация Argo CD](https://argo-cd.readthedocs.io/) — руководства по паттернам App of Apps, ApplicationSet и управлению секретами.
- [Репозиторий проекта SOPS (CNCF Sandbox)](https://github.com/getsops/sops) — шифрование конфигураций и интеграция с age/KMS.

---

## 8. Вопросы для собеседования

### 1. Почему в монорепозитории разделение структуры строго на две директории (`clusters/` и `components/`) считается эталонным для мультикластерного парка?
**Ответ:** 
- Директория `components/` (шаблоны) содержит чистую библиотеку абстрактных компонентов без привязки к конкретным кластерам, IP-адресам или секретам.
- Директория `clusters/` (экземпляры) содержит конкретные инстансы кластеров, которые собирают нужные компоненты через Kustomize-оверлеи и накладывают специфичные патчи (размеры пулов, ingress хосты).
Это устраняет дублирование кода (DRY), исключает копирование одних и тех же YAML-файлов между 20 кластерами и локализует изменения: обновление версии базового сервиса в `components/` автоматически распространяется на весь парк, либо раскатывается поэтапно через канареечные кластеры.

### 2. Как директива `argocd.argoproj.io/sync-wave` решает проблему гонок зависимостей при установке операторов и кастомных ресурсов (CRD)?
**Ответ:** Классический пример — Prometheus Operator или Cert-Manager. Если ресурс мониторинга `Prometheus` попытаться применить одновременно с чартом оператора, API-сервер вернет ошибку отсутствия CRD. Аннотация `sync-wave` связывает объекты `Application` в направленный ациклический граф (DAG). Argo CD гарантирует, что `Application` с `sync-wave: "-10"` (CRD) будет полностью синхронизирован и перейдет в статус `Health: Healthy`, прежде чем начнет обрабатываться `Application` с `sync-wave: "0"` (оператор).

### 3. Какой радиус поражения (Blast Radius) несет синтаксическая ошибка в каталоге `components/` в монорепозитории на 20 кластеров и как защитить прод?
**Ответ:** Радиус поражения максимален: если ошибка закоммичена в ветку `main`, синхронизация упадет одновременно во всех 20 кластерах парка.
**Защита:**
1. **Pre-merge CI Gates:** в GitLab CI на каждый Merge Request запускается конвейер, прогоняющий `kubectl kustomize` и `kubeconform -strict` по всем 20 каталогам `clusters/*`. Если хотя бы один оверлей не компилируется, слияние в `main` блокируется.
2. **Canary Cluster Tracking:** прод-кластеры отслеживают тегированные релизы или фиксированные коммиты, в то время как dev-кластер синхронизируется с `HEAD` ветки `main`.

### 4. Как во Argo CD реализуется безопасная изоляция команд (Multi-Tenancy) без выдачи администраторских прав?
**Ответ:** Argo CD использует собственную абстракцию изоляции — **AppProject**. В каждом `Application` указывается поле `spec.project: <team-project>`. AppProject определяет, какие Git-репозитории разрешено использовать, в какие кластеры и неймспейсы разрешен деплой, какие ресурсы разрешено/запрещено создавать (например, запрет создания `ClusterRoleBinding` или правок `ResourceQuota`). Если команда попытается через GitOps создать ClusterRoleBinding или захватить чужой неймспейс, Argo CD заблокирует синхронизацию с ошибкой `Forbidden`.

### 5. Для каких ресурсов обязательно выставлять аннотацию `argocd.argoproj.io/sync-options: Prune=false`?
**Ответ:** Для критических ресурсов, потеря которых необратима:
- Пользовательские CustomResourceDefinitions (CRD): удаление CRD мгновенно уничтожает все существующие объекты этого типа во всем кластере!
- Пространства имен (Namespaces): случайное удаление манифеста namespace каскадно уничтожит базы данных, секреты и PVC.
- PersistentVolumeClaim (PVC): защита данных от случайной очистки при рефакторинге репозитория.
Аннотация запрещает Argo CD удалять объект из кластера, даже если манифест был удален из Git-репозитория.
