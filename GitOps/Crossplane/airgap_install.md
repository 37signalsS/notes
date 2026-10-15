# Crossplane: Air-Gap установка (изолированный контур с нуля)

**Актуально для:** Crossplane v1.18+ / v2.x (актуально v2.4); Kubernetes 1.28–1.32+; On-Premise / Bare-Metal без выхода в интернет

## Определения

**Air-Gap (изолированный контур)** — сетевая изоляция кластера от публичного интернета: все артефакты (бинарники CLI, Helm-чарты, OCI-пакеты, образы подов) доставляются через доверенный шлюз во внутренний OCI-реестр (Harbor/Nexus). Ядро Crossplane и все провайдеры устанавливаются только по ссылкам на внутренний реестр.

**Шлюз (gateway / диодная передача)** — односторонний канал переноса артефактов (физический носитель, air-gap firewall, единый диод) между внешней сетью и изолированным контуром; единственная легитимная точка импорта пакетов.

**Helm Chart Museum / внутренний Helm-репозиторий** — локальный репозиторий чартов (Harbor OCI, ChartMuseum), содержащий `crossplane-stable/crossplane` для установки ядра без обращения к публичным `charts.crossplane.io`.

**Corporare CA Bundle** — корневой сертификат корпоративного удостоверяющего центра, монтируемый в поды Crossplane и провайдеров для проверки TLS-сертификатов внутреннего Harbor.

**Список артефактов (air-gap manifest)** — итоговый перечень версий и sha256-дайджестов всех компонентов (CLI, чарт, провайдеры, функции), необходимых для воспроизводимой установки в изолированном контуре; ведётся в Git и служит источником истины для шлюза.

## Базовые концепции и архитектура

### Целевая архитектура изолированного контроля

```text
[ Внешняя сеть ]                       [ Air-Gap контур ]
  GitHub / OCI                          ┌──────────────────────────┐
      │                                │  Внутренний Harbor       │
      ▼  (1) Шлюз: crane pull /        │  - helm charts (OCI)     │
  sha256sum / cosign sign               │  - xpkg (providers)      │
      │                                │  - function images       │
      ▼  (2) Перенос по носителю/        │  - CA Bundle             │
  Air-gap firewall (односторонне)       └──────────┬───────────────┘
      │                                            │
      ▼  (3) crane push                            ▼
  ┌───────────────────────────────────────────────────────────┐
  │  Управляющий кластер Kubernetes (Air-Gap)                  │
  │  ┌────────────────────────────────────────────────────┐   │
  │  │ Crossplane Core (Helm из Harbor OCI)               │   │
  │  │ Provider / Function (packagePullSecrets + digest)  │   │
  │  └────────────────────────────────────────────────────┘   │
  │  ┌────────────────────────────────────────────────────┐   │
  │  │ Managed Resources → внутренние On-Premise системы  │   │
  │  │ (Proxmox, MinIO, Patroni, Rancher, etc.)           │   │
  │  └────────────────────────────────────────────────────┘   │
  └───────────────────────────────────────────────────────────┘
```

### Принципы air-gap установки

1. **Никаких ссылок на публичные источники** в манифестах `Provider`, `Function`, `Configuration`, Helm-чарте — только `harbor.airgap.local/...`.
2. **Digest pinning обязателен** — теги недоступны для проверки без сети; фиксация по sha256 — единственный способ гарантировать целостность.
3. **Подпись внутренним ключом** (см. [Безопасность пакетов](./package_security.md), Сценарий 6) — проверка Cosign выполняется шлюзовым ключом, не публичным.
4. **CA Bundle** монтируется во все поды, обращающиеся к Harbor (ядро, пакетный менеджер, каждый провайдер через `DeploymentRuntimeConfig`).

## Практические сценарии и конфигурация

### Сценарий 1: Подготовка на шлюзе (перенос артефактов)

На рабочей станции шлюза (с доступом в интернет) собираем полный набор:

