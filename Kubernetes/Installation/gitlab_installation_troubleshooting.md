# Решение проблем при установке GitLab в Kubernetes

Руководство по диагностике и устранению типичных ошибок, возникающих при развертывании GitLab через официальный Helm-чарт.

---

## Определения

| Термин | Описание |
|--------|----------|
| **PVC Pending** | Состояние запроса на хранилище (PersistentVolumeClaim), при котором Kubernetes не может найти или создать подходящий физический том (PV). |
| **StorageClass** | Объект Kubernetes, описывающий "классы" хранилищ и позволяющий динамически создавать тома. |
| **Default StorageClass** | Класс хранилища, используемый автоматически, если в запросе PVC явно не указано имя `storageClassName`. |
| **OOM (Out Of Memory)** | Ошибка, возникающая при нехватке оперативной памяти для запуска или работы контейнера. |

---

## Основные концепции

### Проблемы развертывания GitLab

GitLab является ресурсоемким приложением (Stateful), состоящим из множества связанных компонентов. Основные сложности при установке связаны с:

1. **Динамическим выделением томов**: Большинство компонентов (PostgreSQL, Gitaly, Redis) требуют постоянного хранилища.
2. **Высокими требованиями к ресурсам**: По умолчанию чарт запрашивает значительные лимиты CPU и RAM, что может привести к невозможности размещения подов на узлах.
3. **Очисткой состояния**: При неудачной установке и повторном запуске старые секреты или PVC могут вызвать конфликты.

---

## Практические сценарии

### Проблемы с хранилищем (PVC Pending)

**Симптом:** Поды GitLab остаются в статусе `Pending`, а связанные с ними PVC — в статусе `Pending`.

**Причина 1: Отсутствие StorageClass по умолчанию**
Если в кластере нет Default StorageClass, чарт GitLab не сможет автоматически выделить место.

```bash
# Проверка наличия класса по умолчанию (ищите метку (default))
kubectl get storageclass

# Назначение существующего класса (например, 'nfs') классом по умолчанию
kubectl patch storageclass nfs \
  -p '{"metadata": {"annotations": {"storageclass.kubernetes.io/is-default-class": "true"}}}'
```

**Причина 2: Конфликты при переустановке**
Helm не удаляет PVC автоматически при выполнении `helm uninstall`.

```bash
# Полная очистка перед повторной установкой
helm uninstall gitlab -n gitlab
kubectl delete pvc --all -n gitlab
```

### Настройка размеров томов для тестов

По умолчанию GitLab запрашивает около 80 ГБ дискового пространства. Для тестовых сред это можно уменьшить через `values.yaml`.

**Минимальный файл конфигурации для экономии места:**

```yaml
# test-values.yaml
postgresql:
  primary:
    persistence:
      size: 2Gi
minio:
  persistence:
    size: 5Gi
redis:
  master:
    persistence:
      size: 1Gi
global:
  gitaly:
    persistence:
      size: 5Gi
prometheus:
  install: false # Отключение для экономии ресурсов
```

### Нехватка ресурсов (CPU/RAM)

**Симптом:** Поды не запускаются, в `describe pod` видна ошибка `Insufficient cpu` или `Insufficient memory`.

**Диагностика:**

```bash
# Проверка нагрузки на узлы
kubectl top nodes

# Просмотр событий пода для подтверждения нехватки ресурсов
kubectl describe pod <pod_name> -n gitlab | grep -A 5 Events
```

**Решение:** Добавьте ресурсы в кластер или уменьшите `requests` в `values.yaml` (не рекомендуется для production).

---

## Дополнительная информация

### См. также

- [Установка GitLab через Helm](./gitlab_kubernetes_helm_installation.md)
- [Методы доступа к GitLab](./gitlab_kubernetes_access.md)
- [Диагностика статуса Pending в Kubernetes](../Troubleshooting/Common_Errors/pod_pending/diagnostics.md)
