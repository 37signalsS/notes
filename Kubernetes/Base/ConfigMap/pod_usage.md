# Способы использования ConfigMap в подах

## Определения

**ConfigMap** — объект Kubernetes для хранения конфигурационных данных, которые могут быть использованы в подах через:

- Переменные окружения (`env`, `envFrom`)
- Смонтированные тома (`volume`)
- Projected volumes (комбинация источников)

## Основные концепции

### Двухэтапный процесс подключения ConfigMap

Подключение ConfigMap к поду состоит из двух обязательных этапов:

**Шаг 1. Объявление тома (Volumes)** — делаем ConfigMap доступным для пода в целом. В спецификации пода добавляется секция `volumes`, где создаётся том с именем (например, `nginx-config`) и указывается источник данных — ConfigMap по имени.

**Шаг 2. Монтирование тома (VolumeMounts)** — монтируем том в файловую систему конкретного контейнера. В секции `volumeMounts` внутри описания контейнера указывается:
- `name` — имя тома, объявленного на шаге 1
- `mountPath` — путь внутри контейнера, где будет доступен файл
- `subPath` (опционально) — какой именно ключ из ConfigMap монтировать

**Аналогия:** Процесс можно сравнить с подключением USB-флешки к компьютеру:
1. Сначала вы подключаете флешку к системе (Volumes)
2. Затем монтируете её в конкретную точку файловой системы (VolumeMounts)

### Сравнение способов использования

| Способ | Типичные случаи | Обновления | Особенности |
| :--- | :--- | :--- | :--- |
| **`env`/`envFrom`** | Флаги, небольшие параметры | **Не обновляются** автоматически | Простота, но требует рестарта Pod для новых значений |
| **`volume`** | Файлы конфигурации, ключи | **Обновляются** атомарно | Гибкое монтирование, позволяет обновлять конфиг на лету |
| **`subPath`** | Монтирование одного файла в существующую директорию | **Не обновляется** автоматически | Удобно, но блокирует автоматические обновления |
| **`projected`** | Сборка конфигурации из нескольких источников | **Обновляются**, как у `volume` | Единая точка монтирования для разных ресурсов |

## Практические сценарии

### Как переменные окружения (`env`, `envFrom`)

Подходит для передачи простых строковых значений в приложение.

```yaml
# ...
spec:
  containers:
    - name: my-app
      image: my-app:1.0.0
      env:
        # 1. Передать значение одного конкретного ключа
        - name: APP_COLOR_SETTING
          valueFrom:
            configMapKeyRef:
              name: app-config # Имя ConfigMap
              key: APP_COLOR    # Ключ, значение которого нужно взять
              optional: false   # Под упадет, если ConfigMap или ключ не найдены
      # 2. Передать все ключи из ConfigMap как переменные окружения
      envFrom:
        - configMapRef:
            name: app-config
            optional: true # Под запустится, даже если ConfigMap не найден
```

**Важно:** Переменные окружения читаются один раз при старте контейнера и не обновляются при изменении ConfigMap.

### Как файлы в томе (`volume`)

Это самый распространенный и мощный способ. ConfigMap монтируется как директория в файловую систему контейнера, где каждый ключ становится файлом.

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: nginx-pod
spec:
  containers:
    - name: nginx
      image: nginx:1.29.0
      volumeMounts:
        - name: config-volume
          mountPath: /etc/nginx/conf.d
  volumes:
    - name: config-volume
      configMap:
        name: app-config # Имя нашего ConfigMap
        defaultMode: 0660 # Права доступа к файлам по умолчанию
        items:
          - key: nginx.conf
            path: special_nginx.conf # Монтируем ключ nginx.conf в файл special_nginx.conf
```

Использование `items` позволяет гибко настраивать путь монтирования для каждого ключа.

**Важно:** Файлы в томе обновляются автоматически (с задержкой до 1 минуты), но приложение должно уметь перечитывать конфигурацию.

### Том с `subPath`

Используйте `subPath`, чтобы смонтировать только один файл из ConfigMap в конкретный путь, не скрывая остальное содержимое целевой директории.

**Двухэтапный процесс подключения ConfigMap:**

1. **Объявление тома (Volumes)** — делаем ConfigMap доступным для пода:
   ```yaml
   volumes:
     - name: nginx-config
       configMap:
         name: nginx-configmap
   ```

2. **Монтирование тома (VolumeMounts)** — монтируем в контейнер:
   ```yaml
   volumeMounts:
     - name: nginx-config
       mountPath: /etc/nginx/nginx.conf
       subPath: nginx.conf
   ```

**Полный пример Deployment с nginx:**

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: nginx-deployment
spec:
  template:
    spec:
      containers:
        - name: nginx
          image: nginx:1.29.0
          volumeMounts:
            - name: nginx-config
              mountPath: /etc/nginx/nginx.conf
              subPath: nginx.conf
      volumes:
        - name: nginx-config
          configMap:
            name: nginx-configmap
```

**Важно знать:**

1. Использование `subPath` имеет побочный эффект — **смонтированный файл перестает обновляться автоматически** при изменении ConfigMap.
2. При использовании `subPath` содержимое директории монтирования **не скрывается** — остальные файлы в ней остаются доступными.
3. Для применения изменений в ConfigMap при использовании `subPath` требуется **перезапуск пода** (`kubectl rollout restart deployment/...`).

### Projected том

Объединяет несколько источников в одну директорию.

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: app-projected
spec:
  containers:
  - name: app
    image: nginx
    volumeMounts:
    - name: all-in-one
      mountPath: /etc/app
      readOnly: true
  volumes:
  - name: all-in-one
    projected:
      sources:
      - configMap:
          name: app-config
      - secret:
          name: db-creds
```

При конфликте имен файлов приоритет имеет последний источник в списке `sources`.

> **Подробнее:** [Projected Volume в Pod Volumes](../Pod/volume_types/projected_volumes.md) — полное описание всех источников (secret, configMap, downwardAPI, serviceAccountToken, clusterTrustBundle, podCertificate) и практические примеры.

## Дополнительная информация

### Рекомендации

- **Для production** используйте `volume` с автоматическим [перезапуском подов](./update_and_rollout.md)
- **Для простых флагов** — `envFrom` с декларативным управлением
- **Для комбинации Secret + ConfigMap** — `projected` volumes
- **Избегайте `subPath`** если требуется автообновление конфигурации

### Связанные документы

- [Создание ConfigMap](./creation.md)
- [Обновление и rollout](./update_and_rollout.md)
- [Лучшие практики](./best_practices.md)
