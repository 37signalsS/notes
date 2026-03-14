# Pod Image Pull Errors: Air-gapped кластеры

## 7. Air-gapped кластеры (offline)

**Проблема:** Нет доступа к внешним registry.

**Решение:**

### Шаг 1: Скачать образы на машине с доступом

```bash
docker pull my-app:1.0
docker save -o my-app.tar my-app:1.0
```

### Шаг 2: Передать в offline-кластер

```bash
scp my-app.tar offline-node:
```

### Шаг 3: Загрузить в локальный registry

```bash
docker load -i my-app.tar
docker tag my-app:1.0 local-registry:5000/my-app:1.0
docker push local-registry:5000/my-app:1.0
```

### Использование в манифесте

```yaml
containers:
- name: app
  image: local-registry:5000/my-app:1.0
imagePullPolicy: IfNotPresent  # Использовать локальный кэш
```

> **Полное руководство:** См. **[Kubespray: Offline установка](../../../Installation/Kubespray/offline_installation/offline_definitions.md)** — комплексное руководство по развертыванию Kubernetes в закрытом контуре с использованием Kubespray и Harbor.

> **См. также:** [`../../../Prometheus/kubernetes/Kube_Prometheus_Stack_Helm/practical_scenarios/offline_airgapped_installation.md`](../../../Prometheus/kubernetes/Kube_Prometheus_Stack_Helm/practical_scenarios/offline_airgapped_installation.md)
