# Установка в закрытом контуре (Air-gapped)

> [Назад к оглавлению](../overview.md)

> **SSoT для темы:** установка kube-prometheus-stack в изолированной среде без доступа к интернету.  
> **Смежные темы:** [Kubespray: Offline установка](../../../../Kubernetes/Installation/Kubespray/offline_installation/offline_definitions.md) — развёртывание базовой инфраструктуры кластера; [Обзор Harbor](../../../../Docker/Docker_registries/Harbor/overview.md) — использование приватного реестра; [Диагностика загрузки образов](../../../../Kubernetes/Troubleshooting/Common_Errors/PodImagePullErrors/airgapped.md) — решение типичных проблем в изоляции.

## Определения

**Air-gapped кластер (Закрытый контур)** — среда Kubernetes, полностью изолированная от публичных сетей. Все артефакты (Docker-образы, Helm-чарты, бинарные файлы) должны быть доставлены на физических носителях или через защищённые шлюзы.

**Приватный реестр (Harbor/Nexus)** — внутренний сервис хранения и дистрибуции образов. В оффлайн-установке он становится единственным источником данных для кластера.

**OCI (Open Container Initiative)** — стандарт, позволяющий использовать Docker-реестры для хранения не только образов, но и Helm-чартов. Это основной метод дистрибуции чартов в современных закрытых контурах.

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

## Практические сценарии

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

### Шаг 2: Загрузка в приватный репозиторий (Harbor)

#### 2.1 Импорт образов

На машине внутри закрытого контура, имеющей доступ к Harbor:

```bash
tar -xvzf kube-prometheus-stack-bundle.tar.gz
docker load -i prom-images.tar
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

#### 2.3 Пуш чарта в OCI-хранилище

```bash
helm package ./kube-prometheus-stack
helm push kube-prometheus-stack-*.tgz oci://${HARBOR}/helm
```

### Шаг 3: Установка в закрытом контуре

#### 3.1 Создание секрета для Pull образов

```bash
kubectl create namespace monitoring
kubectl create secret docker-registry harbor-pull-secret \
  -n monitoring \
  --docker-server=${HARBOR} \
  --docker-username=<user> \
  --docker-password=<password>
```

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

## Дополнительная информация

### Устранение неисправностей

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `ImagePullBackOff` | Образ не найден по указанному пути в Harbor | Проверьте вкладку Repositories в Harbor UI. Путь должен быть `monitoring/quay.io/...` |
| `x509: unknown authority` | Кластер не доверяет сертификату Harbor | Добавьте CA Harbor в `/etc/docker/certs.d/` или системное хранилище всех нод. |
| `Pending` поды (Webhook) | Проблема с `kube-webhook-certgen` | Убедитесь, что образ `ghcr.io/jkroepke/kube-webhook-certgen` зеркалирован. |
| Ошибка при `helm install` | Harbor OCI не авторизован в Helm | Выполните `helm login harbor.domain.local`. |
| Grafana не видит дашборды | Sidecar образ не загружен | Проверьте `grafana.sidecar.image` в `values.yaml`. |

### Диагностика

```bash
# Проверка итоговой конфигурации всех образов в рендере
helm template kps oci://${HARBOR}/helm/kube-prometheus-stack -f offline-values.yaml | grep "image:" | sort -u

# Проверка статуса подов и причин ошибок загрузки
kubectl describe pod -n monitoring <pod-name> | grep -A 5 Events

# Проверка доступности реестра с узла (containerd/docker)
crictl pull harbor.domain.local/monitoring/quay.io/prometheus/prometheus:v3.12.0
```

### Рекомендации (Best Practices)

1. **Автоматизируйте извлечение:** Используйте скрипты для генерации `prom-images.txt`, чтобы не пропустить скрытые зависимости субчартов.
2. **Версионируйте бандлы:** Храните архивы `prom-images.tar` вместе с версией чарта для возможности быстрого отката в оффлайн-среде.
3. **Используйте Robot Accounts:** В Harbor создавайте Robot Accounts с правами `pull` для использования в `imagePullSecrets`.
4. **Управление CRD:** В больших кластерах устанавливайте CRD отдельно (`kubectl apply -f crds/`), так как Helm может превысить лимит размера Secret при хранении релизов.
5. **Проверка DNS:** Убедитесь, что имя Harbor резолвится внутри подов кластера (настройка CoreDNS).

### Связанные ресурсы

| Ресурс | Описание |
|---|---|
| [Kubespray: Offline установка](../../../../Kubernetes/Installation/Kubespray/offline_installation/offline_definitions.md) | Подготовка базового кластера в изоляции. |
| [Harbor: Использование](../../../../Docker/Docker_registries/Harbor/usage.md) | Детальная настройка приватного реестра. |
| [Troubleshooting Image Pull](../../../../Kubernetes/Troubleshooting/Common_Errors/PodImagePullErrors/airgapped.md) | Отладка ошибок загрузки в оффлайн-средах. |
| [Online Installation](./online_installation.md) | Стандартная процедура для сравнения. |
