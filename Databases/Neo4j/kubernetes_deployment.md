# Neo4j: Развёртывание в Kubernetes

**Актуально для:** Neo4j 2026.09.x / 5.26.x LTS

## Определения

| Термин | Значение |
| :--- | :--- |
| **Neo4j Helm chart** | Официальный способ запуска Neo4j в Kubernetes; заменил charts проекта Neo4j Labs. |
| **Chart version** | Версия чарта: `2026.9.0`. **App version** — версия образа: `2026.09.0`. Форматы различаются. |
| **Standalone / cluster release** | Один инстанс или кластер, описанный одним Helm-релизом. |
| **Volume mount** | Точка монтирования тома в контейнер: `/data`, `/logs`, `/backups`, `/import`, `/licenses`, `/metrics`. |
| **StorageClass** | Класс хранилища в Kubernetes, по которому PV provisioner создаёт динамический том. |
| **Online maintenance** | Обслуживание работающего Neo4j через `kubectl exec`. |
| **Offline maintenance** | Обслуживание с остановленным процессом Neo4j; под остаётся, но никогда не становится READY. |
| **Command expansion** | Механизм подстановки параметров конфигурации в строку запуска; требует флага `--expand-commands`. |

## Базовые понятия: три особенности чарта

### Конфигурация задаётся в values.yaml, а не в neo4j.conf

**Neo4j Helm chart не использует файл `neo4j.conf`.** Конфигурация задаётся в `values.yaml` объектом `config` — это строковая карта «имя настройки `neo4j.conf` → значение».

```yaml
# Neo4j configuration (yaml format)
config:
 server.metrics.enabled: "true"
 server.metrics.csv.interval: "10s"
```

Два требования к формату:

- **все значения — строки YAML**, кавычки обязательны: `"true"`, `"false"`, `"2"`, иначе значение будет разобрано как другой тип YAML и не применится как ожидается;
- поддерживаются все настройки `neo4j.conf`, **кроме `server.jvm.additional`**.

JVM-аргументы задаются отдельным объектом `jvm` списком:

```yaml
# Jvm configuration for Neo4j
jvm:
 additionalJvmArguments:
 - "-XX:+HeapDumpOnOutOfMemoryError"
 - "-XX:HeapDumpPath=/logs/neo4j.hprof"
```

Обратите внимание на путь дампа: в контейнере `/logs` — точка монтирования volume, а не `/var/lib/neo4j/logs`.

### Две версии: чарта и образа

Версия чарта и версия образа записываются по-разному, и это регулярный источник ошибок:

| Что | Формат | Пример |
| :--- | :--- | :--- |
| Chart version | `YYYY.M.P` | `2026.9.0` |
| App version (образ) | `YYYY.MM.P` | `2026.09.0` |
| Тег образа Enterprise | с суффиксом | `2026.09.0-enterprise` |
| Тег образа Community | с суффиксом | `2026.09.0-community` |
| Тег образа LTS | версия LTS | `5.26.30-enterprise` |

Официальный образ подставляется чартом автоматически по версии самого чарта; переопределить его можно через `image.customImage`.

### Память: heap + page cache + запас

Контейнер настроен так, чтобы Neo4j использовал предоставленную память: `server.memory.heap.initial_size` и `server.memory.pagecache.size` **в сумме не должны превышать память контейнера**. В Kubernetes процесс, вышедший за лимит памяти контейнера, убивается операционной системой, поэтому рекомендуется оставить **дополнительно 1 ГБ запаса**:

> `heap + pagecache + 1GB < доступная память`

Минимальные значения для инстанса Neo4j — **0.5 CPU и 2 ГБ памяти**. Helm проверяет это при установке и завершается ошибкой при заниженных значениях:

```plain
Error: template: neo4j-standalone/templates/_helpers.tpl:157:11:
executing "neo4j.resources.evaluateCPU" at <fail ...>:
error calling fail: Provided cpu value 0.25 is less than minimum.
 cpu value cannot be less than 0.5 or 500m
```

### Хранилище: тип тома определяет пригодность

Чарт создаёт volume mounts: `/backups`, `/data`, `/import`, `/licenses`, `/logs`, `/metrics` (Community Edition метрики не генерирует). Volume `/plugins` задать можно, но по умолчанию чарт его не создаёт.

