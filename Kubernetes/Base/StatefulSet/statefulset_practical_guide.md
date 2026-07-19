# StatefulSet: Практическое руководство

## Определения

**StatefulSet: Практическое руководство** — прикладной справочник по развертыванию, настройке и эксплуатации контроллера StatefulSet в кластере Kubernetes. Руководство ориентировано на практическое применение механизмов стабильной идентификации и хранения данных.

Теоретическую базу и описание механизмов работы см. в **[StatefulSet: Обзор](./statefulset_overview.md)** и **[Ключевые концепции](./statefulset_core_concepts.md)**.

## Основные концепции

Для успешного выполнения практических заданий необходимо понимать роль следующих компонентов:

* **Headless Service:** Сервис без **IP (Internet Protocol)** кластера, отвечающий за создание индивидуальных записей в **DNS (Domain Name System)** для каждого пода.
* **PersistentVolumeClaim (PVC):** Декларативный запрос на выделение диска. В StatefulSet PVC генерируются автоматически для каждого индекса пода через шаблон `volumeClaimTemplates`.
* **Идентификация:** Каждый под получает стабильное имя формата `имя-sts-индекс` и **FQDN (Fully Qualified Domain Name)** формата `имя-пода.имя-сервиса.namespace.svc.cluster.local`.

Подробнее о сетевом взаимодействии: **[Headless Service](../../Networking/Service/service_type_headless.md)**.

## Практические сценарии

### Сценарий 1: Развертывание кластерного веб-сервера (Nginx)

Цель: запустить группу подов, где каждый экземпляр имеет собственную страницу `index.html`, сохраняющуюся после перезапуска.

#### Шаг 1: Создание сетевой инфраструктуры (Headless Service)

```yaml
apiVersion: v1
kind: Service
metadata:
  name: nginx-headless
spec:
  clusterIP: None
  selector:
    app: nginx-stateful
  ports:
  - port: 80
    name: web
```

#### Шаг 2: Создание контроллера StatefulSet

```yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: web-app
spec:
  serviceName: "nginx-headless"
  replicas: 3
  selector:
    matchLabels:
      app: nginx-stateful
  template:
    metadata:
      labels:
        app: nginx-stateful
    spec:
      containers:
      - name: nginx
        image: nginx:1.25.5
        volumeMounts:
        - name: data
          mountPath: /usr/share/nginx/html
  volumeClaimTemplates:
  - metadata:
      name: data
    spec:
      accessModes: ["ReadWriteOnce"]
      resources:
        requests:
          storage: 1Gi
```

#### Шаг 3: Проверка персистентности данных

1. Запишите данные в первый под:
    `kubectl exec web-app-0 -- sh -c 'echo "Pod 0 Data" > /usr/share/nginx/html/index.html'`
2. Удалите под:
    `kubectl delete pod web-app-0`
3. Проверьте данные после автоматического восстановления пода:
    `kubectl exec web-app-0 -- cat /usr/share/nginx/html/index.html`
    *Результат: Сообщение "Pod 0 Data" сохранено на диске.*

### Сценарий 2: Маршрутизация трафика на конкретный под через Ingress

В распределенных системах часто требуется обращение к конкретному узлу (например, для доступа к панели управления конкретной реплики).

1. **Создайте целевой сервис** для конкретного пода, используя метку `statefulset.kubernetes.io/pod-name`:

    ```yaml
    apiVersion: v1
    kind: Service
    metadata:
      name: web-app-0-direct
    spec:
      selector:
        statefulset.kubernetes.io/pod-name: web-app-0
      ports:
      - port: 80
    ```

2. **Настройте Ingress**, указав созданный сервис в качестве бэкенда. Это позволит обращаться к `web-app-0` по внешнему доменному имени.

### Сценарий 3: Масштабирование и проверка порядка операций

Наблюдайте за строгим порядком создания и удаления подов при изменении количества реплик:

* **Увеличение (Scale Up):** `kubectl scale statefulset web-app --replicas=5`
    *Поды создаются по одному: сначала 3, затем 4.*
* **Уменьшение (Scale Down):** `kubectl scale statefulset web-app --replicas=2`
    *Поды удаляются в обратном порядке: сначала 4, затем 3, затем 2.*

### Сценарий 4: Диагностика и устранение неполадок

Основные команды для поиска проблем в работе StatefulSet:

* **Проверка событий контроллера:** `kubectl describe statefulset web-app`. Помогает выявить ошибки квот или проблемы с созданием PVC.
* **Проверка статуса дисков:** `kubectl get pvc -l app=nginx-stateful`. Если PVC в статусе `Pending`, проверьте наличие доступных **PV (PersistentVolume)**.
* **Проверка сетевой доступности:** Запустите временный под и выполните `nslookup web-app-0.nginx-headless` для проверки работы DNS.

### Сценарий 5: Изменение размера диска (PVC) в StatefulSet

**Проблема:** Поля в `volumeClaimTemplates` иммутабельны. Простое изменение `storage: 2Gi` в манифесте и `kubectl apply` приведет к ошибке.

**Решение (Manual Resizing):**

1. **Обновите PVC:** Измените размер напрямую в объектах PVC (если StorageClass поддерживает `allowVolumeExpansion`):
   ```bash
   kubectl patch pvc data-web-app-0 -p '{"spec":{"resources":{"requests":{"storage":"2Gi"}}}}'
   ```
2. **Удалите StatefulSet (без подов):** Используйте режим `orphan`, чтобы поды продолжали работать:
   ```bash
   kubectl delete statefulset web-app --cascade=orphan
   ```
3. **Обновите манифест:** Измените размер в `volumeClaimTemplates` в вашем YAML-файле.
4. **Пересоздайте StatefulSet:**
   ```bash
   kubectl apply -f statefulset.yaml
   ```
   *Результат: StatefulSet подхватит работающие поды и PVC, а новые поды будут создаваться с увеличенным размером.*

## Дополнительная информация

### Рекомендации по эксплуатации

* Никогда не удаляйте PVC вручную, если планируете восстанавливать под с теми же данными.
* Используйте **[Лучшие практики](./statefulset_best_practices.md)** для настройки отказоустойчивости (PDB, Anti-Affinity).

### См. также

* **[Обзор StatefulSet](./statefulset_overview.md)** — основы и архитектура.
* **[Ключевые концепции](./statefulset_core_concepts.md)** — детальное описание механизмов.
* **[StatefulSet vs Deployment](./statefulset_vs_deployment.md)** — выбор подходящего контроллера.
