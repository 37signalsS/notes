# Организация Flux CD monorepo: кейс миграции с Flux v1 на ~20 кластерах

**Актуально для:** Flux v2.9.x (структура monorepo и архитектура оверлеев полностью совместимы со всей линейкой Flux v2.x)

Документ систематизирует инженерный опыт и практический кейс миграции распределенной инфраструктуры (~20 Kubernetes-кластеров в корпоративных дата-центрах и bare-metal контурах) с устаревшего Flux v1 на современный стек Flux v2 с организацией единого централизованного GitOps-монорепозитория. 

Общие сведения о контроллерах и архитектуре GitOps Toolkit приведены в [обзоре Flux](../flux.md); мультикластерные топологии и классификация pull/push подходов — в [мульти-кластерных паттернах](./multi_cluster_patterns.md); управление секретами — в [шифровании секретов в GitOps](../secrets_encryption.md).

---

## 1. Определения

- **Monorepo Flux** — единый Git-репозиторий, содержащий как конфигурации целевых кластеров, так и переиспользуемые шаблоны базовых инфраструктурных и прикладных компонентов. В рассматриваемой архитектуре состоит из двух корневых директорий: `clusters/` и `components/`.
- **`clusters/`** — директория экземпляров кластеров. Содержит по одной поддиректории на каждый обслуживаемый кластер, внутри которого выделены каталоги `custom-resources/` и `sync-code/`.
- **`components/`** — библиотека базовых деклараций и шаблонов (системные сервисы, CNI/NetworkPolicy, мониторинг, ingress, прикладные сервисы), совместно используемых парком кластеров.
- **`custom-resources/`** — кластерные переопределения, оверлеи Kustomize, ConfigMap с локальными параметрами (IP-диапазоны, имена ЦОД, реплики) и зашифрованные секреты конкретного кластера.
- **`sync-code/`** — декларации манифестов `Kustomization` (CRD Flux), связывающие кластер с базовыми компонентами и оверлеями в `custom-resources/`. Точка входа реконсиляции для контроллеров Flux.
- **Сквозной нейминг (Uniform Naming Convention)** — строгое правило соответствия имен: имя директории пространства имен, имя подключающего ресурса `Kustomization` в `sync-code/` и имя целевого ресурса (например, `HelmRelease`) совпадают.
- **Заглушка невалидного ключа (Fail-Safe Stub)** — паттерн защиты шаблонов безопасности (например, NetworkPolicy), при котором в базовый манифест закладывается заведомо некорректное значение (например, `namespace: "__PLACEHOLDER_INVALID_NAMESPACE__"`), блокирующее случайное применение сырого шаблона без кластерного оверлея.
- **Reconciliation Loop (Цикл сверки)** — непрерывный процесс сравнения объявленного в Git состояния (Desired State) с фактическим состоянием объектов в etcd Kubernetes-кластера (Actual State) с автоматическим исправлением расхождений (Drift Correction).
- **Blast Radius (Радиус поражения)** — масштаб потенциального сбоя при внесении некорректных изменений в базовый компонент, затрагивающий зависимые кластеры.

---

## 2. Базовые концепции и архитектура

### 2.1 Исходные предпосылки и проблематика парка кластеров

Исходное состояние инфраструктуры до перехода на монорепозиторий:
- Около 20 автономных Kubernetes-кластеров (bare-metal серверы в основных и резервных корпоративных ЦОД, тестовые и стейджинг-зоны).
- Архитектура «один кластер — один Git-репозиторий».
- Использование Flux v1, достигшего статуса End-Of-Life (ноябрь 2022).
- Шаблонизация через Git-субмодули поверх общих модулей Terraform: высокое зацепление, рассинхронизация коммитов субмодулей между репозиториями, невозможность централизованного аудита.
- Отсутствие единых корпоративных стандартов сетевой изоляции (NetworkPolicy) и ролевого доступа (RBAC).
- Требования регуляторов и аудита ISO 27001 / Disaster Recovery: обязательное детерминированное развертывание чистых bare-metal кластеров с нуля за фиксированное время.

