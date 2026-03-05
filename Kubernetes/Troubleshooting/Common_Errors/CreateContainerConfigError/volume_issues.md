# CreateContainerConfigError: Проблемы с томами

## 1. Проблемы с Projected Volume

**Сообщение:**

```
Error: projected volume error: configmap "cm1" not found
```

**Причина:** Projected volume объединяет несколько источников, один из которых отсутствует.

**Решение:**

```yaml
# Проверка всех источников в projected volume
volumes:
- name: all-in-one
  projected:
    sources:
    - configMap:
        name: app-config  # ✅ Существует?
    - secret:
        name: db-credentials  # ✅ Существует?
    - downwardAPI:
        items:
        - path: "labels"
          fieldRef:
            fieldPath: metadata.labels
```

## 2. Проблемы с томами emptyDir

**Сообщение:**

```
Error: failed to create emptyDir volume "cache": quota exceeded
```

**Причина:** Превышен лимит на `emptyDir` или ResourceQuota.

**Решение:**

```yaml
# Указание sizeLimit для emptyDir
volumes:
- name: cache
  emptyDir:
    sizeLimit: 1Gi  # Ограничение размера
```
