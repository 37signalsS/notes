# Offline Air-gapped Installation (kube-prometheus-stack)

> [Назад к оглавлению](../overview.md)

> **SSoT для темы:** установка kube-prometheus-stack в изолированной среде без доступа к интернету.  
> **Смежные темы:** [Kubespray Offline Installation](../../../../Kubernetes/Installation/Kubespray/offline_installation/offline_definitions.md) — развёртывание самого Kubernetes в закрытом контуре; [Harbor Overview](../../../../Docker/Docker_registries/Harbor/overview.md) — приватный репозиторий; [Air-gapped Troubleshooting](../../../../Kubernetes/Troubleshooting/Common_Errors/PodImagePullErrors/airgapped.md) — диагностика проблем pull образов.

## Definitions

**Air-gapped кластер (Offline, закрытый контур)** — кластер Kubernetes, развёртываемый в изолированной среде без доступа к интернету. Все артефакты (образы контейнеров, Helm-чарты, бинарники) предварительно загружаются через съёмные носители или одноразовый канал передачи.

**Приватный репозиторий (Harbor)** — локальный Docker-registry, развёрнутый внутри закрытого контура. Служит источником образов для всех компонентов кластера. kube-prometheus-stack поддерживает настройку `global.imageRegistry` для перенаправления pull всех образов.

**Helm OCI registry** — механизм хранения Helm-чартов в OCI-совместимом репозитории (Harbor, Nexus). Позволяет выполнять `helm install` и `helm upgrade` из приватного источника без доступа к public репозиториям.

## Basic Concepts

### Архитектура air-gapped развёртывания

```
┌───────────────────────┐         Съёмный носитель        ┌──────────────────────────┐
│  Хост с интернетом    │  ──────────────────────────►    │  Хост в закрытом контуре  │
│  (download zone)      │    • prom-images.tar            │  (air-gapped zone)        │
│                       │    • kube-prometheus-stack.tgz  │                           │
│  1. pull образов      │                                 │  1. load образов           │
│  2. helm pull chart   │                                 │  2. push в Harbor          │
│  3. docker save       │                                 │  3. helm push chart (OCI)  │
└───────────────────────┘                                 └─────────────┬────────────┘
                                                                       │
                                                        ┌──────────────▼────────────┐
                                                        │  Kubernetes cluster       │
                                                        │  (air-gapped)             │
                                                        │                           │
                                                        │  Harbor ← pull образов     │
                                                        │  Helm install из OCI      │
                                                        └───────────────────────────┘
```

### Три этапа развёртывания

| Этап | Где | Что |
|---|---|---|
| **1. Подготовка артефактов** | Хост с доступом к интернету | Скачивание чарта, извлечение списка образов, `docker pull`, `docker save` |
| **2. Загрузка в приватный репозиторий** | Хост в закрытом контуре | `docker load`, `docker tag` → Harbor, `docker push`, `helm push` (OCI) |
| **3. Установка в кластер** | Хост в закрытом контуре (kubect) | `helm install` из OCI, `values.yaml` с `global.imageRegistry` |

### Ключевые отличия от online-установки

| Параметр | Online | Air-gapped |
|---|---|---|
| Источник чарта | `https://prometheus-community.github.io/helm-charts` | `oci://harbor.domain.local/helm/` |
| Источник образов | docker.io, quay.io, ghcr.io | `harbor.domain.local` |
| `global.imageRegistry` | Не требуется | Обязателен |
| `imagePullSecrets` | Не требуется | Обязателен (auth в Harbor) |
| CRD | `crds.enabled: true` (авто-создание) | `crds.enabled: false` (созданы заранее) или `true` при первом развёртывании |

## Practical Scenarios

### Этап 1: Подготовка образов (на хосте с интернетом)

#### 1.1 Скачивание чарта

```bash
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update
helm pull prometheus-community/kube-prometheus-stack --untar
cd kube-prometheus-stack
```

#### 1.2 Извлечение списка образов

```bash
helm template prometheus ../kube-prometheus-stack -f values.yaml > rendered.yaml
grep -oE 'image:\s*"?[^"]+' rendered.yaml | sed -E 's/^image:\s*"?//; s/"$//' | sort -u > prom-images.txt
```