Для **объёма `/data`** поддерживаются только:

- `persistentVolumeClaim`;
- `hostPath` — при работе с Docker Desktop.

**`azureFile` и `nfs` для `/data` не поддерживаются.** Типы `awsElasticBlockStore`, `azureDisk`, `gcePersistentDisk` объявлены устаревшими в Kubernetes, и чарт их больше не поддерживает — для перехода следует использовать CSI-драйверы, см. документацию вендора Kubernetes.

`hostPath`, `local` и `emptyDir` показывают хорошие результаты при подходящем хранилище (например, SSD), но имеют эксплуатационные ограничения и **не рекомендуются**. Использование HDD или облачного хранилища, смонтированного как диск, также не рекомендуется. Для остальных volume mounts, кроме `/data`, обычно подходит любой тип PV.

По умолчанию все монтирования обслуживаются **одним** PV с именем `data`. Выбор тома задаётся объектом `volumes.<имя>`; поддерживаемые режимы: `dynamic`, `share`, `defaultStorageClass`, `volume`, `selector`, `volumeClaimTemplate`. Для режимов `dynamic`, `defaultStorageClass`, `selector` и `volumeClaimTemplate` можно задать метки при создании и использовать их для отбора PV. По умолчанию том `/logs` использует том `/data` (режим `share`).

## Практические сценарии

### Подготовка репозитория чартов

**Требования (Prerequisites):** Helm v3, `kubectl` с `kubeconfig`, доступ к кластеру Kubernetes и права на создание `StatefulSet`/`Service`/`Secret`/`PersistentVolumeClaim`/`ServiceAccount`. Для динамического PV нужен **StorageClass** в кластере (или подготовленный вручную PV).Чарт не требует привилегированного доступа, но создаёт `ServiceAccount` для подов, которым нужен доступ к API Kubernetes (например, для чтения секретов `apoc_credentials`).

```bash
helm repo add neo4j https://helm.neo4j.com/neo4j
helm repo update
helm search repo neo4j/ --versions | grep 2026.9.0
```

```plain
neo4j/neo4j 2026.9.0 2026.09.0 Neo4j is the world's leading graph database
neo4j/neo4j-admin 2026.9.0 2026.09.0 Neo4j is the world's leading graph database
neo4j/neo4j-headless-service 2026.9.0 - Neo4j is the world's leading graph database
neo4j/neo4j-loadbalancer 2026.9.0 - Neo4j is the world's leading graph database
neo4j/neo4j-persistent-volume 2026.9.0 - Sets up persistent disks suitable for a Neo4j H...
neo4j/neo4j-reverse-proxy 2026.9.0 2026.09.0 Sets up an http server and a reverse proxy for ...
```

Служебные чарты `neo4j/neo4j-docker-desktop-pv` и `neo4j/neo4j-persistent-volume` — альтернативный способ создать PV в соответствующих окружениях.

### Минимальный standalone с динамическим PV

```yaml
# values.yaml
neo4j:
  name: standalone-with-storage-class
  resources:
    requests:
      cpu: "1000m"
      memory: "2Gi"
    limits:
      cpu: "2000m"
      memory: "5Gi"

# Neo4j configuration (yaml format)
config:
  server.memory.heap.initial_size: "3G"
  server.memory.heap.max_size: "3G"
  server.memory.pagecache.size: "1G"

volumes:
  data:
    labels:
      data: "true"
    mode: dynamic
    dynamic:
      storageClassName: "neo4j-data"
      requests:
        storage: 10Gi
  logs:
    mode: "share"
    share:
      data: true
```

```bash
helm install neo4j-standalone neo4j/neo4j --version 2026.9.0 -f values.yaml
kubectl get pods
# → NAME                                READY   STATUS    RESTARTS   AGE
#   neo4j-standalone-0                  1/1     Running   0          2m
```

Если блок `requests`/`limits` не задан, значения из объекта `resources` используются и для requests, и для limits одновременно:

```yaml
neo4j:
  resources:
    cpu: "2"
    memory: "5Gi"
```

### Обслуживание: онлайн

Онлайн-обслуживание не требует остановки процесса Neo4j и выполняется через `kubectl exec`.

