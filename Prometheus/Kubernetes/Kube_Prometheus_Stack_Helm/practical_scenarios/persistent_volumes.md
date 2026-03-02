# Настройка Persistent Volumes вручную

> [Назад к оглавлению](../practical_scenarios.md)

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