> **Примечание:** `grep` может не захватить образы из subcharts (grafana-sidecar, busybox). Проверьте результат вручную.

#### 1.3 Загрузка и сохранение образов

```bash
# Pull всех образов
for img in $(cat prom-images.txt); do
  docker pull $img
done

# Дополнительные образы (могут отсутствовать в rendered.yaml)
docker pull quay.io/prometheus-operator/prometheus-config-reloader:v0.89.0
docker pull docker.io/library/busybox:1.37.0

# Сохранение в единый архив
docker save -o prom-images.tar $(cat prom-images.txt)
```

#### 1.4 Упаковка чарта

```bash
cd ~
tar -cvf kube-prometheus-stack.tgz kube-prometheus-stack
```

### Этап 2: Загрузка в приватный репозиторий (Harbor)

#### 2.1 Загрузка образов на air-gapped хост

```bash
# На хосте в закрытом контуре
tar -xvf /home/admin/kube-prometheus-stack.tgz
mv kube-prometheus-stack/prom-images.tar ./
sudo docker load -i prom-images.tar
```

#### 2.2 Push образов в Harbor

```bash
# Переменные
export HARBOR="harbor.domain.local"
export PROJECT="monitoring"
docker login ${HARBOR}

# Tag + Push
while read -r img; do
  new="${HARBOR}/${PROJECT}/${img}"
  docker tag "${img}" "$new"
  docker push "$new"
done < prom-images.txt
```

#### 2.3 Push Helm-чарта в OCI registry

```bash
rm kube-prometheus-stack/rendered.yaml
helm package ./kube-prometheus-stack -d .
helm push kube-prometheus-stack*.tgz oci://harbor.domain.local/helm
```

### Этап 3: Установка в закрытом контуре

#### 3.1 Создание imagePullSecret

```bash
# Secret для аутентификации в Harbor
kubectl create secret docker-registry harbor-pull-secret \
  -n monitoring \
  --docker-server=harbor.domain.local \
  --docker-username=<user> \
  --docker-password=<password>
```

#### 3.2 Файл values.yaml для air-gapped

```yaml
crds:
  enabled: true  # false если CRD созданы заранее

global:
  imageRegistry: "harbor.domain.local"
  imagePullSecrets:
    - name: harbor-pull-secret

prometheusOperator:
  image:
    registry: harbor.domain.local
    repository: monitoring/quay.io/prometheus-operator/prometheus-operator
  admissionWebhooks:
    patch:
      enabled: true
      image:
        registry: harbor.domain.local
        repository: monitoring/ghcr.io/jkroepke/kube-webhook-certgen
  prometheusConfigReloader:
    image:
      registry: harbor.domain.local
      repository: monitoring/quay.io/prometheus-operator/prometheus-config-reloader

prometheus:
  prometheusSpec:
    image:
      registry: harbor.domain.local
      repository: monitoring/quay.io/prometheus/prometheus
    storageSpec:
      volumeClaimTemplate:
        spec:
          storageClassName: longhorn
          accessModes: ["ReadWriteOnce"]
          resources:
            requests:
              storage: 10Gi
  ingress:
    enabled: true
    ingressClassName: nginx
    annotations:
      nginx.ingress.kubernetes.io/backend-protocol: "HTTP"
    hosts:
      - prometheus.k8s.domain.local
    paths:
      - /
    pathType: Prefix

alertmanager:
  alertmanagerSpec:
    image:
      registry: harbor.domain.local
      repository: monitoring/quay.io/prometheus/alertmanager

kube-state-metrics:
  image:
    registry: harbor.domain.local
    repository: "monitoring/registry.k8s.io/kube-state-metrics/kube-state-metrics"

prometheus-node-exporter:
  image:
    registry: harbor.domain.local
    repository: "monitoring/quay.io/prometheus/node-exporter"

grafana:
  image:
    repository: monitoring/docker.io/grafana/grafana
  ingress:
    enabled: true
    ingressClassName: nginx
    annotations:
      nginx.ingress.kubernetes.io/backend-protocol: "HTTP"
    hosts:
      - grafana.k8s.domain.local
    path: /
    pathType: Prefix
  persistence:
    enabled: true
    storageClassName: longhorn
    size: 5Gi
  initChownData:
    enabled: true
    image:
      registry: harbor.domain.local
      repository: monitoring/docker.io/library/busybox
  sidecar:
    image:
      registry: harbor.domain.local
      repository: monitoring/quay.io/kiwigrid/k8s-sidecar
```