**Все команды `neo4j-admin` в контейнере требуют флага `--expand-commands`:** чарт задаёт конфигурацию Neo4j через подстановку в команде, которая разрешается в рантайме.

```bash
# Разовая команда
kubectl exec neo4j-standalone-0 -- neo4j-admin database info \
  --from-path=/var/lib/neo4j/data/databases --expand-commands
```

```bash
# Интерактивная оболочка для серии команд
kubectl exec -it neo4j-standalone-0 -- bash
```

Ограничение, о котором стоит помнить: **процессы, запущенные через `kubectl exec`, учитываются в лимите памяти контейнера.** Задача, потребляющая заметную память, или очень жёсткий лимит памяти могут привести к тому, что операционная система убьёт контейнер с Neo4j.

### Обслуживание: офлайн

В офлайн-режиме процесс Neo4j не работает. Под продолжает работать, но никогда не достигает статуса READY.

```yaml
# values.yaml
neo4j:
  offlineMaintenanceModeEnabled: true
```

```bash
helm upgrade neo4j-standalone neo4j/neo4j -f values.yaml
# Либо одной командой:
helm upgrade neo4j-standalone neo4j/neo4j --version=2026.9.0 --reuse-values \
  --set neo4j.offlineMaintenanceModeEnabled=true
```

Дождаться перезапуска и убедиться, что JVM не запущен:

```bash
kubectl get pod neo4j-standalone-0
kubectl exec -it neo4j-standalone-0 -- bash
# $ jps
# → 19 Jps
```

Единственный java-процесс — сам `jps`: это подтверждение, что Neo4j остановлен и можно работать с файлами.

Долгие команды в офлайн-режиме запускают через `nohup`, чтобы они пережили обрыв `kubectl exec`:

```bash
kubectl exec -it neo4j-standalone-0 -- bash
# $ nohup neo4j-admin database check neo4j --expand-commands &>job.out </dev/null &
# $ tail -f job.out
```

Возврат в рабочий режим — тем же `helm upgrade` со снятым флагом:

```bash
helm upgrade neo4j-standalone neo4j/neo4j --reuse-values \
  --set neo4j.offlineMaintenanceModeEnabled=false
```

### Обновление версии

Версия образа задаётся в `values.yaml`, применяется через `helm upgrade`:

```yaml
image:
  customImage: neo4j:2026.09.0-enterprise
```

```bash
helm upgrade neo4j-standalone neo4j/neo4j -f values.yaml
```

Переход с Community на Enterprise:

```bash
helm upgrade neo4j-standalone neo4j/neo4j --reuse-values \
  --set neo4j.edition=enterprise --set neo4j.acceptLicenseAgreement=yes
```

Пошаговые инструкции для standalone и для rolling-обновления кластера находятся в Upgrade and Migration Guide — общие соображения по обновлению версий разобраны в [обновлении и миграции](./upgrade_and_migration.md).

### Безопасность и hardening пода

Чарт по умолчанию запускает под без root и с минимальными привилегиями. Это реализуется двумя объектами `securityContext` — на уровне пода и контейнера.Первая величина — `uid`/`gid` Neo4j (`7474`), вторая — `fsGroup`, которому принадлежит PV, чтобы Neo4j мог писать в volume `chmod`/`chown` применяется к владельцу.

```yaml
# values.yaml
neo4j:
  securityContext:
    runAsNonRoot: true
    runAsUser: 7474
    runAsGroup: 7474
    fsGroup: 7474
    fsGroupChangePolicy: "Always"
  containerSecurityContext:
    runAsNonRoot: true
    runAsUser: 7474
    runAsGroup: 7474
    capabilities:
      drop: ["ALL"]
  serviceAccountName: ""
```

Дополнительные меры SRE:

- **Image pull** — `imagePullPolicy: IfNotPresent` по умолчанию; для production-образов используйте `IfNotPresent` и pinned-тег (`2026.09.0-enterprise`), а для private registry — `imagePullSecrets` с `docker-registry` (см. таблицу операций).
- **ReadOnly root** — корень контейнера можно сделать только для чтения; Neo4j пишет только в подмонтированные volume (`/data`, `/logs`), так что `readOnlyRootFilesystem: true` совместим и устраняет кишщу для злоумышленника.
- **NetworkPolicy** — ограничьте вход на `7474`/`7473`/`7687` только драйверами и LB; chart-сервисы `default`/`neo4j` получают `type: LoadBalancer` — замените на `ClusterIP`+Ingress, если доступ извне не нужен.