**Ключевые требования к целевому дизайну:**
1. Единый источник правды (SSoT) для всех кластеров без дублирования манифестов.
2. Прозрачное версионирование компонентов и поэтапный ввод изменений в эксплуатацию.
3. Низкий порог входа для инженеров платформы и системных администраторов.
4. Отсутствие внешних облачных зависимостей: работа в изолированных контурах (on-premise / bare-metal).

### 2.2 Выбор между Flux v2 и Argo CD

При проектировании рассматривался переход на Argo CD. Выбор был сделан в пользу Flux v2 по следующим техническим и организационным причинам:
- **Отсутствие единой точки отказа (No Single Point of Failure):** Flux v2 функционирует по pull-модели непосредственно внутри каждого кластера (`pull-per-cluster`). Кластеры в изолированных сегментах сети не требуют открытых входящих портов от центрального сервера управления.
- **Сохранение существующего CI/CD конвейера:** разработчики используют корпоративный CI/CD для доставки артефактов; платформенная команда администрирует кластерную инфраструктуру через GitOps без необходимости навязывать командам интерфейс стороннего UI.
- **Unix-way архитектура GitOps Toolkit:** возможность выборочного развертывания только необходимых контроллеров (`source-controller`, `kustomize-controller`, `helm-controller`) без избыточных сервисов.

Подробное сопоставление контроллеров и манифестов приведено в [сравнении ArgoCD и Flux](../argo_vs_flux_manifests.md).

### 2.3 Архитектурные отличия Flux v1 и Flux v2

| Характеристика | Flux v1 (Legacy, EOL) | Flux v2 (GitOps Toolkit) |
| :--- | :--- | :--- |
| **Архитектура** | Монолитный демон (`fluxd`), совмещавший Git, генерацию манифестов и применение | Набор специализированных контроллеров Kubernetes (Source, Kustomize, Helm и др.) |
| **Работа с Git** | Рекурсивный `git clone` с поддержкой git submodules внутри Pod | Легковесный `source-controller`, генерирующий сжатые gzip-артефакты в памяти/хранилище |
| **Декларативность** | Настройка через аргументы командной строки и аннотации манифестов | Полноценные Custom Resource Definitions (`GitRepository`, `Kustomization`, `HelmRelease`) |
| **Управление зависимостями** | Отсутствовало (порядок применения определялся алфавитным порядком файлов) | Декларативное дерево зависимостей через директиву `spec.dependsOn` |
| **Поддержка Kustomize** | Встроенная базовая версия, ограниченная функциональность | Нативная поддержка современных спецификаций Kustomize v5 с валидацией схем |

### 2.4 Анализ первой неудавшейся структуры monorepo

При первой попытке миграции была скопирована стандартная референсная структура сообщества:
```text
repo/
├── clusters/
├── apps/
└── infrastructure/
```

**Причины неудачи на парке из ~20 кластеров:**
- **Массовый Copy-Paste:** инженеры копировали директории соседних кластеров целиком. Манифесты мониторинга и инфраструктурных операторов насчитывали тысячи строк. В результате в кластерах возникали несовместимые лимиты ресурсов, неверные адреса внутренних DNS и порты.
- **Неконтролируемое обновление CRD:** при использовании Helm-чартов операторов (Prometheus Operator, Cert-Manager) `helm-controller` не обновлял существующие CRD при апгрейде чарта (штатное поведение механизма Helm для предотвращения потери данных в etcd). Без разделения CRD на отдельный шаг синхронизация ломалась.
- **Когнитивная перегрузка:** команда платформы тратила часы на поиск различий между кластерами из-за запутанных взаимных ссылок между `apps/` и `infrastructure/`.

### 2.5 Целевая архитектура: Двухдиректориальный Monorepo

Итоговая архитектура устраняет дублирование за счет жесткого разделения на глобальные компоненты (`components/`) и кластерные инстансы (`clusters/`):

