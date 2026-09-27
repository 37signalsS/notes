# Установка в закрытом контуре (Air-gapped)

> [Назад к оглавлению](../overview.md)

> **Основной документ по теме:** установка kube-prometheus-stack в изолированной среде без доступа к интернету.  
> **Смежные темы:** [Kubespray: Offline установка](../../../../Kubernetes/Installation/Kubespray/offline_installation/offline_definitions.md) — развёртывание базовой инфраструктуры кластера; [Обзор Harbor](../../../../Docker/Docker_registries/Harbor/overview.md) — использование приватного реестра; [Диагностика загрузки образов](../../../../Kubernetes/Troubleshooting/Common_Errors/PodImagePullErrors/airgapped.md) — решение типичных проблем в изоляции.

## Определения

**Air-gapped кластер (Закрытый контур)** — среда Kubernetes, полностью изолированная от публичных сетей. Все артефакты (Docker-образы, Helm-чарты, бинарные файлы) должны быть доставлены на физических носителях или через защищённые шлюзы.

**Приватный реестр (Harbor/Nexus)** — внутренний сервис хранения и дистрибуции образов. В оффлайн-установке он становится единственным источником данных для кластера.

**OCI (Open Container Initiative)** — стандарт, позволяющий использовать Docker-реестры для хранения не только образов, но и Helm-чартов. Это основной метод дистрибуции чартов в современных закрытых контурах.

## Предварительные требования

| Компонент | Минимальная версия / Требование | Проверка |
|:---|:---|:---|
| **Kubernetes** | v1.25+ | `kubectl version --short` |
| **Helm** | v3.8+ (поддержка OCI) | `helm version` |
| **Harbor** | v2.11+ (полная поддержка OCI 1.1) | `curl -sk https://harbor.domain.local/api/v2.0/version` |
| **Container Runtime** | containerd v1.5+ или Docker 20.10+ | `crictl info` или `docker info` |
| **Диск на хосте-шаблонизаторе** | Минимум 20Gi на образы чарта | `df -h` |
| **Диск в Harbor** | Минимум 50Gi для проекта `monitoring` | Harbor UI → Projects → monitoring → Quota |
| **Сеть** | Harbor доступен из подов кластера (L3-маршрут, порт 443) | `curl -sk https://harbor.domain.local` с ноды |
| **TLS** | CA Harbor добавлен в доверенное хранилище всех нод | `openssl s_client -connect harbor.domain.local:443 -showcerts` |

### Требования к Harbor

Перед началом работы убедитесь, что Harbor настроен соответствующим образом:

1. **Проект `monitoring`** создан с режимом `Private`.
2. **Robot Account** с правами `push` и `pull` в проекте `monitoring` создан.
3. **Proxy Cache** (опционально) настроен для кэширования внешних реестров (`docker.io`, `quay.io`, `registry.k8s.io`), если кластер допускает ограниченный исходящий доступ.
4. **Retention Policy** настроена для предотвращения переполнения хранилища.
5. **Immutable Tags** включены для production-проектов (опционально, но рекомендуется).

Подробнее об архитектуре и настройке Harbor см. [Обзор Harbor](../../../../Docker/Docker_registries/Harbor/overview.md) и [Использование Harbor](../../../../Docker/Docker_registries/Harbor/usage.md).

## Основные концепции

### Архитектура оффлайн-развёртывания

```
┌───────────────────────┐         Перенос данных          ┌──────────────────────────┐
│  Хост с интернетом    │  ──────────────────────────►    │  Хост в закрытом контуре  │
│  (Download Zone)      │    • prom-images.tar            │  (Air-gapped Zone)        │
│                       │    • kps-chart.oci.tar          │                           │
│  1. Загрузка чарта    │                                 │  1. Импорт образов        │
│  2. Сбор списка image │                                 │  2. Push в локальный OCI  │
│  3. Docker pull/save  │                                 │  3. Helm install          │
└───────────────────────┘                                 └─────────────┬────────────┘
                                                                       │
                                                        ┌──────────────▼────────────┐
                                                        │  Kubernetes Cluster       │
                                                        │  (Offline)                │
                                                        │                           │
                                                        │  Harbor: Pull образов      │
                                                        │  Helm: Deploy из OCI      │
                                                        └───────────────────────────┘
```

