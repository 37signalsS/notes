# Crossplane: Обзор

> Актуально на август 2026 года. Crossplane — проект CNCF уровня Graduated, текущая стабильная ветка — v2.x (последний релиз v2.4, август 2026).

## Определения

**Crossplane** — это решение класса "инфраструктура как код" (IaC) с открытым исходным кодом, распространяемое под лицензией Apache 2.0, которое расширяет API Kubernetes для управления облачной и прикладной инфраструктурой от различных провайдеров. Он устанавливается в кластер Kubernetes и превращает его в универсальную платформу управления (Control Plane), позволяя определять и настраивать облачные ресурсы (базы данных, сети, виртуальные машины, объектные хранилища) и нативные объекты Kubernetes с помощью декларативных YAML-манифестов.

Ключевое отличие от классических инструментов IaC (Terraform, OpenTofu): Crossplane не выполняет инфраструктуру "по требованию" (push-модель `plan/apply`), а работает по модели непрерывной сверки (pull-модель). Контроллеры Crossplane постоянно следят за тем, чтобы реальное состояние ресурсов в облаке соответствовало желаемому состоянию, описанному в объектах Kubernetes, и автоматически устраняют дрейф конфигурации. Таким образом Kubernetes становится не просто "клиентом" облака, а его декларативным интерфейсом управления.

**Control Plane (платформа управления)** — в терминологии Crossplane это кластер Kubernetes, в котором запущен Crossplane и который предоставляет единый набор декларативных API для оркестрации ресурсов независимо от того, где они физически находятся (в облаке, в другом кластере, on-prem).

## Базовые концепции

### Ключевые возможности

* **Унифицированное управление:** Использование знакомого синтаксиса и инструментов Kubernetes (`kubectl`, GitOps) для управления приложениями и инфраструктурой в едином цикле. Инженеру не нужно переключаться между HCL, консолями облаков и манифестами — всё описывается одними и теми же ресурсами.
* **Представление облачных сервисов как CRD:** Автоматическое создание Custom Resource Definitions (CRD) для облачных сервисов, делая их нативными ресурсами кластера. Например, после установки провайдера появляется возможность создавать объект `kind: Bucket`, как если бы это был встроенный ресурс Kubernetes.
* **Непрерывная сверка (Reconciliation):** Контроллеры Crossplane постоянно следят за соответствием реального состояния ресурсов в облаке их описанию в Kubernetes, автоматически устраняя дрейф конфигурации (configuration drift). Это даёт эффект self-healing: ручное изменение в консоли облака будет отменено при следующей итерации сверки.
* **Интеграция с GitOps:** Полная совместимость с Argo CD и Flux для реализации модели "Git как единственный источник правды" для инфраструктуры. Манифесты хранятся в Git, GitOps-инструмент доставляет их в кластер, а Crossplane приводит облако к описанному состоянию. См. [Интеграция с GitOps](./gitops_integration.md).
* **Политики управления:** Использование RBAC и Open Policy Agent (OPA/Kyverno) для гранулярного контроля доступа к облачным ресурсам на уровне Kubernetes API. Platform-команды могут запрещать создание определённых ресурсов или ограничивать допустимые значения параметров.
* **Композиция без написания контроллеров:** Crossplane позволяет строить собственные API платформы (внутренние платформы разработчика, IDP) без написания Go-кода контроллеров — через декларативные Composition Functions на YAML, KCL, Python или Go.

### Основные компоненты