```text
flux-monorepo/
├── .sops.yaml                             # Правила шифрования секретов age для ЦОД
├── clusters/                              # Конфигурации целевых кластеров
│   ├── dc1-prod-01/                       # Продакшен-кластер в ЦОД-1
│   │   ├── custom-resources/              # Оверлеи Kustomize и кластерные переменные
│   │   │   ├── infrastructure-crds/
│   │   │   ├── network-system/
│   │   │   └── monitoring/
│   │   └── sync-code/                     # Kustomization CRD (точки входа Flux)
│   │       ├── infrastructure-crds.yaml
│   │       ├── network-system.yaml
│   │       └── monitoring.yaml
│   ├── dc2-prod-02/                       # Продакшен-кластер в ЦОД-2
│   └── dc1-stage-01/                      # Стейджинг-кластер
└── components/                            # Единая библиотека базовых шаблонов
    ├── base-crds/                         # Шаблоны CRD (Prometheus, Cert-Manager)
    ├── flux-system/                       # Манифесты установки Flux по версиям
    │   ├── v2.9.x-prod/
    │   └── v2.9.x-stage/
    ├── network-policies/                  # Базовый каркас сетевой безопасности
    ├── monitoring/                        # Стек мониторинга (Prometheus + Grafana)
    └── ingress-nginx/                     # Ingress-контроллер bare-metal
```

**Фундаментальные принципы архитектуры:**
1. **Плоская иерархия по пространствам имен:** имя поддиректории в `custom-resources/` строго соответствует целевому Namespace и имени файла в `sync-code/`.
2. **Связывание через относительные пути:** `custom-resources/<ns>/kustomization.yaml` ссылается на базовый шаблон `../../../components/<component>/` и накладывает только локальные диффы (patches, configMapGenerator).
3. **Изоляция контуров:** тестовые (dev/stage) и боевые (prod) окружения никогда не совмещаются на одном физическом кластере. Кластер целиком принадлежит определенному контуру.
4. **Ветка как селектор среды:** объект `GitRepository` кластера может ссылаться на долгоживущую ветку (`main`, `staging`) или на сервисную ветку обслуживания (`maintenance/upgrade-monitoring`) для безопасного тестирования изменений на выделенном кластере.

---

## 3. Практические сценарии и конфигурация

### 3.1 Сценарий 1: Декларативный Bootstrap и версионирование Flux на Bare-Metal

Установка Flux в изолированных кластерах дата-центра выполняется через генерацию манифестов с последующим применением через корпоративный IaC (Terraform/OpenTofu или локальный оркестратор). Это исключает необходимость предоставления утилите `flux` прямого сетевого доступа к кластерам из внешней сети.

#### Шаг 1: Экспорт манифестов Flux нужной версии в monorepo
Манифесты генерируются и фиксируются в репозитории:

```bash
flux install \
  --version=v2.9.4 \
  --components=source-controller,kustomize-controller,helm-controller \
  --export > components/flux-system/v2.9.x-prod/gotk-components.yaml
```

#### Шаг 2: Создание базового GitRepository в кластере
Каждый кластер настраивается на чтение монорепозитория через локальный SSH-ключ (`deploy-key`), обладающий правами read-only:

```yaml
# clusters/dc1-prod-01/sync-code/flux-system.yaml
apiVersion: source.toolkit.fluxcd.io/v1
kind: GitRepository
metadata:
  name: flux-monorepo
  namespace: flux-system
spec:
  interval: 5m
  url: ssh://git@git.internal.corp/infrastructure/flux-monorepo.git
  ref:
    branch: main
  secretRef:
    name: flux-system-git-deploy-key
  timeout: 60s
```

#### Шаг 3: Верификация установки в кластере
После применения стартовых манифестов выполняется диагностика:

```bash
flux check
# ► checking prerequisites
# ✔ Kubernetes 1.35.3 >=1.34.0-0
# ► checking controllers
# ✔ source-controller: deployment ready
# ✔ kustomize-controller: deployment ready
# ✔ helm-controller: deployment ready
# ✔ all components are healthy

flux get sources git -n flux-system
# → NAME           REVISION     SUSPENDED  READY  MESSAGE
# → flux-monorepo  main@sha1:a1b2c3d False      True   stored artifact for revision 'main@sha1:a1b2c3d'
```

---

### 3.2 Сценарий 2: Подключение инфраструктурного компонента и разрешение проблем CRD

Классическая проблема при обновлении Prometheus Operator в bare-metal парке: Helm не обновляет CRD при релизах чарта. В архитектуре monorepo эта задача решается жестким разделением на два независимых шага с директивой `spec.dependsOn`.