### Этапы процесса

| Этап | Локация | Описание |
|:---|:---|:---|
| **1. Подготовка** | С интернетом | Скачивание чарта, извлечение списка всех образов (включая зависимости и sidecars), экспорт архивов. |
| **2. Транспортировка** | Физическая | Перенос архивов во внутренний контур согласно регламентам безопасности (съемные носители). |
| **3. Наполнение** | Внутренняя сеть | Загрузка образов и чартов в локальный Harbor, тегирование согласно внутренней структуре. |
| **4. Развёртывание** | Кластер | Установка через Helm с переопределением путей ко всем компонентам. |

### Ключевые отличия от онлайн-установки

| Параметр | Онлайн | Оффлайн |
|:---|:---|:---|
| Источник чарта | `https://prometheus-community.github.io/helm-charts` | `oci://harbor.domain.local/helm/` |
| Источник образов | Публичные Registry (docker.io, quay.io) | Приватный Harbor/Nexus |
| Глобальный реестр | Не требуется | Обязательный `global.imageRegistry` |
| Секреты (Pull) | Не требуются (для public) | Обязательный `imagePullSecrets` для Harbor |
| Управление CRD | `crds.enabled: true` | Рекомендуется ручной `kubectl apply -f crds/` |

### Конфигурация Container Runtime для работы с Harbor

В оффлайн-среде containerd (или CRI-O) должен перенаправлять все запросы на локальный Harbor. Это обеспечивается на двух уровнях:

1. **На уровне узла:** файлы `hosts.toml` в `/etc/containerd/certs.d/` определяют, какие реестры и на какие зеркала перенаправлять.
2. **На уровне Ansible/Helm:** все манифесты должны использовать адреса локального Harbor, чтобы runtime никогда не обращался к публичным реестрам.

```
kubelet → containerd (CRI) → registry controller → /etc/containerd/certs.d/
                                                            ↓
                                               ┌─────────────────────────┐
                                               │  docker.io/...          │ → harbor.domain.local/monitoring/docker.io/...
                                               │  quay.io/...            │ → harbor.domain.local/monitoring/quay.io/...
                                               │  registry.k8s.io/...    │ → harbor.domain.local/monitoring/registry.k8s.io/...
                                               │  harbor.domain.local/...│ → harbor.domain.local/... (без маппинга)
                                               └─────────────────────────┘
```

**Важно:** В air-gapped среде критически важно предварительно загрузить в Harbor образ `pause` (`registry.k8s.io/pause`), который используется Kubernetes для создания сетевого namespace пода. Если рантайм не найдет его локально, поды не смогут запуститься.

### Структура проекта Harbor для мониторинга

Рекомендуется логическое разделение артефактов внутри Harbor:

| Проект | Назначение | Пример пути |
|:---|:---|:---|
| `monitoring` | Образы и чарт kube-prometheus-stack | `harbor.domain.local/monitoring/quay.io/prometheus/prometheus` |
| `k8s-system` | Системные образы кластера (pause, coredns, etcd) | `harbor.domain.local/k8s-system/registry.k8s.io/pause` |
| `helm` | Helm-чарты в OCI-формате | `harbor.domain.local/helm/kube-prometheus-stack` |

Такой подход позволяет назначать разные политики ретенции и доступ для каждого типа артефактов.

## Практические сценарии

### Pre-flight проверка

Перед началом подготовки артефактов выполните проверки на хосте с интернетом и в закрытом контуре:

```bash
# 1. Проверка доступности Harbor и версии API
curl -sk https://harbor.domain.local/api/v2.0/version
# → {"harbor_version":"2.11.x"}

# 2. Проверка поддержки OCI в Harbor
curl -sk https://harbor.domain.local/api/v2.0/ | head -5
# → Должен вернуть JSON с поддержкой OCI-артефактов

# 3. Проверка резолва имени Harbor из пода кластера
kubectl run dnstest --image=busybox:1.37 --restart=Never --rm -it -- nslookup harbor.domain.local

# 4. Проверка доступности Harbor через containerd crictl
crictl pull harbor.domain.local/monitoring/registry.k8s.io/pause:3.6

# 5. Проверка существования проекта и Robot Account
curl -sk -u "robot$monitoring:pull-push-token" \
  https://harbor.domain.local/api/v2.0/projects/monitoring/repositories | jq length
```