* **Crossplane Core:** Набор контроллеров, отвечающих за жизненный цикл ресурсов, композицию, управление пакетами (Providers, Functions, Configurations) и RBAC. Состоит из основного контроллера (`crossplane`) и контроллера управления ролями (`crossplane-rbac-manager`).
* **Providers (провайдеры):** Пакеты (`kind: Provider`), которые "обучают" Crossplane взаимодействию с API конкретного облака или системы (AWS, Azure, GCP, Yandex Cloud, Kubernetes, OCI, Cloudflare и др.). Каждый провайдер регистрирует свои CRD (Managed Resources) и контроллеры для сверки.
* **Provider Families:** Современная архитектура провайдеров (введена в v1.x, стандарт в v2.x), разделяющая огромные монолитные провайдеры на более мелкие пакеты по сервисам (например, `provider-family-aws` + `provider-aws-s3`, `provider-aws-rds`) для снижения нагрузки на API-сервер Kubernetes. Монолитный `provider-aws` устанавливает более 900 CRD, что дестабилизирует control plane; семейства позволяют ставить только нужные сервисы.
* **ProviderConfig:** Конфигурация (`kind: ProviderConfig`), содержащая учетные данные (ссылка на Kubernetes Secret) и настройки подключения провайдера к облачному API (регион, endpoint, профиль). MR ссылается на ProviderConfig через `spec.providerConfigRef`.
* **Managed Resources (MR):** Низкоуровневые ресурсы, представляющие конкретный объект в облаке (например, `Bucket` в S3, `Instance` в Yandex Compute Cloud). Именно они управляются непосредственно провайдер-контроллером.
* **Composition Engine (движок композиции):** Подсистема Crossplane, которая по заданному пайплайну функций (Composition Functions) преобразует высокоуровневый запрос пользователя в набор MR. Заменяет необходимость писать собственные контроллеры.
* **Package Manager:** Подсистема установки и обновления пакетов (Providers, Functions, Configurations) из OCI-реестров. В v2.x требует всегда указывать полностью квалифицированный URL образа (`registry.example.com/repo/package:tag`).
* **Functions (функции композиции):** Пакеты (`kind: Function`), реализующие логику формирования инфраструктуры. Выполняются как gRPC-сервисы (отдельные поды) и могут быть написаны на YAML, KCL, Python, Go (см. ниже).

### Уровни абстракции и композиция

Crossplane позволяет строить собственные внутренние платформы разработчика (IDP) через систему композиции, скрывая сложность облака за простыми API:

1. **Composite Resource Definition (XRD):** Описание схемы вашего собственного высокоуровневого API (например, абстрактный ресурс `XPostgreSQL`). Задаёт `group`, `kind`, версии (`served`/`referenceable`) и OpenAPI-схему входных параметров. XRD может одновременно объявлять и Composition-Claim (через `claimNames`), давая пользователям namespace-scoped интерфейс.
2. **Composition:** Реализация XRD, определяющая, из каких Managed Resources (MR) или других ресурсов состоит ваш абстрактный ресурс и как они связаны. В v2.x Composition использует режим `mode: Pipeline` — упорядоченный набор шагов, каждый из которых вызывает Composition Function.
3. **Composite Resource (XR):** Экземпляр ресурса, созданный платформенной командой на базе XRD. В v1.x XR был только cluster-scoped; в v2.x появились **namespaced XR** для изоляции между командами.
4. **Composite Resource Claim (XRC или Claim):** Запрос на создание ресурса пользователем из конкретного namespace (Namespace-scoped), аналогично `PersistentVolumeClaim`. При создании Claim Crossplane автоматически создаёт соответствующий XR (через `claimNames` в XRD), а XR разворачивается в MR через Composition.

**Composition Functions (функции композиции).** В v2.x это основной механизм формирования инфраструктуры. Функции — это gRPC-сервисы, запускаемые Crossplane как поды в `crossplane-system`. Поддерживаемые языки:
* **YAML** — через `function-auto-ready` и `function-kro` (YAML+CEL, анонсирован март 2026);
* **KCL** — декларативный конфигурационный язык (`function-kcl`);
* **Python** — `function-python` (позволяет циклы, условия, внешние запросы);
* **Go** — `function-go` (максимальная гибкость, компилируется в бинарный образ).

Нативная patch-and-transform композиция (статические шаблоны) **удалена в v2** (устарела ещё в v1.17) и заменена функциями.

**Managed Resource Definitions (MRDs).** Возможность избирательной активации ресурсов провайдера: платформенная команда описывает, какие именно MR должен предоставлять провайдер, что дополнительно снижает нагрузку на API-сервер по сравнению с Family-подходом.