#### Шаг 1: Декларация CRD-компонента в sync-code
```yaml
# clusters/dc1-prod-01/sync-code/monitoring-crds.yaml
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: monitoring-crds
  namespace: flux-system
spec:
  interval: 1h
  prune: false                        # Защита от случайного удаления CRD при переименованиях
  sourceRef:
    kind: GitRepository
    name: flux-monorepo
  path: ./components/monitoring/crds
  timeout: 3m
```

#### Шаг 2: Декларация основного оператора с явной зависимостью
```yaml
# clusters/dc1-prod-01/sync-code/monitoring.yaml
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: monitoring
  namespace: flux-system
spec:
  interval: 10m
  retryInterval: 2m
  prune: true
  sourceRef:
    kind: GitRepository
    name: flux-monorepo
  path: ./clusters/dc1-prod-01/custom-resources/monitoring
  dependsOn:
    - name: monitoring-crds
  timeout: 5m
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
apiVersion: helm.toolkit.fluxcd.io/v2
kind: HelmRelease
metadata:
  name: monitoring
  namespace: monitoring
spec:
  values:
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

В bare-metal кластерах отсутствуют облачные сервисы KMS (AWS KMS, GCP KMS). Хранение паролей баз данных, сертификатов и токенов реализуется через связку **SOPS + age** с нативной поддержкой со стороны `kustomize-controller`.

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
Приватный ключ генерируется администратором и передается в кластер при инициализации узлов:

```bash
# Генерация ключа администратором (выполняется один раз на кластер)
age-keygen -o dc1-prod-01.age.key
# → Public key: age1ql3z7hjy54pw3hyww5ayyfg7zqgvc7w3j2elw8zmrj2kg5sfn9aqmcac8p

# Импорт ключа в пространство имен flux-system
kubectl create secret generic sops-age \
  --namespace=flux-system \
  --from-file=age.agekey=dc1-prod-01.age.key
# → secret/sops-age created
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

#### Шаг 4: Настройка Kustomization на автоматическую расшифровку
```yaml
# clusters/dc1-prod-01/sync-code/monitoring.yaml
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: monitoring
  namespace: flux-system
spec:
  interval: 10m
  sourceRef:
    kind: GitRepository
    name: flux-monorepo
  path: ./clusters/dc1-prod-01/custom-resources/monitoring
  prune: true
  decryption:
    provider: sops
    secretRef:
      name: sops-age
```

`kustomize-controller` расшифровывает файл в оперативной памяти непосредственно перед отправкой манифестов в `kube-apiserver`. В репозитории хранятся только зашифрованные данные. Детальное описание ротации ключей и параметров SOPS приведено в [шифровании секретов в GitOps](../secrets_encryption.md).

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

Сводная таблица повседневных команд SRE и системных администраторов при эксплуатации парка Flux:

| Задача | Команда | Назначение / Ожидаемый результат |
| :--- | :--- | :--- |
| **Проверка статуса кластера** | `flux check` | Полная диагностика контроллеров и соответствия версии Kubernetes |
| **Список всех Kustomization** | `flux get kustomizations -A` | Вывод состояния всех точек синхронизации, текущих ревизий коммитов и статусов Ready |
| **Принудительный pull Git** | `flux reconcile source git flux-monorepo -n flux-system` | Запрос к Git без ожидания истечения таймера `spec.interval` |
| **Принудительная синхронизация** | `flux reconcile kustomization monitoring -n flux-system --with-source` | Немедленная сборка и наложение ресурсов вместе с обновлением Git |
| **Приостановка синхронизации** | `flux suspend kustomization monitoring -n flux-system` | Заморозка реконсиляции (устанавливает `spec.suspend: true`) при аварийных работах |
| **Возобновление синхронизации** | `flux resume kustomization monitoring -n flux-system` | Разморозка и приведение кластера к состоянию в Git |
| **Проверка расхождений (Diff)** | `flux diff kustomization monitoring -n flux-system --path ./clusters/dc1-prod-01/custom-resources/monitoring` | Сравнение локального кода или Git с реальным состоянием объектов в API |
| **Трассировка событий** | `flux events --for Kustomization/monitoring -n flux-system` | Вывод хронологии событий генерации, валидации и применения |