### Шаг 1: Подготовка артефактов (машина с интернетом)

#### 1.1 Скачивание и распаковка чарта

```bash
export CHART_VERSION="88.1.x"
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update
helm pull prometheus-community/kube-prometheus-stack --version $CHART_VERSION --untar
cd kube-prometheus-stack
```

#### 1.2 Извлечение полного списка образов

Метод через `helm template` является самым надежным, так как он учитывает включенные компоненты и их зависимости.

```bash
# Генерация манифестов для анализа (включите все нужные компоненты)
helm template kps . \
  --set grafana.enabled=true \
  --set prometheus-node-exporter.enabled=true \
  --set kube-state-metrics.enabled=true \
  > rendered.yaml

# Извлечение списка уникальных образов
grep -oE 'image:\s*"?[^"]+' rendered.yaml | sed -E 's/^image:\s*"?//; s/"$//' | sort -u > prom-images.txt

# ВАЖНО: Добавление системных образов, которые могут не попасть в шаблон (например, config-reloader)
echo "quay.io/prometheus-operator/prometheus-config-reloader:v0.92.0" >> prom-images.txt
echo "docker.io/library/busybox:1.37.0" >> prom-images.txt
sort -u prom-images.txt -o prom-images.txt
```

#### 1.3 Сохранение образов в архив

```bash
# Pull всех образов
for img in $(cat prom-images.txt); do
  docker pull $img
done

# Сохранение в единый бандл
docker save -o prom-images.tar $(cat prom-images.txt)

# Упаковка самого чарта
cd ..
tar -cvzf kube-prometheus-stack-bundle.tar.gz kube-prometheus-stack/ prom-images.tar prom-images.txt
```

#### 1.4 Альтернативный метод: Skopeo (рекомендуется для production)

Skopeo позволяет сохранять образы сразу в формате OCI-директории, что исключает зависимость от Docker-демона и упрощает верификацию:

```bash
# Установка skopeo (на хосте с интернетом)
# Ubuntu/Debian:
apt-get install -y skopeo

# Синхронизация в OCI-директорию
mkdir -p prom-images-oci
while read -r img; do
  skopeo copy "docker://${img}" "dir:prom-images-oci/$(echo ${img} | tr '/:' '_')"
done < prom-images.txt

# Верификация образа перед переносом
skopeo inspect "dir:prom-images-oci/$(echo quay.io/prometheus/prometheus:v3.12.0 | tr '/:' '_')" | jq .Digest
```

#### 1.5 Альтернативный метод: ORAS для Helm-чартов

ORAS (OCI Registry As Storage) позволяет упаковывать и переносить Helm-чарты как OCI-артефакты:

```bash
# Установка ORAS
curl -sL https://github.com/oras-project/oras/releases/download/v1.1.0/oras_1.1.0_linux_amd64.tar.gz | tar -xz oras

# Упаковка чарта с зависимостями
helm dependency build ./kube-prometheus-stack
helm package ./kube-prometheus-stack --version $CHART_VERSION

# Пуш чарта через ORAS
oras push oci://harbor.domain.local/helm/kube-prometheus-stack:$CHART_VERSION \
  kube-prometheus-stack-$CHART_VERSION.tgz \
  --config /dev/null
```

### Шаг 2: Загрузка в приватный репозиторий (Harbor)

#### 2.0 Подготовка Harbor

Перед импортом образов убедитесь, что Harbor настроен:

