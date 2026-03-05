# Конфигурация Karma

Конфигурация для Karma очень проста. Нужно лишь указать адрес Alertmanager.

**`karma-config.yaml`**

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: karma-config
  namespace: monitoring
data:
  config.yaml: |
    alertmanager:
      servers:
        - name: "Kubernetes"
          uri: "http://alertmanager.monitoring.svc.cluster.local:9093"
          
    # Фильтрация и отображение
    labels:
      # Не показывать эту метку в UI
      strip: ["receiver"] 
```

## Смотрите также

- [Karma Deployment](./07-karma-deployment.md) — развертывание пода
- [Alertmanager](./05-alertmanager-statefulset.md) — источник алертов