```bash
# 1. Клиент Crossplane CLI (x86_64)
curl -sL "https://raw.githubusercontent.com/crossplane/crossplane/master/install.sh" | bash
sha256sum crossplane > crossplane-cli.sha256

# 2. Helm-чарт ядра в OCI-формате
helm pull oci://xpkg.upbound.io/crossplane-stable/crossplane \
  --version 2.4.0 -d charts/

# 3. Пакеты провайдеров и функций по фиксированным дайджестам
crane pull xpkg.upbound.io/crossplane-contrib/provider-kubernetes@sha256:8b4e723... packages/
crane pull xpkg.upbound.io/crossplane-contrib/provider-sql@sha256:1c2d3e4... packages/
crane pull xpkg.upbound.io/crossplane-contrib/function-patch-and-transform@sha256:a1b2c3... packages/

# 4. Подпись всем пакетам внутренним air-gap ключом (без tlog)
for f in packages/*.tar; do
  cosign sign --key airgap-cosign.key --tlog-upload=false <repo>@$(crane digest <pushed-ref>)
done

# 5. Фиксация манифеста
cat > airgap-manifest.yaml <<EOF
crossplane-cli: $(sha256sum crossplane | awk '{print $1}')
helm-chart: crossplane-2.4.0.tgz
providers:
  provider-kubernetes@sha256:8b4e723...
  provider-sql@sha256:1c2d3e4...
functions:
  function-patch-and-transform@sha256:a1b2c3...
EOF
```

Переносим архив по воздуху (USB/односторонний канал) и импортируем во внутренний Harbor (см. [Безопасность пакетов](./package_security.md), Сценарий 6).

### Сценарий 2: Установка ядра из внутреннего Helm-репозитория

Публикуем чарт в Harbor (OCI-репозиторий):

```bash
helm push charts/crossplane-2.4.0.tgz oci://harbor.airgap.local/charts
```

Создаём секрет аутентификации и CA Bundle:

```bash
kubectl create namespace crossplane-system
kubectl -n crossplane-system create secret docker-registry harbor-pull-secret \
  --docker-server=harbor.airgap.local \
  --docker-username=robot-crossplane \
  --docker-password=<robot-token>

kubectl -n crossplane-system create configmap corporate-root-ca \
  --from-file=corp-ca.crt=ca-bundle.pem
```

Значения Helm для air-gap:

```yaml
# values-airgap.yaml
image:
  repository: harbor.airgap.local/crossplane/crossplane
  tag: 2.4.0@sha256:9e8d7c6...

imagePullSecrets:
  - name: harbor-pull-secret

extraVolumes:
  - name: corp-ca
    configMap:
      name: corporate-root-ca
extraVolumeMounts:
  - name: corp-ca
    mountPath: /etc/ssl/certs/corp-ca.crt
    subPath: corp-ca.crt
    readOnly: true

args:
  - "core"
  - "start"
  - "--enable-composition-functions"
  - "--enable-signature-verification"
  - "--validation-pem=/etc/crossplane/certs/cosign.pub"

extraVolumes:
  - name: cosign-key
    secret:
      secretName: cosign-package-signing-key
```

Установка:

```bash
helm upgrade --install crossplane \
  oci://harbor.airgap.local/charts/crossplane \
  --version 2.4.0 \
  --namespace crossplane-system \
  -f values-airgap.yaml \
  --wait --timeout 10m
# → STATUS: deployed
```

### Сценарий 3: Установка провайдеров и функций по digest

```yaml
apiVersion: pkg.crossplane.io/v1
kind: Provider
metadata:
  name: provider-kubernetes
spec:
  package: harbor.airgap.local/crossplane/provider-kubernetes@sha256:8b4e723a1fbc9c01824d55aa610b2e3f019a77b81239c5132de984f8812c80aa
  packagePullPolicy: IfNotPresent
  packagePullSecrets:
    - name: harbor-pull-secret
  runtimeConfigRef:
    name: airgap-provider-runtime
---
apiVersion: pkg.crossplane.io/v1
kind: Function
metadata:
  name: function-patch-and-transform
spec:
  package: harbor.airgap.local/crossplane/function-patch-and-transform@sha256:a1b2c3d4...
  packagePullSecrets:
    - name: harbor-pull-secret
```

Runtime с CA Bundle для всех провайдеров:

```yaml
apiVersion: pkg.crossplane.io/v1beta1
kind: DeploymentRuntimeConfig
metadata:
  name: airgap-provider-runtime
spec:
  deploymentTemplate:
    spec:
      template:
        spec:
          volumes:
            - name: corp-ca
              configMap:
                name: corporate-root-ca
          containers:
            - name: package-runtime
              volumeMounts:
                - name: corp-ca
                  mountPath: /etc/ssl/certs/corp-ca.crt
                  subPath: corp-ca.crt
                  readOnly: true
```

### Сценарий 4: Верификация изолированной установки