```bash
# Создание проекта (если не существует)
curl -sk -X POST https://harbor.domain.local/api/v2.0/projects \
  -H "Content-Type: application/json" \
  -u "admin:Harbor12345" \
  -d '{
    "project_name": "monitoring",
    "public": false,
    "enable_content_trust": false,
    "enable_content_trust_cosign": false,
    "prevent_vul": false,
    "severity": "high",
    "enable_policy": true,
    "reuse_sys_cve_whitelist": true
  }'

# Создание Robot Account для CI/CD (pull + push)
curl -sk -X POST https://harbor.domain.local/api/v2.0/robots \
  -H "Content-Type: application/json" \
  -u "admin:Harbor12345" \
  -d '{
    "name": "kps-deployer",
    "duration": -1,
    "level": "project",
    "permissions": [
      {
        "namespace": "monitoring",
        "kind": "project",
        "access": [
          {"resource": "repository", "action": "pull"},
          {"resource": "repository", "action": "push"},
          {"resource": "tag", "action": "create"},
          {"resource": "tag", "action": "list"},
          {"resource": "artifact", "action": "read"},
          {"resource": "artifact", "action": "create"}
        ]
      }
    ]
  }'
```

**Настройка Retention Policy в Harbor UI:**
1. Перейдите в проект `monitoring` → `Tag Immutability` → включите `Immutable Tags`.
2. Перейдите в `Replication` → создайте правило ретенции: `Keep last 10 tags` или `Keep images for 90 days`.
3. Установите квоту проекта: `50Gi` (или больше в зависимости от объёма данных).

#### 2.1 Импорт образов

На машине внутри закрытого контура, имеющей доступ к Harbor:

```bash
tar -xvzf kube-prometheus-stack-bundle.tar.gz

# Вариант A: Docker (традиционный)
docker load -i prom-images.tar

# Вариант B: Skopeo (рекомендуется)
mkdir -p /tmp/prom-images-load
skopeo copy "dir:prom-images-oci/" "docker-daemon:harbor.domain.local/monitoring"
```

#### 2.2 Тегирование и Push в Harbor

Рекомендуется сохранять структуру оригинальных имен для избежания конфликтов.

```bash
export HARBOR="harbor.domain.local"
export PROJECT="monitoring"
docker login ${HARBOR}

while read -r img; do
  # Создаем новый тег: harbor.domain.local/monitoring/оригинальный_путь_образа
  # Пример: quay.io/prometheus/prometheus -> harbor.domain.local/monitoring/quay.io/prometheus/prometheus
  new_tag="${HARBOR}/${PROJECT}/${img}"
  docker tag "${img}" "${new_tag}"
  docker push "${new_tag}"
done < prom-images.txt
```

##### 2.2.1 Верификация загруженных образов

```bash
# Проверка наличия ключевых образов через Harbor API
curl -sk -u "robot$monitoring:pull-push-token" \
  "https://harbor.domain.local/api/v2.0/projects/monitoring/repositories/quay.io/prometheus/prometheus/artifacts" | jq '.[] | .digest'

# Проверка тегов конкретного образа
curl -sk -u "robot$monitoring:pull-push-token" \
  "https://harbor.domain.local/api/v2.0/projects/monitoring/repositories/quay.io/prometheus/prometheus/artifacts/v3.12.0/tags" | jq .
```

#### 2.3 Пуш чарта в OCI-хранилище

```bash
helm package ./kube-prometheus-stack
helm push kube-prometheus-stack-*.tgz oci://${HARBOR}/helm
```

##### 2.3.1 Альтернатива: ORAS для Helm-чартов

```bash
oras push oci://${HARBOR}/helm/kube-prometheus-stack:$CHART_VERSION \
  kube-prometheus-stack-$CHART_VERSION.tgz \
  --config /dev/null
```

##### 2.4 Проверка OCI-хранилища Helm

```bash
# Список доступных чартов
curl -sk https://harbor.domain.local/v2/helm/tags/list | jq .

# Скачивание и распаковка чарта для проверки
helm pull oci://${HARBOR}/helm/kube-prometheus-stack --version $CHART_VERSION
tar -tzf kube-prometheus-stack-*.tgz | head -20
```

### Шаг 3: Установка в закрытом контуре

#### 3.0 Настройка containerd на рабочих узлах