### Примеры выполнения типовых операций

#### Форсированное применение изменений после коммита
```bash
flux reconcile source git flux-monorepo -n flux-system
# ► annotating GitRepository flux-monorepo in flux-system namespace
# ✔ GitRepository reconciled successfully
# ◎ GitRepository flux-monorepo is up to date with revision 'main@sha1:9e4f1a2'

flux reconcile kustomization monitoring -n flux-system
# ► annotating Kustomization monitoring in flux-system namespace
# ✔ Kustomization reconciled successfully
# ◎ Kustomization monitoring is ready: Applied revision: main@sha1:9e4f1a2
```

#### Приостановка реконсиляции при проведении планового обслуживания (Maintenance Window)
```bash
flux suspend kustomization monitoring -n flux-system
# ► annotating Kustomization monitoring in flux-system namespace
# ✔ Kustomization suspended successfully

flux get kustomizations -n flux-system
# → NAME        REVISION              SUSPENDED  READY  MESSAGE
# → monitoring  main@sha1:9e4f1a2      True       True   Applied revision: main@sha1:9e4f1a2
```

---

## 5. Диагностика и устранение неполадок

| Проблема / Симптом | Первопричина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **CRD не обновляются при апгрейде HelmRelease** | Дизайн Helm: `helm upgrade` не накатывает новые CRD из чарта во избежание порчи схемы в etcd | `kubectl get crd <name> -o yaml` (версия устарела); ошибки `validation error: unknown field` в логах | Вынести CRD в отдельный `Kustomization` в `components/base-crds/` и связать через `dependsOn` |
| **Ошибка невалидного Namespace (`RFC 1123 label`)** | Сработала заглушка `__PLACEHOLDER_INVALID_NAMESPACE__` в базовом NetworkPolicy | `flux get kustomization network-system` → `Error: a lowercase RFC 1123 label must consist...` | В `custom-resources/<ns>/kustomization.yaml` добавить патч, заменяющий `/metadata/namespace` на валидное имя |
| **`failed to decrypt: no matching age key found`** | Отсутствует ключ расшифровки SOPS или файл зашифрован ключом другого кластера | `kubectl describe kustomization <name> -n flux-system` | Проверить наличие `Secret` `sops-age` в `flux-system` и соответствие открытого ключа правилам `.sops.yaml` |
| **Циклическая зависимость (Cyclic Dependency)** | Взаимные ссылки в `dependsOn` между объектами `Kustomization` | `flux get kustomizations` показывает статус `DependencyCycleDetected` | Построить направленный ациклический граф (DAG); развязать циклические ссылки |
| **Таймаут синхронизации (apiserver timeout / throttling)** | Одновременный запуск реконсиляции десятков тяжелых компонентов перегружает control-plane | Высокий CPU на мастерах; в логах контроллера: `context deadline exceeded` | Разнести `spec.interval` по времени; ограничить число воркеров флагом `--concurrent` у контроллеров |
| **Случайное удаление ресурсов (Pruning)** | Опечатка в пути оверлея или имени namespace при `spec.prune: true` | Flux удаляет рабочие Pods/Deployments: статус `deleted resource ...` | Временно выставить `spec.prune: false`; восстановить манифесты; настроить CI-валидацию |

### Пример отладки сбоя реконсиляции Kustomize
```bash
# 1. Быстрый просмотр статуса
flux get kustomizations -n flux-system
# → NAME        REVISION              SUSPENDED  READY  MESSAGE
# → monitoring  main@sha1:b4c5d6e      False      False  kustomize build failed: missing file cluster-variables.yaml

# 2. Получение расширенной информации из Kubernetes Events
kubectl describe kustomization monitoring -n flux-system
# → Normal   ReconcileFailed  2m   kustomize-controller  kustomize build failed: accumulating resources: accumulation err='accumulating resources from 'custom-resources/monitoring': missing file'

# 3. Анализ логов соответствующего контроллера
kubectl logs -n flux-system deploy/kustomize-controller --tail=50
```

---

## 6. Рекомендации и Best Practices (SRE / DevOps / Sysadmin)

