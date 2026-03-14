# Оффлайн установка (Air-gapped)

> [Назад к оглавлению](../practical_scenarios.md)

> **См. также:** **[Kubespray: Offline установка](../../../../Kubernetes/Installation/Kubespray/offline_installation/offline_definitions.md)** — полное руководство по развертыванию Kubernetes в закрытом контуре с использованием Kubespray и Harbor.

## Этап 1: Подготовка образов (на хосте с интернетом)

**Скачивание чарта:**

```bash
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update
helm pull prometheus-community/kube-prometheus-stack --untar
cd kube-prometheus-stack
```

**Извлечение списка образов:**

```bash
helm template prometheus ../kube-prometheus-stack -f values.yaml > rendered.yaml
grep -oE 'image:\s*"?[^"]+' rendered.yaml | sed -E 's/^image:\s*"?//; s/"$//' | sort -u > prom-images.txt
```

**Загрузка образов:**

```bash
for img in $(cat prom-images.txt); do
  docker pull $img
done

# Дополнительные образы (при необходимости)
docker pull quay.io/prometheus-operator/prometheus-config-reloader:v0.89.0
docker pull docker.io/library/busybox:1.37.0

# Сохранение в архив
docker save -o prom-images.tar $(cat prom-images.txt)
```

**Упаковка чарта:**

```bash
cd ~
tar -cvf kube-prometheus-stack.tgz kube-prometheus-stack
```

## Этап 2: Загрузка в приватный репозиторий

**Загрузка образов:**

```bash
# На хосте в закрытом контуре
tar -xvf /home/admin/kube-prometheus-stack.tgz
mv kube-prometheus-stack/prom-images.t* ./
sudo docker load -i prom-images.tar

# Переменные для Harbor
export HARBOR="harbor.domain.local"
export PROJECT="monitoring"
docker login ${HARBOR}

# Push образов
while read -r img; do
  new="${HARBOR}/${PROJECT}/${img}"
  docker tag "${img}" "$new"
  docker push "$new"
done < prom-images.txt
```

**Push Helm-чарта:**

```bash
rm kube-prometheus-stack/rendered.yaml
helm package ./kube-prometheus-stack -d .
helm push kube-prometheus-stack*.tgz oci://harbor.domain.local/helm
```

## Этап 3: Установка в закрытом контуре

**Файл values.yaml для air-gapped:**

```yaml
crds:
  enabled: false

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

**Установка:**

```bash
helm install kube-prometheus-stack \
  oci://harbor.domain.local/helm/kube-prometheus-stack \
  -n monitoring --create-namespace -f values.yaml
```

**Диагностика:**

```bash
# Проверка pulling образов из интернета
helm template kps ../kube-prometheus-stack -f ../values.yaml | grep -i name_image

# Удаление при ошибке
helm uninstall kube-prometheus-stack -n monitoring
```