### Жизненный цикл пода

Грейсфул шатдаун важен: Neo4j сбрасывает in-memory данные на диск при завершении, поэтому чарт ставит **`terminationGracePeriodSeconds: 3600`** (1 час) — лимит не побуждает K8s SIGKILL-нуть процесс до завершения flush.

- **Probes** — `readiness`/`liveness`/`startup` жмут на `tcpSocket` порт `7687`. Пороги выбраны специально: `failureThreshold: 40` (`periodSeconds: 5`) ≈ **10 минут** для liveness, чтобы длительные GC-паузы (см. [JVM-диагностика](./jvm_diagnostics.md)) не вызывали перезапуск, и `startupProbe` с `failureThreshold: 1000` — чтобы дать кластеру время сформироваться и восстановиться после restore. Не уменьшайте их без анализа GC-пауз.
- **PodDisruptionBudget** — выключен по умолчанию (`podDisruptionBudget.enabled: false`). Для кластера включите и задайте `minAvailable: <N-1>` или `maxUnavailable`, иначе `kubectl drain` может вывести все члены кластера.
- **Password recovery** — первоначальный пароль `neo4j` хранится в Secret `<release-name>-auth` (ключ `NEO4J_AUTH`). Восстановить:

```bash
kubectl get secret neo4j-standalone-auth -oyaml | yq -r '.data.NEO4J_AUTH' | base64 -d
```

### Прочие операции чарта

