# Пример установки Prometheus в Kubernetes с помощью Helm

Этот документ содержит конкретный пример установки Prometheus в Kubernetes с использованием Helm-чарта `stable/prometheus-operator`.

> **Важно:** Текущий стенд не предназначен к выполнению текущих инструкций. Информация предоставляется просто к сведению. Также стоит отметить, что репозиторий `stable` для Helm устарел, и для новых установок рекомендуется использовать чарт `kube-prometheus-stack` из репозитория `prometheus-community`. Тем не менее, общие принципы настройки через `values.yaml` остаются схожими.

## 1. Авторизация Prometheus в Kubernetes

Чтобы Prometheus мог собирать метрики с `kubelet`, ему необходима авторизация по токену. Для этого на всех мастер-нодах необходимо добавить следующие флаги в конфигурационный файл kubelet (например, `/etc/kubernetes/kubelet.env`):

```
--authentication-token-webhook \
--authorization-mode=Webhook
```

## 2. Установка через Helm

В данном примере используется хранение постоянных данных (persistent data) на `cephFS`.

### 2.1 Создание Namespace

Сначала создадим отдельное пространство имен для компонентов мониторинга:

```bash
kubectl create namespace monitoring
```

### 2.2 Подготовка `values.yaml`

Чтобы настроить установку, необходимо получить стандартный файл `values.yaml` и внести в него изменения.

```bash
helm inspect values stable/prometheus-operator > values.yml
```

**Основные изменения в `values.yml`:**
*   Задать пароль администратора для Grafana.
*   Выключить анонимный доступ.
*   Включить Ingress-ресурсы для Grafana, Alertmanager и Prometheus.
*   Настроить basic-аутентификацию для доступа к Alertmanager и Prometheus.
*   Настроить Persistent Volume Claims для Alertmanager и Prometheus, используя `cephfs-provisioner`.

**Создание секрета для Basic Auth:**
```bash
htpasswd -c auth admin
kubectl create secret generic admin-basic-auth --from-file=auth --namespace=monitoring
```

**Пример изменений в `values.yaml`:**

```yaml
alertmanager:
  ingress:
    enabled: true
    annotations:
      nginx.ingress.kubernetes.io/auth-type: basic
      nginx.ingress.kubernetes.io/auth-secret: admin-basic-auth
      nginx.ingress.kubernetes.io/auth-realm: "Authentication Required - foo" 
    hosts:
      - alertmanager.k8s.example.com
  storage:
    volumeClaimTemplate:
      spec:
        storageClassName: cephfs-provisioner
        accessModes: ["ReadWriteOnce"]
        resources:
          requests:
            storage: 10Gi
      selector: {}

grafana:
  adminPassword: "topsecret" 
  ingress:
    enabled: true
    annotations:
      kubernetes.io/ingress.class: nginx
      kubernetes.io/tls-acme: "true" 
    hosts:
      - "grafana-k8s.example.com" 
    tls:
      - secretName: grafana-k8s-example-com-tls
        hosts:
          - grafana.k8s.example.com

prometheus:
  ingress:
    enabled: true
    annotations:
      nginx.ingress.kubernetes.io/auth-type: basic
      nginx.ingress.kubernetes.io/auth-secret: admin-basic-auth
      nginx.ingress.kubernetes.io/auth-realm: "Authentication Required - foo" 
    hosts:
      - prometheus.k8s.example.com
  storageSpec:
    volumeClaimTemplate:
      spec:
        storageClassName: cephfs-provisioner
        accessModes: ["ReadWriteOnce"]
        resources:
          requests:
            storage: 10Gi
      selector: {}
```

### 2.3 Установка Prometheus

После подготовки `values.yaml` можно установить Prometheus:

```bash
helm install stable/prometheus-operator --name prometheus --namespace monitoring -f values.yaml
```

---
**Связанные темы:**
*   [[./setup.md]]
*   [[./helm_chart_configuration.md]]
*   [[./operator.md]]