Перед установкой Helm-чарта настройте containerd на всех узлах кластера для перенаправления pull-запросов на Harbor:

```bash
# Создание директории для registry-контроллера
mkdir -p /etc/containerd/certs.d/harbor.domain.local

# Создание hosts.toml для перенаправления всех публичных реестров на Harbor
cat > /etc/containerd/certs.d/harbor.domain.local/hosts.toml <<'EOF'
[host."harbor.domain.local"]
  capabilities = ["pull", "resolve", "push"]
  skip_verify = false
  ca = "/etc/containerd/certs.d/harbor.domain.local/ca.crt"

# Перенаправление публичных реестров (опционально, если используете proxy cache)
[host."docker.io"]
  endpoint = ["https://harbor.domain.local"]

[host."quay.io"]
  endpoint = ["https://harbor.domain.local"]

[host."registry.k8s.io"]
  endpoint = ["https://harbor.domain.local"]
EOF

# Перезагрузка containerd
systemctl restart containerd

# Проверка работы реестрового маппинга
crictl pull harbor.domain.local/monitoring/quay.io/prometheus/prometheus:v3.12.0
```

**Примечание:** Если кластер использует Docker вместо containerd, аналогичная настройка выполняется через `/etc/docker/daemon.json`:

```json
{
  "insecure-registries": ["harbor.domain.local:443"],
  "registry-mirrors": [
    "https://harbor.domain.local"
  ]
}
```

#### 3.1 Создание секрета для Pull образов

```bash
kubectl create namespace monitoring

# Вариант A: Секрет на уровне namespace (рекомендуется)
kubectl create secret docker-registry harbor-pull-secret \
  -n monitoring \
  --docker-server=${HARBOR} \
  --docker-username=robot\$monitoring \
  --docker-password=<robot-token>

# Вариант B: Секрет на уровне ServiceAccount (если namespace уже используется)
kubectl create serviceaccount prometheus -n monitoring
kubectl patch serviceaccount prometheus -n monitoring \
  -p '{"imagePullSecrets": [{"name": "harbor-pull-secret"}]}'
```

**Примечание:** При использовании Robot Account в username экранируйте символ `$` как `\$` в bash, либо используйте кавычки.

#### 3.2 Подготовка values.yaml (Максимальная детализация)

Не все компоненты корректно подхватывают `global.imageRegistry`, поэтому требуется точечное переопределение.

```yaml
# offline-values.yaml
crds:
  enabled: true # Если устанавливаете впервые

global:
  imageRegistry: "harbor.domain.local/monitoring"
  imagePullSecrets:
    - name: harbor-pull-secret

prometheusOperator:
  image:
    registry: harbor.domain.local
    repository: monitoring/quay.io/prometheus-operator/prometheus-operator
  prometheusConfigReloader:
    image:
      registry: harbor.domain.local
      repository: monitoring/quay.io/prometheus-operator/prometheus-config-reloader

prometheus:
  prometheusSpec:
    image:
      registry: harbor.domain.local
      repository: monitoring/quay.io/prometheus/prometheus
    # Важно для sidecars внутри пода Prometheus
    containers:
      - name: config-reloader
        image: harbor.domain.local/monitoring/quay.io/prometheus-operator/prometheus-config-reloader:v0.92.0

alertmanager:
  alertmanagerSpec:
    image:
      registry: harbor.domain.local
      repository: monitoring/quay.io/prometheus/alertmanager

kube-state-metrics:
  image:
    registry: harbor.domain.local
    repository: monitoring/registry.k8s.io/kube-state-metrics/kube-state-metrics

prometheus-node-exporter:
  image:
    registry: harbor.domain.local
    repository: monitoring/quay.io/prometheus/node-exporter

grafana:
  image:
    repository: harbor.domain.local/monitoring/docker.io/grafana/grafana
  initChownData:
    image:
      registry: harbor.domain.local
      repository: monitoring/docker.io/library/busybox
  sidecar:
    image:
      registry: harbor.domain.local
      repository: monitoring/quay.io/kiwigrid/k8s-sidecar
```

#### 3.3 Выполнение установки

