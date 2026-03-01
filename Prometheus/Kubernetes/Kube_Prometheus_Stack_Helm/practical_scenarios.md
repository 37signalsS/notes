# kube-prometheus-stack: Практические сценарии

## Определения

**Онлайн установка** — стандартный метод развертывания стека мониторинга с прямым доступом к публичным Helm-репозиториям и контейнерным реестрам.

**Оффлайн установка (Air-gapped)** — метод развертывания в изолированных средах без доступа к интернету, требующий предварительной загрузки образов и чартов в приватный репозиторий.

## Основные концепции

### Выбор метода установки

| Критерий | Онлайн | Оффлайн |
| :--- | :--- | :--- |
| Доступ к интернету | Требуется | Не требуется |
| Требования | Helm, K8s cluster, Ingress (опционально) | Хост с интернетом, Harbor/Nexus, Longhorn/NFS |
| Сложность | Низкая | Высокая |
| Время развертывания | 5-10 минут | 30-60 минут |

## Практические сценарии

### Онлайн установка

#### Шаг 1: Подключение репозитория

```bash
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update
```

#### Шаг 2: Создание values.yaml (опционально)

При наличии Ingress создаётся файл конфигурации с параметрами доступа:

```yaml
prometheus:
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

grafana:
  ingress:
    enabled: true
    ingressClassName: nginx
    annotations:
      nginx.ingress.kubernetes.io/backend-protocol: "HTTP"
    hosts:
      - grafana.k8s.domain.local
    path: /
    pathType: Prefix
```

#### Шаг 3: Установка

**Без values.yaml:**

```bash
helm install kps prometheus-community/kube-prometheus-stack \
  -n monitoring --create-namespace
```

**С values.yaml:**

```bash
helm install kps prometheus-community/kube-prometheus-stack \
  -n monitoring --create-namespace -f values.yaml
```

#### Шаг 4: Доступ к веб-интерфейсам

**Через Ingress:**

- `http://grafana.k8s.domain.local`
- `http://prometheus.k8s.domain.local`

**Через port-forward (без Ingress):**

```bash
# Grafana
kubectl --namespace monitoring port-forward svc/kube-prometheus-grafana 3000:80

# Prometheus
kubectl --namespace monitoring port-forward svc/kube-prometheus-kube-prome-prometheus 9090:9090
```

**Получение пароля Grafana:**

```bash
kubectl -n monitoring get secret kube-prometheus-grafana \
  -o jsonpath='{.data.admin-password}' | base64 -d; echo
```

Логин: `admin`

---

### Оффлайн установка (Air-gapped)

#### Этап 1: Подготовка образов (на хосте с интернетом)

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

#### Этап 2: Загрузка в приватный репозиторий

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

#### Этап 3: Установка в закрытом контуре

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

---

### Настройка мониторинга внешних ресурсов (static_configs)

Позволяет добавлять кастомные `scrape_configs` напрямую в конфигурацию Prometheus. Это основной способ настроить мониторинг целей, которые находятся **вне Kubernetes** (виртуальные машины, физические серверы).

* **Пример:** Мониторинг внешнего хоста с `node-exporter`.

    ```yaml
    prometheus:
      prometheusSpec:
        additionalScrapeConfigs:
          - job_name: 'external-nodes'
            static_configs:
              - targets: ['192.168.1.100:9100', '192.168.1.101:9100']
                labels:
                  env: 'production'
    ```

### Обогащение метрик `node-exporter`

Позволяет определить специфичные для `node-exporter` правила `relabeling` для обогащения метрик.

* **Пример:** Добавление читаемого имени узла в метрики.

    ```yaml
    prometheus:
      prometheusSpec:
        scrapeClasses:
          - name: node-exporter
            relabelingConfigs:
              - sourceLabels: [__meta_kubernetes_pod_node_name]
                targetLabel: node
                action: replace
    ```

### Сбор метрик с master-нод

Позволяет подам Node Exporter размещаться на master-нодах, которые по умолчанию имеют `taint` (например, `NoSchedule`).

* **Рекомендация:** Добавить `toleration`, чтобы собирать метрики со всех узлов кластера.

    ```yaml
    nodeExporter:
      tolerations:
        - operator: "Exists"
          effect: "NoSchedule"
    ```

### Настройка Persistent Volumes (PV) вручную

Если ваш `StorageClass` не поддерживает динамическое создание томов (dynamic provisioning), вам потребуется создать PersistentVolume вручную. Это актуально, например, при использовании `local-storage`.

* **Пример манифеста PV:**

    ```yaml
    apiVersion: v1
    kind: PersistentVolume
    metadata:
      name: pv-prometheus-1
    spec:
      capacity:
        storage: 5Gi
      accessModes:
        - ReadWriteOnce
      storageClassName: local-storage
      local:
        path: /mnt/local-pv-1 # Путь на хостовой машине, который должен существовать
      nodeAffinity:
        required:
          nodeSelectorTerms:
            - matchExpressions:
                - key: kubernetes.io/hostname
                  operator: In
                  values:
                    - node-1 # Имя ноды, на которой будет использоваться PV
    ```

    **Важно:** Перед применением манифеста необходимо убедиться, что директория, указанная в `local.path`, существует на соответствующей ноде. **Не забудьте создать эти директории на целевых узлах кластера перед применением PV-манифестов.**

### Авторизация в веб-интерфейсе

1. **Через Ingress:** Исторически доступ к интерфейсу Prometheus защищался через Basic Auth на уровне Ingress. Это позволяет настроить окно ввода логина и пароля при доступе к Prometheus через Ingress.
2. **Закрытый контур:** Не выставлять Prometheus наружу, держать его в закрытых контурах с подключением через VPN. Это наиболее безопасный вариант, но не всегда возможный.
3. **Нативная авторизация Prometheus:** В новых версиях Prometheus появилась **нативная поддержка Basic Auth**, которую можно настроить непосредственно в конфигурации самого Prometheus. Это более современный и безопасный способ. Также появилась возможность авторизации по TLS-сертификатам. Подробности можно можно найти в `release notes` соответствующей версии Prometheus.