### 6.1 Архитектурные стандарты
1. **Строго две директории верхнего уровня:** `clusters/` (экземпляры) и `components/` (шаблоны). Не создавать смешанные каталоги `apps/`, `infra/` на верхнем уровне monorepo во избежание лавинообразного копирования кода.
2. **Изоляция окружений на физическом уровне:** продакшен и стейджинг размещаются в раздельных кластерах. Запрещено использовать общие физические worker-узлы для prod и dev с разделением только по Namespace.
3. **Единый сквозной нейминг:** если компонент называется `monitoring`, то директория в `components/` называется `monitoring`, подкаталоги в `clusters/<cluster>/` — `monitoring/`, а ресурс в `sync-code/` — `monitoring.yaml`.

### 6.2 Надежность и отказоустойчивость (SRE)
1. **Канареечное развертывание платформенных компонентов:** перед обновлением версии базового компонента (например, Ingress или CNI) в ветке `main` переключите один стейджинг-кластер на сервисную ветку через параметр `spec.ref.branch` в его `GitRepository`. После стабилизации изменения сливаются в `main`.
2. **Защита от каскадного удаления (Prune Safety):** критически важные кластерные ресурсы (CRD, PersistentVolumeClaim, внешние базы данных) должны сопровождаться аннотацией:
   ```yaml
   metadata:
     annotations:
       kustomize.toolkit.fluxcd.io/prune: disabled
   ```
3. **Оптимизация опроса Git:** при наличии 20 кластеров одновременный опрос Git-сервера каждые 60 секунд создает пиковую нагрузку в 20 одновременных `git fetch`. Рекомендуется установить базовый интервал `spec.interval: 10m` или `15m`, а оперативную доставку коммитов настроить через локальные webhook-уведомления через `notification-controller` (`Receiver`).

### 6.3 Эксплуатация и безопасность (Sysadmin)
1. **Минимальные привилегии ServiceAccount (Impersonation):** не позволять `kustomize-controller` применять ресурсы под дефолтным суперпользователем `cluster-admin`. Назначать в `Kustomization` выделенный `ServiceAccount` через `spec.serviceAccountName` с ограниченными RBAC-правами в рамках конкретного namespace.
2. **Локальное шифрование SOPS + age:** полностью отказаться от хранения незашифрованных секретов в Git. Использовать раздельные ключи age для каждой локации/ЦОД, чтобы компрометация одного узла не ставила под угрозу весь парк.
3. **Ограничение concurrency на слабых узлах control-plane:** если узлы управления кластера имеют ограниченные ресурсы CPU, настройте в Deployment контроллеров флаг `--concurrent=2` (по умолчанию 4), чтобы ограничить параллельные сборки Kustomize.

---

## 7. Дополнительная информация

**Связанные документы в базе знаний:**
- [Flux — обзор и ключевые концепции](../flux.md) — детальный справочник по контроллерам, CRD, disaster recovery и bootstrap.
- [Мульти-кластерные паттерны в GitOps](./multi_cluster_patterns.md) — топологии парков кластеров (Hub-and-Spoke vs Pull-per-cluster).
- [Шифрование секретов в GitOps](../secrets_encryption.md) — руководство по SOPS, age, ротации ключей и External Secrets Operator.
- [Сравнение манифестов ArgoCD и Flux](../argo_vs_flux_manifests.md) — архитектурные различия и спецификации манифестов.
- [NetworkPolicy: CI/CD и GitOps](../../Kubernetes/Networking/Network/NetworkPolicy/gitops_ci_cd.md) — конвейеры автоматической валидации сетевых политик.

**Официальные источники и спецификации:**
- [Официальная документация Flux CD](https://fluxcd.io/flux/) — руководства по GitOps Toolkit, Kustomize Controller и Helm Controller.
- [Спецификация Kustomize v5](https://kubectl.docs.kubernetes.io/) — генераторы, патчи и декларативные трансформации манифестов.
- [Спецификация шифрования age](https://age-encryption.org/) — простой, современный и безопасный инструмент шифрования файлов.
- [Репозиторий проекта SOPS (CNCF Sandbox)](https://github.com/getsops/sops) — шифрование конфигураций и интеграция с age/KMS.