```bash
helm install kps oci://${HARBOR}/helm/kube-prometheus-stack \
  -n monitoring \
  -f offline-values.yaml
```

#### 3.4 Валидация установки

```bash
# Проверка итоговой конфигурации всех образов в рендере
helm template kps oci://${HARBOR}/helm/kube-prometheus-stack -f offline-values.yaml | grep "image:" | sort -u

# Проверка статуса подов
kubectl get pods -n monitoring -w
# → Все поды должны перейти в состояние Running

# Проверка, что Prometheus получает метрики
kubectl port-forward -n monitoring svc/kps-kube-prometheus-kube-prome-prometheus 9090:9090 &
curl -s http://localhost:9090/api/v1/query?query=up | jq '.data.result[0].value'

# Проверка доступности реестра с узла (containerd)
crictl pull harbor.domain.local/monitoring/quay.io/prometheus/prometheus:v3.12.0

# Проверка CRD
kubectl get crd | grep monitoring.coreos.com
```

## Дополнительная информация

### Устранение неисправностей

| Симптом | Причина | Решение |
|:---|:---|:---|
| `ImagePullBackOff` | Образ не найден по указанному пути в Harbor | Проверьте вкладку Repositories в Harbor UI. Путь должен быть `monitoring/quay.io/...` |
| `x509: unknown authority` | Кластер не доверяет сертификату Harbor | Добавьте CA Harbor в `/etc/docker/certs.d/` или системное хранилище всех нод. |
| `Pending` поды (Webhook) | Проблема с `kube-webhook-certgen` | Убедитесь, что образ `ghcr.io/jkroepke/kube-webhook-certgen` зеркалирован. |
| Ошибка при `helm install` | Harbor OCI не авторизован в Helm | Выполните `helm login harbor.domain.local`. |
| Grafana не видит дашборды | Sidecar образ не загружен | Проверьте `grafana.sidecar.image` в `values.yaml`. |
| `CrashLoopBackOff` (Prometheus) | Неверный тег образа или отсутствие слоя | Проверьте digest образа через Harbor API: `curl /api/v2.0/projects/monitoring/repositories/.../artifacts/<tag>` |
| `CreateContainerConfigError` | Секрет `harbor-pull-secret` отсутствует в namespace | `kubectl get secret harbor-pull-secret -n monitoring` |
| `connection timed out` | NetworkPolicy блокирует доступ к Harbor | Разрешите egress на порт 443 для namespace `monitoring`. |
| `no such host` | Harbor не резолвится внутри кластера | Проверьте CoreDNS: `kubectl run dnstest --image=busybox --rm -it -- nslookup harbor.domain.local` |
| `manifest unknown` | Несовпадение digest после docker save/load | Используйте `cilium_deploy_with_digest: false` (Kubespray) или перезагрузите образ через skopeo. |
| `etcdserver: too large` | Helm Secret релиза превышает 1MB | Установите CRD отдельно (`kubectl apply -f crds/`) и используйте `--skip-crds` при установке. |
| `ImagePullBackOff` (pause) | Образ `pause` отсутствует в Harbor | Загрузите `registry.k8s.io/pause` в Harbor и перезапустите containerd. |

### Диагностика

```bash
# Проверка итоговой конфигурации всех образов в рендере
helm template kps oci://${HARBOR}/helm/kube-prometheus-stack -f offline-values.yaml | grep "image:" | sort -u

# Проверка статуса подов и причин ошибок загрузки
kubectl describe pod -n monitoring <pod-name> | grep -A 5 Events

# Проверка доступности реестра с узла (containerd/docker)
crictl pull harbor.domain.local/monitoring/quay.io/prometheus/prometheus:v3.12.0
```

### Очистка и откат

```bash
# Полный откат установки Helm-релиза
helm uninstall kps -n monitoring

# Удаление namespace (опционально)
kubectl delete namespace monitoring

# Откат значений к предыдущей версии
helm rollback kps 1 -n monitoring

# Очистка Harbor от тестовых артефактов
curl -sk -X DELETE -u "robot$monitoring:pull-push-token" \
  "https://harbor.domain.local/api/v2.0/projects/monitoring/repositories/quay.io/prometheus/prometheus/artifacts/<digest>"
```