### Архитектура и поток данных

Интеграция Crossplane в GitOps-пайплайн обеспечивает автоматизацию полного цикла "Git → облако":

```text
┌─────────────┐     ┌─────────────┐     ┌──────────────────┐     ┌─────────────┐
│     Git     │────▶│   Argo CD   │────▶│     Crossplane    │────▶│  Облачный   │
│  Repository │     │  (Sync)     │     │  (Reconcile)      │     │ Провайдер   │
└─────────────┘     └─────────────┘     └──────────────────┘     └─────────────┘
                                                   │                       │
                                                   ▼                       ▼
                                            etcd (желаемое)        Облако (реальное)
```

1. **Применение манифеста:** Пользователь фиксирует YAML в Git, GitOps-инструмент (Argo CD/Flux) синхронизирует его в кластер Kubernetes, записывая объект в etcd.
2. **Обработка Core:** Crossplane Core видит новый ресурс (MR, XR или Claim) через механизм watch Kubernetes API и добавляет его в очередь сверки.
3. **Композиция:** Если это Claim — Crossplane создаёт XR; если XR — движок композиции по пайплайну Functions разворачивает его в набор Managed Resources.
4. **Взаимодействие с провайдером:** Соответствующий Provider-контроллер берёт MR, читает `providerConfigRef`, получает учётные данные из Secret и вызывает API облака (Create/Update/Delete).
5. **Создание ресурса:** Облачный сервис создаётся или обновляется; Crossplane записывает идентификатор облачного объекта в аннотацию `crossplane.io/external-name`.
6. **Обратная связь:** Crossplane обновляет поле `status` ресурса (условия `Ready`, `Synced`, connection details). Если в облаке произойдут изменения вручную, следующая итерация сверки вернёт их к желаемому состоянию.

### Принцип непрерывной сверки (Reconciliation) — подробно

Каждый контроллер Crossplane реализует классический Kubernetes reconcile-цикл для своих ресурсов. Для Managed Resource типовой цикл:

* **Observe (наблюдение):** провайдер опрашивает облако, чтобы понять, существует ли ресурс и в каком он состоянии. Если ресурс найден вне Crossplane, выполняется `LateInitialization` — заполнение `spec` значениями, заданными облаком (например, автосгенерированные поля).
* **Create / Update:** если ресурса нет — создаётся; если отличается от `spec` — обновляется.
* **Delete:** при удалении объекта из Kubernetes облачный ресурс удаляется (поведение регулируется `managementPolicies` и `deletionPolicy`).
* **PublishConnectionDetails:** запись чувствительных выходных данных (эндпоинты, пароли) в Kubernetes Secret для использования приложениями.

Частота сверки управляется:
* **poll interval** — как часто провайдер опрашивает облако (по умолчанию ~1 минута, настраивается через `DeploymentRuntimeConfig` аргументом `--poll`);
* **max reconcile rate** — ограничение числа одновременных сверок (`--max-reconcile-rate`), защищает от превышения квот API облака.

Важно: сверка **поллинговая**, а не событийная. Задержка обнаружения дрейфа равна примерно poll interval. Для ускорения реакции уменьшают poll interval (ценилось нагрузкой на API облака).

**managementPolicies** — список операций, которые Crossplane вправе выполнять с ресурсом: `Observe`, `Create`, `Update`, `Delete`, `LateInitialize`. Режим `ObserveOnly` (только наблюдение) позволяет импортировать существующую инфраструктуру, не управляя ей.

## Передовые возможности v2.x (актуально на 2026 год)

Crossplane v2.0 выпущен 12 августа 2025 года и расширил модель за пределы инфраструкты: v2 позволяет управлять приложениями как объектами первого класса (Deployment, Service, CloudNativePG Cluster), строя единый API платформы.