| Задача | Страница документации |
| :--- | :--- |
| Масштабирование | [Scale a Neo4j deployment](https://neo4j.com/docs/operations-manual/current/kubernetes/operations/scaling/) |
| Назначение подов узлам | [Assign Neo4j pods to specific nodes](https://neo4j.com/docs/operations-manual/current/kubernetes/operations/assign-neo4j-pods/) |
| Образы из приватного реестра | [Use custom images from private registries](https://neo4j.com/docs/operations-manual/current/kubernetes/operations/image-pull-secret/) |
| Сброс пароля `neo4j` | [Reset the neo4j user password](https://neo4j.com/docs/operations-manual/current/kubernetes/operations/reset-password/) |
| Перезапуск пода после смены конфигурации | [Restart a Neo4j pod after a configuration change](https://neo4j.com/docs/operations-manual/current/kubernetes/operations/restart-pod/) |
| Дамп и загрузка баз (офлайн) | [Dump and load databases](https://neo4j.com/docs/operations-manual/current/kubernetes/operations/dump-load/) |
| Бэкап и восстановление одной базы (онлайн) | [Back up and restore a single database](https://neo4j.com/docs/operations-manual/current/kubernetes/operations/backup-restore/) |
| Миграция с Labs-чартов | [Migrate from the Labs Helm charts](https://neo4j.com/docs/operations-manual/current/kubernetes/operations/migrate-from-labs/) |
| Импорт данных | [Importing data](https://neo4j.com/docs/operations-manual/current/kubernetes/import-data/) |
| Плагины (APOC, GDS) | [Plugins](https://neo4j.com/docs/operations-manual/current/kubernetes/plugins/) |
| Мониторинг | [Monitoring](https://neo4j.com/docs/operations-manual/current/kubernetes/monitoring/) |
| Диагностика | [Troubleshooting](https://neo4j.com/docs/operations-manual/current/kubernetes/troubleshooting/) |

## Устранение неполадок

| Проблема | Симптом | Причина | Решение |
| :--- | :--- | :--- | :--- |
| Helm падает на `evaluateCPU` | `Provided cpu value 0.25 is less than minimum` | Ресурс ниже минимума 0.5 CPU | Поднять `neo4j.resources.cpu`; тот же порог действует для памяти в 2 ГБ |
| Под убит с exit code 137 | `OOMKilled` | `heap + pagecache` слишком близки к лимиту, либо память съела задача через `kubectl exec` | Оставить запас 1 ГБ; тяжёлые задачи из контейнера выносить |
| Настройка из `config` не применяется | Значение осталось прежним | Значение не в кавычках и разобралось как не строка | Обернуть все значения `config` в кавычки |
| `server.jvm.additional` игнорируется | JVM-флаг не виден в процессе | Эта настройка не поддерживается в объекте `config` | Перенести флаги в `jvm.additionalJvmArguments` списком |
| `neo4j-admin` не запускается в контейнере | Ошибка разбора параметров | Забыт `--expand-commands` | Добавить флаг |
| Данные не переживают пересоздание пода | Потеря графа | Использован `emptyDir` или не тот PV | Перейти на `persistentVolumeClaim` с отдельным StorageClass |
| Под `0/1` неделю, `helm upgrade` завершился | Нет READY | Включён офлайн-режим обслуживания | Проверить `offlineMaintenanceModeEnabled`; `jps` в поде покажет, запущен ли JVM |
| Медленный запуск или OOM при монтировании | Высокая нагрузка на PVC | NFS или `azureFile` для `/data` | Эти типы для `/data` не поддерживаются; перейти на CSI-блочное хранилище |
| После `helm upgrade` пароль перестал работать | Ошибка аутентификации | Учётные данные не заданы в values | Задать `neo4j.password`; либо сбросить пароль отдельной операцией |

## Лучшие практики

- **Используйте только `neo4j/neo4j` чарт.** Labs-чарты — предшественник, миграция документирована отдельно.
- **Держите запас памяти в 1 ГБ** сверх heap + page cache, иначе OOM Kill придёт на ровном месте.
- **Все значения `config` — строки в кавычках.** Это не стилистика, а условие применения настройки.
- **JVM-флаги — только через `jvm.additionalJvmArguments`.**
- **Разделяйте `/data` и `/logs` на разные PV**, если хотите независимое масштабирование: по умолчанию `/logs` делит том с `/data`.
- **Пользуйтесь `persistentVolumeClaim` с выделенным StorageClass** для `/data`, а не `hostPath`, `local` или `emptyDir`.
- **Плановое обслуживание — через offline maintenance mode**, а не через `kubectl exec` с тяжёлыми командами.
- **Длинные офлайн-команды запускайте через `nohup`** с выводом в файл: разрыв `kubectl exec` не должен убивать задачу.
- **Фиксируйте тег образа явно** (`2026.09.0-enterprise` или `5.26.30-enterprise`) при обновлении, полагаясь только на версию чарта трудно аудировать.

## Дополнительная информация

- **[Документация: Kubernetes](https://neo4j.com/docs/operations-manual/current/kubernetes/)** — оглавление раздела: quickstart для standalone, кластера и аналитического кластера, volume mounts, кастомизация, SSL, аутентификация, плагины, доступ, Ingress, импорт, мониторинг, операции.
- **[Neo4j Helm charts](https://github.com/neo4j/helm-charts)** — исходный код чартов.
- **[Репозиторий чартов](https://helm.neo4j.com/neo4j)** — источник для `helm repo add`.
- **[StatefulSet: ключевые концепции](../../Kubernetes/Base/StatefulSet/statefulset_core_concepts.md)** — почему под Neo4j это StatefulSet, а не Deployment.
- **[StatefulSet: лучшие практики](../../Kubernetes/Base/StatefulSet/statefulset_best_practices.md)** — PDB, обновление, сеть.
- **[Kubernetes: устранение неполадок](../../Kubernetes/Troubleshooting/troubleshooting_overview.md)** — общий порядок диагностики.
- **[Kubernetes: CrashLoopBackOff](../../Kubernetes/Troubleshooting/Common_Errors/pod_crash_loop_back_off/common_cases_and_solutions.md)** — OOMKilled и чтение логов подов.

## См. также

- **[Установка и настройка](./installation_and_setup.md)** — Docker и Docker Compose, начальная конфигурация, hardening.
- **[Диагностика на уровне JVM](./jvm_diagnostics.md)** — heap, GC, off-heap и лимиты контейнера.
- **[Кластеризация и высокая доступность](./clustering.md)** — топология, маршрутизация, Raft.
- **[Мониторинг и логи](./monitoring.md)** — метрики, которые стоит собирать с подов.
- **[Массовый импорт](./bulk_import.md)** — начальная загрузка и её особенности в контейнере.