# Netdata: Мониторинг в реальном времени

## 1. Определения

**Netdata** — это высокопроизводительная система для мониторинга производительности систем и приложений в реальном времени. Её ключевое отличие от систем вроде Prometheus — это предоставление метрик с детализацией **до секунды** и готовые, интерактивные дашборды, не требующие настройки.

Netdata идеально подходит для:
*   Отладки производительности в реальном времени.
*   Анализа проблем во время нагрузочного тестирования.
*   Быстрого получения обзора состояния хоста или контейнера.

## 2. Основные концепции

### Архитектура в Kubernetes

При установке в Kubernetes через официальный Helm-чарт, Netdata развертывается по следующей модели:

*   **Parent `Deployment`**: Один главный под, который агрегирует данные от всех дочерних агентов и предоставляет централизованный пользовательский интерфейс. Он хранит исторические данные в `PersistentVolume`.
*   **Child `DaemonSet`**: На каждом узле кластера запускается под-агент, который собирает метрики с данного хоста (CPU, память, диски, сеть) и из `cgroups` запущенных контейнеров.
*   **Service Discovery**: Дочерние агенты автоматически обнаруживают родительский под и начинают отправлять ему метрики.

### Преимущества и недостатки

**Преимущества:**
*   **Реальное время:** Данные обновляются каждую секунду.
*   **Авто-обнаружение:** Netdata автоматически обнаруживает и начинает мониторить сотни сервисов и приложений.
*   **Нулевая конфигурация:** Готовые дашборды доступны сразу после установки.
*   **Низкое потребление ресурсов:** Агенты очень легковесны.

**Недостатки:**
*   **Дашборды:** Встроенные дашборды негибкие и практически не поддаются кастомизации, в отличие от Grafana.
*   **Долгосрочное хранение:** Хотя Netdata может хранить историю, для долгосрочного анализа и агрегации метрик лучше использовать Prometheus. Netdata может выступать как источник метрик для Prometheus.

## 3. Практические сценарии

### 3.1. Установка через Helm

Netdata рекомендуется устанавливать с помощью официального Helm-чарта.

**Шаг 1: Добавление репозитория**

```bash
helm repo add netdata https://netdata.github.io/helmchart/
helm repo update
```

**Шаг 2: Отладка и кастомизация (`--dry-run`)**

Перед установкой полезно посмотреть, какие манифесты сгенерирует Helm, и переопределить значения по умолчанию. Для этого используется флаг `--dry-run`.

```bash
helm install netdata netdata/netdata 
  --namespace monitoring 
  --set image.pullPolicy=IfNotPresent 
  --set parent.database.storageClass=managed-nfs-storage 
  --set child.resources.requests.cpu=100m 
  --set parent.resources.limits.memory=1Gi 
  --set ingress.enabled=false 
  --dry-run --debug
```
*   `--dry-run --debug`: Сгенерировать и вывести итоговые YAML-манифесты без их применения в кластере. Это позволяет проверить конфигурацию перед установкой.

**Шаг 3: Установка релиза**

Убираем флаги `--dry-run --debug` и запускаем установку.

```bash
helm install netdata netdata/netdata 
  --namespace monitoring 
  --create-namespace 
  --set image.pullPolicy=IfNotPresent 
  --set parent.database.storageClass=managed-nfs-storage 
  --set child.resources.requests.cpu=100m 
  --set parent.resources.limits.memory=1Gi 
  --set ingress.enabled=false
```
*   `ingress.enabled=false`: Мы отключаем создание Ingress-ресурса по умолчанию, чтобы настроить его вручную с нужными TLS-сертификатами (см. сценарий интеграции с `cert-manager`).
*   `parent.database.storageClass`: Указываем `StorageClass` для `PersistentVolume`, где будут храниться исторические данные.

**Шаг 4: Доступ к интерфейсу через Ingress**

После установки создайте `Ingress`-ресурс для доступа к родительскому поду Netdata.

```yaml
# netdata-ingress.yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: netdata-ingress
  namespace: monitoring
  annotations:
    cert-manager.io/issuer: "kubernetes-ca-issuer" # Интеграция с cert-manager
spec:
  ingressClassName: system-ingress
  tls:
  - hosts:
    - netdata.k8s.local
    secretName: internal-services-secret # Секрет, созданный cert-manager
  rules:
  - host: netdata.k8s.local
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: netdata # Сервис, созданный Helm-чартом
            port:
              name: http
```

### 3.2. Удаление Netdata

Удаление релиза выполняется одной командой. Helm автоматически удалит все связанные ресурсы (`Deployment`, `DaemonSet`, `Service`, `PVC` и т.д.).

```bash
helm uninstall netdata -n monitoring
```
> **Примечание:** `PersistentVolume` может быть не удален, если его `reclaimPolicy` установлена в `Retain`.

## 4. Дополнительная информация

*   **Метрики для Prometheus:** Netdata может отдавать метрики в формате Prometheus. Это настраивается в `values.yaml` Helm-чарта.
*   [Документация по Helm-чарту Netdata](https://github.com/netdata/helmchart)