| Функция | Описание | Статус в v2 |
| :--- | :--- | :--- |
| **Namespaced Composite/Managed Resources** | Возможность создавать XR и MR внутри пространств имён для изоляции команд и применения лимитов. Cluster-scoped MR/XR объявлены устаревшими (legacy), будут удалены в будущем. | Стабильно (v2) |
| **Composition Functions** | Переход от статических шаблонов к gRPC-функциям на YAML, KCL, Python, Go (через `function-kro`, `function-kcl`, `function-python`, `function-go`). Позволяет циклы, условия, внешние запросы. | Стабильно (v2) |
| **Managed Resource Definitions (MRDs)** | Избирательная активация только нужных ресурсов провайдера, снижение нагрузки на API-сервер сверх Family-подхода. | Стабильно (v2) |
| **Operations** | Запуск операционных задач через пайплайны функций: `Operation` (разово), `CronOperation` (по расписанию), `WatchOperation` (при изменении ресурсов). Примеры: мониторинг сертификатов, плановое обслуживание. | Alpha (v2) |
| **Compose any resource** | XR может компоновать не только MR, но и нативные ресурсы K8s (Deployment, Service) и сторонние CRD (например, CloudNativePG). | Стабильно (v2) |
| **API-first инфраструктура для AI-агентов** | v2 позиционируется как machine-readable control plane, предоставляющий машиночитаемый декларативный API для автоматизации инфраструктуры AI-агентами (API-centric operations). | Концепция (v2) |
| **Provider Families** | Дробление монолитных провайдеров на сервисные пакеты для снижения числа CRD. | Стабильно (v1.x→v2) |

**Критическиеbreaking-изменения при переходе на v2** (важно для обновления и написания манифестов):
* Удалена нативная patch-and-transform композиция (заменена функциями).
* Удалён тип `ControllerConfig` — заменён на `DeploymentRuntimeConfig` для тюнинга poll interval/reconcile rate.
* Удалена поддержка external secret stores (функция оставалась в alpha и не поддерживалась).
* Удалена нативная поддержка connection details у составных ресурсов (XR); для MR — сохранена (воссоздаётся композицией собственного Secret).
* Удалён default registry для пакетов: теперь всегда требуется полностью квалифицированный URL образа (`registry/repo/package:tag`).

Проверить использование устаревших функций перед обновлением: `crossplane beta upgrade check` (с CLI v1.20) против v1.x control plane.

## Безопасность и наблюдаемость

### Безопасность

* **RBAC Manager:** Компонент Crossplane (`crossplane-rbac-manager`), который автоматически создаёт и управляет ролями Kubernetes (`ClusterRole`/`Role`) для доступа к CRD, регистрируемым провайдерами, и связывает их с сервисными аккаунтами провайдеров. При отключении RBAC Manager права на создание Claim/XR нужно выдавать вручную.
* **Secrets Management:** Интеграция с **External Secrets Operator (ESO)** и HashiCorp Vault для безопасной доставчи учетных данных провайдерам. Рекомендуется никогда не коммитить сырые ключи в Git; в GitOps-сценариях манифесты `ProviderConfig` шифруются через SOPS. См. [Интеграция с GitOps](./gitops_integration.md).
* **Composition-level RBAC:** Возможность ограничивать, какие команды/namespace могут использовать конкретные `Compositions` и XRD, через стандартный RBAC Kubernetes и политики OPA/Kyverno (валидация параметров до применения).
* **Полномочия провайдеров:** провайдер-контроллер действует от имени ServiceAccount с правами, выданными RBAC Manager; принцип наименьших привилегий применяется через ограничение устанавливаемых MRD/Family.

### Наблюдаемость

* **Crossplane CLI:** Инструмент `crossplane` для отладки ресурсов, проверки пакетов и визуализации графа композиции:
  * `crossplane beta trace <xr>` — текстовая визуализация дерева композиции (XR → MR);
  * `crossplane render <xr.yaml> <composition.yaml> <functions...>` — локальный рендеринг без обращения к кластеру;
  * `crossplane beta validate` — проверка манифестов на соответствие схемам CRD;
  * `crossplane xpkg install provider <url>` — установка провайдера из OCI.