```bash
# 1. Поды ядра
kubectl get pods -n crossplane-system
# → NAME                          READY   STATUS    RESTARTS   AGE
# → crossplane-6d8f7c9-abc12      1/1     Running   0          3m
# → crossplane-rbac-manager-...   1/1     Running   0          3m

# 2. Провайдеры установились по digest, без PackagePullBackOff
kubectl get providers
# → NAME                  INSTALLED   HEALTHY   PACKAGE
# → provider-kubernetes   True        True      harbor.airgap.local/...@sha256:8b4e723...

# 3. Подписи прошли проверку
kubectl get providerrevisions -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.status.conditions[?(@.type=="Healthy")].message}{"\n"}{end}'
# → provider-kubernetes-abc  ProviderRevision is healthy
```

## Операции и команды

| Задача | Команда |
|---|---|
| Экспорт пакета с апстрима | `crane pull <ref>@sha256:... <tar>` |
| Импорт в air-gap Harbor | `crane push <tar> harbor.airgap.local/...` |
| Фиксация дайджеста | `crane digest harbor.airgap.local/...` |
| Подпись (без tlog) | `cosign sign --key airgap-cosign.key --tlog-upload=false <ref>@sha256:...` |
| Проверка подписи | `cosign verify --key airgap-cosign.pub --insecure-ignore-tlog=true <ref>@sha256:...` |
| Публикация чарта | `helm push crossplane-<ver>.tgz oci://harbor.airgap.local/charts` |
| Установка из OCI-чарта | `helm upgrade --install crossplane oci://harbor.airgap.local/charts/crossplane -f values-airgap.yaml` |

## Устранение неполадок (Troubleshooting)

| Симптом | Первопричина | Диагностика | Решение |
|---|---|---|---|
| `x509: certificate signed by unknown authority` | CA Bundle не смонтирован в под ядра или провайдера | `kubectl -n crossplane-system logs deploy/crossplane \| grep x509` | Добавить `extraVolumes`/`extraVolumeMounts` (ядро) или `DeploymentRuntimeConfig` (провайдеры) |
| `ErrSignatureVerificationFailed` | Подпись сделана внешним (не air-gap) ключом, либо отсутствует `--validation-pem` | `kubectl describe providerrevision <name>` | Убедиться, что в секрете `cosign-package-signing-key` лежит `cosign.pub` air-gap ключа |
| `PackagePullBackOff` / `dial tcp ... timeout` | Ссылка на публичный реестр (нарушение air-gap) | `kubectl describe provider <name>` | Заменить `spec.package` на `harbor.airgap.local/...@sha256:...` |
| `helm pull` падает: `no such host charts.crossplane.io` | Использован публичный Helm-репозиторий | Вывод Helm | Добавить `oci://harbor.airgap.local/charts` в источник чарта |
| Провайдер не видит внутренние TLS-эндпоинты | Отсутствует CA на уровне провайдера (не только ядра) | Логи провайдера: TLS handshake failure | Смонтировать CA через `DeploymentRuntimeConfig` (Сценарий 3) |

## Лучшие практики (Best Practices)

1. **Air-gap manifest в Git** — единственный источник истины для шлюза; обновление версий только через ревизию этого файла.
2. **Digest pinning + подпись** — без сети теги не проверяемы; digest + Cosign — минимальный уровень доверия.
3. **Единый CA Bundle** — монтировать во все компоненты (ядро, провайдеры, функции), а не только в ядро.
4. **Регулярное обновление шлюза** — air-gap не означает «замороженный стек»: провайдеры должны получать патчи безопасности по тому же циклу, что и online-контуры (см. [Обновление и миграция](./upgrade_migration.md)).
5. **Сетевая изоляция провайдеров** — egress-политики только до целевых систем и kube-apiserver; запрет наружу (см. [Безопасность пакетов](./package_security.md), NetworkPolicy).
6. **Тестовая ступень на шлюзе** — перед импортом в prod-air-gap прогонять `crossplane render` и Trivy-сканирование на шлюзе (см. [Тестирование платформы](./testing_crossplane.md)).

## Дополнительная информация

### Внутренние ссылки

* [Безопасность пакетов](./package_security.md) — подробности зеркалирования, подписи, Digest Pinning, Admission-контроль.
* [Обновление и миграция](./upgrade_migration.md) — цикл обновления в air-gap (ссылка на шлюз как единственный источник новых версий).
* [Observability](./observability.md) — мониторинг подов в изолированном контуре.
* [Обзор Crossplane](./overview.md) — базовая установка ядра (сравнение с air-gap сценарием).

### Внешние ресурсы

* [Crossplane Air-Gapped Installation (community patterns)](https://docs.crossplane.io/latest/software/install/) — официальный гайд установки; для air-gap адаптируется под внутренний OCI-реестр.
* [Harbor replication and air-gap](https://goharbor.io/docs/latest/administration/replication/) — механизмы репликации артефактов через шлюз.