> **Важно:** Пути `repository` включают префикс исходного registry (`quay.io/`, `docker.io/`) как часть имени проекта в Harbor. Это сохраняет совместимость с оригинальными путями образов.

#### 3.3 Установка

```bash
helm install kube-prometheus-stack \
  oci://harbor.domain.local/helm/kube-prometheus-stack \
  -n monitoring --create-namespace -f values.yaml
```

## Additional Information

### Troubleshooting

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `ImagePullBackOff` на поде | Образ отсутствует в Harbor или неверный путь | Проверить `kubectl describe pod` → exact image path; сверить с Harbor |
| `ErrImagePull` — unauthorized | imagePullSecret не настроен или неверен | Проверить `kubectl get secret harbor-pull-secret -n monitoring`; `kubectl describe pod` |
| `helm install` — chart not found | OCI chart не запушен или неверный URL | `helm search repo` для локальных; проверить `helm push` в Harbor UI |
| CRD не созданы | `crds.enabled: false`, но CRD отсутствуют | Создать CRD вручную из `crds/` директории чарта или установить `crds.enabled: true` |
| Подвисание pod'ов | DNS недоступен для внешних registry | Убедиться, что все образы в Harbor; проверить `/etc/resolv.conf` в подах |
| Grafana sidecar не загружает дашборды | `k8s-sidecar` образ не в Harbor | Проверить `grafana.sidecar.image.registry` и `repository` в values.yaml |

### Диагностика

```bash
# Проверка, что все образы указывают на Harbor
helm template kps ../kube-prometheus-stack -f values.yaml | grep -i 'image:' | sort -u

# Проверка pulling образов из кластера
kubectl get pods -n monitoring -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.status.containerStatuses[*].image}{"\n"}{end}'

# Проверка ImagePullSecrets
kubectl get serviceaccount -n monitoring default -o jsonpath='{.imagePullSecrets}'

# Удаление при ошибке
helm uninstall kube-prometheus-stack -n monitoring
kubectl delete namespace monitoring

# Проверка доступности Harbor из кластера
kubectl run test-pull --image=harbor.domain.local/monitoring/quay.io/prometheus/prometheus --rm -it --restart=Never -- sh
```

### Best Practices

1. **Автоматизируйте извлечение образов** — `helm template | grep image` может пропустить субчарты. Сравнивайте результат с полным списком из `values.yaml` чарта.
2. **Версионирование артефактов** — сохраняйте `prom-images.txt` и `kube-prometheus-stack.tgz` с версией чарта в Git/архив для воспроизводимости.
3. **Harbor project = monitoring** — выделяйте отдельный проект в Harbor для мониторинга; это упрощает управление правами и rotation credentials.
4. **CRD создавайте отдельно** — для production рекомендуется `crds.enabled: false` и отдельный pipeline для обновления CRD (чтобы `helm upgrade` не удалял кастомные ресурсы).
5. **Тестируйте на staging до air-gapped** — развёртывание с `global.imageRegistry` можно протестировать в online-среде, указав `imageRegistry` на Harbor с доступом из интернета.
6. **Обновление версий** — при обновлении kube-prometheus-stack повторяйте все 3 этапа; проверяйте changelist образов (новые/удалённые образы в новой версии чарта).

### Связанные ресурсы

| Ресурс | Описание |
|---|---|
| [Kubespray Offline Installation](../../../../Kubernetes/Installation/Kubespray/offline_installation/offline_definitions.md) — развёртывание самого Kubernetes в закрытом контуре |
| [Harbor Overview](../../../../Docker/Docker_registries/Harbor/overview.md) — приватный Docker registry |
| [Air-gapped Image Pull Troubleshooting](../../../../Kubernetes/Troubleshooting/Common_Errors/PodImagePullErrors/airgapped.md) — диагностика `ImagePullBackOff` |
| [Online Installation](./online_installation.md) — стандартная установка с доступом к интернету |