### Рекомендации (Best Practices)

1. **Автоматизируйте извлечение:** Используйте скрипты для генерации `prom-images.txt`, чтобы не пропустить скрытые зависимости субчартов.
2. **Версионируйте бандлы:** Храните архивы `prom-images.tar` вместе с версией чарта для возможности быстрого отката в оффлайн-среде.
3. **Используйте Robot Accounts:** В Harbor создавайте Robot Accounts с правами `pull` для использования в `imagePullSecrets`. Никогда не используйте учётные данные реальных пользователей в автоматизации.
4. **Управление CRD:** В больших кластерах устанавливайте CRD отдельно (`kubectl apply -f crds/`), так как Helm может превысить лимит размера Secret при хранении релизов.
5. **Проверка DNS:** Убедитесь, что имя Harbor резолвится внутри подов кластера (настройка CoreDNS). Добавьте запись в `ConfigMap coredns` при необходимости.
6. **Immutable Tags:** Включите `Tag Immutability` в проекте Harbor, чтобы предотвратить случайную перезапись образов в production.
7. **Retention Policy:** Настройте автоматическую очистку старых тегов в Harbor для предотвращения переполнения диска.
8. **Предзагрузка pause:** Всегда загружайте `registry.k8s.io/pause` в локальный реестр и проверяйте его доступность перед установкой.
9. **Верификация артефактов:** Используйте `skopeo inspect` или `crane digest` для проверки контрольных сумм образов после загрузки.
10. **Мониторинг Harbor:** Настройте алерты на доступность Harbor и заполнение диска, так как его отказ парализует весь кластер.

### Граничные случаи

1. **K0s/K3s:** В легковесных дистрибутивах containerd может использовать другой путь сокета (`/run/k3s/containerd/containerd.sock`). Адаптируйте пути в диагностических командах.
2. **CRI-O вместо containerd:** Конфигурация реестрового маппинга выполняется через `/etc/containers/registries.conf`, а не `hosts.toml`.
3. **Harbor Proxy Cache:** Если кластер допускает ограниченный исходящий доступ, настройте Harbor в режиме Proxy Cache. Это снижает объём артефактов, требующих ручного переноса.
4. **Большие кластеры (>100 нод):** Используйте DaemonSet Image Puller для предварительной загрузки образов на все узлы, чтобы снизить нагрузку на Harbor при первом deploy.
5. **Helm release Secret size:** При установке через Helm с большим количеством CRD размер Secret релиза может превысить лимит `etcd` (1MB). Устанавливайте CRD отдельно.
6. **Сетевые политики (NetworkPolicy):** При включенном NetworkPolicy разрешите egress из namespace `monitoring` на порт 443 к Harbor и ingress от Harbor к kubelet.
7. **Сертификаты:** Self-signed CA Harbor должен быть добавлен в доверенное хранилище **каждого узла**, а не только в контейнеры. Проверяйте `update-ca-trust` (RHEL) или `update-ca-certificates` (Debian).
8. **imagePullPolicy:** Используйте `IfNotPresent` для пода Prometheus и `Never` только для DaemonSet Node Exporter после предварительной загрузки образов на все узлы.
9. **Версии чарта:** Убедитесь, что версия чарта и версия приложения (App Version) совместимы. При обновлении проверяйте release notes на предмет изменений в списке образов.
10. **Одновременный upgrade:** Не обновляйте более одного компонента стека одновременно в air-gapped среде — это усложняет откат при проблемах с образами.

### Связанные ресурсы

| Ресурс | Описание |
|:---|:---|
| [Harbor: Использование](../../../../Docker/Docker_registries/Harbor/usage.md) | Детальная настройка приватного реестра, Robot Accounts, OCI. |
| [Troubleshooting Image Pull](../../../../Kubernetes/Troubleshooting/Common_Errors/PodImagePullErrors/airgapped.md) | Отладка ошибок загрузки в оффлайн-средах. |
| [Online Installation](./online_installation.md) | Стандартная процедура для сравнения. |