* **Metrics:** Экспорт метрик в формате Prometheus о времени сверки, ошибках API провайдеров, количестве ресурсов и их статусе (`crossplane_*`). В v2 расширены метрики здоровья control plane.
* **Events:** Использование стандартных Kubernetes Events для уведомления о критических изменениях или сбоях (например, `Warning` при ошибке создания MR).
* **Логи:** контроллеры пишут структурированные логи; диагностика провайдера — `kubectl -n crossplane-system logs -l pkg.crossplane.io/provider=<имя>`.

## Статус проекта

* **CNCF Status:** Graduated (объявлено 6 ноября 2025 года, [анонс CNCF](https://www.cncf.io/announcements/2025/11/06/cloud-native-computing-foundation-announces-graduation-of-crossplane/)). Более 3 000 контрибьюторов из 450+ организаций.
* **Текущая версия:** v2.4 (август 2026). График релизов — примерно раз в 3 месяца (v2.3 — май 2026, v2.4 — август 2026, v2.5 ожидается ноябрь 2026). Ветка v1.20 (последняя v1.x) уходит в EOL при выходе v2.5.
* **Лицензия:** Apache 2.0.

## Практические сценарии

Ниже — базовый сквозной сценарий работы с Crossplane на уровне обзора. Подробные инструкции для конкретных провайдеров и GitOps-доставки вынесены в профильные файлы (см. конец раздела).

### Предварительные требования

* Кластер Kubernetes **v1.28+** с доступом `kubectl` и правами cluster-admin (для установки CRD и провайдеров).
* Установленный **Helm 3.14+**.
* Установленный **Crossplane CLI** (`kubectl crossplane` plugin или бинарь `crossplane`) — опционально, для отладки.
* Учётные данные облачного провайдера (API-ключ/сервисный аккаунт) с правами на создание целевых ресурсов.
* Свободные ресурсы в namespace `crossplane-system` (рекомендуется выделенный узел/квоты при большом числе провайдеров из-за нагрузки от CRD).

Установка CLI (пример для Linux/amd64):

```bash
curl -sL "https://raw.githubusercontent.com/crossplane/crossplane/master/install.sh" | bash
# → crossplane installed to ./crossplane
sudo mv crossplane /usr/local/bin/
crossplane version
# → Version: <2.4.x>
```

### Сценарий 1: Установка Crossplane Core

```bash
helm repo add crossplane-stable https://charts.crossplane.io/stable
helm repo update
helm install crossplane crossplane-stable/crossplane \
  --namespace crossplane-system --create-namespace \
  --set args='{"--enable-composition-functions=true"}'
# → NAME: crossplane
# → LAST DEPLOYED: ...
# → STATUS: deployed
```

Проверка готовности:

```bash
kubectl -n crossplane-system get pods
# → crossplane-<hash>               1/1  Running
# → crossplane-rbac-manager-<hash>  1/1  Running

kubectl get crds | grep crossplane.io | head
# → (вывод зарегистрированных CRD ядра Crossplane)
```

Если поды не стартуют — проверить события `kubectl -n crossplane-system describe pod crossplane-<hash>` (частая причина — нехватка памяти/лимиты).

### Сценарий 2: Установка провайдера (Provider / Provider Family)

В v2.x обязателен полностью квалифицированный URL образа. Рекомендуется Family-подход — ставить только нужный сервис.

Пример для AWS (семейство + конкретный сервис S3):

```bash
kubectl apply -f - <<'EOF'
apiVersion: pkg.crossplane.io/v1
kind: Provider
metadata:
  name: upbound-provider-family-aws
spec:
  package: xpkg.upbound.io/upbound/provider-family-aws:v1.0.0
---
apiVersion: pkg.crossplane.io/v1
kind: Provider
metadata:
  name: upbound-provider-aws-s3
spec:
  package: xpkg.upbound.io/upbound/provider-aws-s3:v1.0.0
EOF
# → provider.pkg.crossplane.io/upbound-provider-family-aws created
# → provider.pkg.crossplane.io/upbound-provider-aws-s3 created
```

Проверка установки и здоровья пакета:

```bash
kubectl get providers
# → NAME                          INSTALLED  HEALTHY   PACKAGE                                       AGE
# → upbound-provider-family-aws   True       True      xpkg.upbound.io/upbound/provider-family-aws:v1.0.0   1m
# → upbound-provider-aws-s3       True       True      xpkg.upbound.io/upbound/provider-aws-s3:v1.0.0       1m

kubectl get crds | grep 's3.aws.upbound.io'
# → (появились CRD для ресурсов S3, напр. buckets.s3.aws.upbound.io)
```

Подробная настройка провайдеров: [Yandex Cloud](./provider_yandex_cloud_setup.md), [Kubernetes](./provider_kubernetes_setup.md).

### Сценарий 3: Настройка ProviderConfig

ProviderConfig хранит способ аутентификации провайдера. Учётные данные передаются через Secret (никогда не встраивайте ключи в сам ProviderConfig в открытом виде).

```bash
# 1. Создание Secret с учётными данными (пример AWS, формат зависит от провайдера)
kubectl -n crossplane-system create secret generic aws-creds \
  --from-literal=credentials='[default]
aws_access_key_id = <AWS_ACCESS_KEY_ID>
aws_secret_access_key = <AWS_SECRET_ACCESS_KEY>'
# → secret/aws-creds created
```

```yaml
# 2. ProviderConfig, ссылающийся на Secret
apiVersion: aws.upbound.io/v1beta1
kind: ProviderConfig
metadata:
  name: default
spec:
  credentials:
    source: Secret
    secretRef:
      namespace: crossplane-system
      name: aws-creds
      key: credentials
```

Поля:
* `metadata.name` — имя конфигурации, на которое ссылаются MR через `spec.providerConfigRef.name`.
* `spec.credentials.source` — источник учётных данных (`Secret`, `Environment`, `Filesystem`, `InjectedIdentity` для IRSA/Workload Identity).
* `spec.credentials.secretRef` — указание namespace/name/key Secret с данными.

```bash
kubectl apply -f providerconfig.yaml
kubectl get providerconfig
# → NAME      AGE
# → default   10s
```

### Сценарий 4: Создание Managed Resource (MR)

MR — минимальная единица управления облачным объектом. Пример бакета S3:

```yaml
apiVersion: s3.aws.upbound.io/v1beta1
kind: Bucket
metadata:
  name: my-bucket
spec:
  forProvider:
    region: eu-central-1
  providerConfigRef:
    name: default
  managementPolicies:
    - Observe
    - Create
    - Update
    - Delete
```

Применение и проверка:

```bash
kubectl apply -f bucket.yaml
# → bucket.s3.aws.upbound.io/my-bucket created

kubectl get bucket my-bucket
# → NAME        READY  SYNCED  EXTERNAL-NAME  AGE
# → my-bucket   True   True    my-bucket      45s

kubectl get bucket my-bucket -o yaml
# → status.conditions: [{type: Ready, status: "True"}, {type: Synced, status: "True"}]
# → metadata.annotations: crossplane.io/external-name: my-bucket
```

* `READY=True` — ресурс создан и готов к использованию.
* `SYNCED=True` — желаемое состояние совпадает с облаком.
* `crossplane.io/external-name` — идентификатор объекта в облаке.

Если `SYNCED=False` — смотреть `kubectl describe bucket my-bucket` (раздел Events) и логи провайдера.

### Сценарий 5: Композиция (XRD + Composition + Claim)

Построение высокоуровневого API "PostgreSQL-кластер" для разработчиков.

```yaml
# 1. XRD — схема API (cluster-scoped XR + namespace-scoped Claim)
apiVersion: apiextensions.crossplane.io/v1
kind: CompositeResourceDefinition
metadata:
  name: xpostgresqls.example.org
spec:
  group: example.org
  names:
    kind: XPostgreSQL
    plural: xpostgresqls
  claimNames:
    kind: PostgreSQL
    plural: postgresqls
  versions:
    - name: v1
      served: true
      referenceable: true
      schema:
        openAPIV3Schema:
          type: object
          properties:
            spec:
              type: object
              properties:
                size:
                  type: string
                  default: small
              required: [size]
---
# 2. Composition — реализация через пайплайн функций (v2, mode: Pipeline)
apiVersion: apiextensions.crossplane.io/v1
kind: Composition
metadata:
  name: xpostgresql.example.org
spec:
  compositeTypeRef:
    apiVersion: example.org/v1
    kind: XPostgreSQL
  mode: Pipeline
  pipeline:
    - step: build
      functionRef:
        name: function-example-postgres
```

Пользователь создаёт только Claim:

```yaml
apiVersion: example.org/v1
kind: PostgreSQL
metadata:
  name: my-db
  namespace: team-alpha
spec:
  size: small
```

Поток: `PostgreSQL` (Claim) → `XPostgreSQL` (XR) → MR (например, `RDSInstance`) через функцию `function-example-postgres`.

```bash
kubectl -n team-alpha apply -f claim.yaml
kubectl -n team-alpha get postgresql
# → NAME     READY  CONNECTION-SECRET   AGE
# → my-db    True   my-db-conn          1m

kubectl get composite
# → (XR, созданный автоматически)

crossplane beta trace xpostgresqls/<имя-xr>
# → визуализация дерева: XPostgreSQL → RDSInstance (+ Secret)
```

### Валидация и отладка

* Локальный рендеринг композиции без кластера: `crossplane render xr.yaml composition.yaml function.yaml`.
* Проверка манифестов: `crossplane beta validate <файлы>`.
* Граф композиции: `crossplane beta trace <xr>`.
* Список всех MR: `kubectl get managed` (aggregated CRD Crossplane).
* Список XR/Claim: `kubectl get composite`, `kubectl get claim`.
* Логи провайдера: `kubectl -n crossplane-system logs -l pkg.crossplane.io/provider=<имя>`.
* Проверка готовности к обновлению v1→v2: `crossplane beta upgrade check`.

### Устранение неполадок

* **Provider в состоянии `False`/`PackagePullBackOff`:** в v2 требуется полностью квалифицированный URL образа; проверьте `spec.package` и доступность реестра (`kubectl describe provider <имя>`).
* **MR завис в `Creating`/`Synced=False`:** причина — неверные учётные данные (ProviderConfig/Secret), отсутствие прав в облаке, превышение квот или несоответствие региона. Диагностика: `kubectl describe <mr>` (Events) и логи провайдера.
* **"cannot resolve reference to Composition / Function not found":** функция не установлена (`kind: Function`) или `compositeTypeRef` не совпадает с XRD.
* **Claim не создаёт XR:** отключён RBAC Manager либо нет прав на XRD/Composition — выдайте RBAC вручную.
* **Слишком много CRD / нестабильный API-сервер:** используйте Provider Families и MRDs, ограничьте набор ресурсов.
* **Дрейф не исправляется быстро:** сверка поллинговая; уменьшите poll interval через `DeploymentRuntimeConfig` (аргумент `--poll`), учитывая нагрузку на API облака.
* **Превышение лимитов API облака:** снизите `--max-reconcile-rate` в `DeploymentRuntimeConfig`.

### Лучшие практики и очистка

* Устанавливайте провайдеры через **Provider Families / MRDs**, а не монолитные пакеты — меньше CRD, стабильнее control plane.
* Всегда указывайте **полностью квалифицированный URL** пакета (требование v2).
* Храните секреты вне Git: ESO + Vault, либо SOPS для шифрования манифестов `ProviderConfig` в репозитории.
* Защищайте XRD/Composition через RBAC и политики OPA/Kyverno — ограничивайте допустимые значения параметров.
* Используйте **namespaced XR/MR** для мультитенантности и изоляции команд.
* Используйте **Composition Functions** вместо удалённой в v2 нативной patch-and-transform композиции.
* Тюнинг производительности — через `DeploymentRuntimeConfig` (poll interval, reconcile rate).

Очистка окружения:
* Удаляйте ресурсы в порядке: Claim → XR (каскадом удаляет MR) → MR (удаляет облачный объект). Облачный ресурс удаляется, только если в `managementPolicies` есть `Delete` и `deletionPolicy` не `Orphan`.
* Режим `ObserveOnly` (`managementPolicies: [Observe]`) позволяет импортировать существующую инфраструктуру без её удаления при удалении манифеста.
* Удаление провайдера: `kubectl delete provider <имя>` (сначала удалите все его MR, иначе останутся осиротевшие облачные ресурсы).

### Ограничения и пограничные случаи

* **Breaking-изменения v2:** удалены нативная patch-and-transform композиция, `ControllerConfig`, external secret stores, нативные connection details у XR, default registry (см. раздел выше).
* **Cluster-scoped MR/XR устарели:** в v2 legacy, будут удалены; новые ворклоады — namespaced.
* **Operations — alpha:** функции операционных задач нестабильны, могут меняться.
* **Поллинговая сверка:** дрейф обнаруживается с задержкой ≈ poll interval; нет гарантии мгновенной реакции без внешних событий.
* **Нагрузка на API облака:** при большом числе MR возможны квоты API — требуется rate limiting.
* **Масштаб CRD:** монолитные провайдеры (сотни–тысячи CRD) дестабилизируют control plane без Family/MRD.

### Подробные руководства

* Настройка провайдера для Yandex Cloud: [Настройка Yandex Cloud провайдера](./provider_yandex_cloud_setup.md)
* Управление ресурсами внутри кластера: [Управление Kubernetes ресурсами](./provider_kubernetes_setup.md)
* Интеграция с GitOps-инструментами: [Интеграция с GitOps](./gitops_integration.md)
* Сравнение с альтернативами: [Сравнение с Terraform](./terraform_comparison.md)

Управление ресурсами Yandex Cloud: [Yandex Resource Manager](../../Yandex/Resource_Manager/overview.md).

### Смежные тематические разделы

* [Composition Functions и EnvironmentConfig](./composition_functions.md) — pipeline функций, `functionConfig`, локальный `render`.
* [Мультитенантность и OOO](./multi_tenancy.md) — изоляция команд, `onlyOneOf`/`ownerOnlyOrphan`, per-namespace RBAC.
* [Защита зависимостей (Usage)](./usage_protection.md) — `Usage`/`ClusterUsage`, защита от каскадного удаления.
* [Тестирование платформы](./testing_crossplane.md) — `crossplane composition render`/`validate`, envtest, CI.
* [Обновление и миграция](./upgrade_migration.md) — ревизии пакетов, ломающие изменения v2, откат.
* [Observability](./observability.md) — метрики `crossplane_managed_resource_*`, алерты, Grafana.
* [Политики и Governance (Kyverno/OPA)](./policy_governance.md) — валидация Claim/XRD, защита удаления.
* [Self-Service и IDP](./self_service.md) — Claims как self-service API, Backstage/Score, golden paths.
* [Безопасность цепочки поставок](./package_security.md) — подписание/верификация пакетов (cosign), приватные реестры.
* [Backup и Disaster Recovery control plane](./backup_dr.md) — etcd/Velero, Git как source of truth, восстановление.

## Дополнительная информация

Общие принципы GitOps описаны в [GitOps Overview](../GitOps_overview.md), инструмент для GitOps-доставки — в [ArgoCD Overview](../ArgoCD/argocd_overview.md).

Внешние ресурсы:

* Официальная документация Crossplane: [docs.crossplane.io](https://docs.crossplane.io/)
* Анонс перехода в CNCF Graduated: [Crossplane Graduation (CNCF, 6 ноября 2025)](https://www.cncf.io/announcements/2025/11/06/cloud-native-computing-foundation-announces-graduation-of-crossplane/)
* Что нового в v2: [What's New in v2](https://docs.crossplane.io/latest/whats-new)
