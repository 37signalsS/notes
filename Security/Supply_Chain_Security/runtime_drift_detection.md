# Runtime SBOM drift detection

## Определения

* **SBOM Drift (Дрейф SBOM):** Расхождение между составом ПО, зафиксированным в SBOM на этапе сборки, и фактическим составом запущенного контейнера в рантайме. Возникает из-за динамической загрузки библиотек (`dlopen`), горячих патчей, монтирования томов или инъекций кода.
* **Runtime SBOM:** Снимок состава выполнения (loaded libraries, loaded modules) в работающем контейнере. Сравнивается с build-time SBOM для обнаружения аномалий.
* **eBPF (Extended Berkeley Packet Filter):** Технология ядра Linux, позволяющая безопасно выполнять пользовательский код в пространстве ядра для мониторинга syscall, загрузки библиотек и сетевых соединений.
* **Falco:** Open-source система обнаружения рантайм-угроз, использующая eBPF для мониторинга syscall и файловой системы.
* **Tetragon:** eBPF-инструмент от Cilium для отслеживания процессов, сетевых соединений и файловых операций на уровне ядра.

## Основные концепции

### Почему возникает drift

```
Build-time SBOM (этап сборки)
    │
    ├── Установлены: libA@1.0, libB@2.0, libC@3.0
    │
    ▼
Runtime (запущенный контейнер)
    │
    ├── libA@1.0, libB@2.0, libC@3.0  (ожидаемые)
    ├── libD@1.5  (загружена через dlopen)  ← DRIFT
    ├── libE@2.0  (монтирована с host)      ← DRIFT
    └── libA@1.1  (горячий патч)            ← DRIFT
```

**Типичные причины drift:**
1. **dlopen/dlsym:** Динамическая загрузка библиотек в рантайме (Java ClassLoader, Python importlib, Go plugin)
2. **Volume mounts:** Монтирование файлов с хоста (конфиги, скрипты, библиотеки)
3. **Init-контейнеры:** Установка дополнительных пакетов перед запуском основного контейнера
4. **Sidecar-контейнеры:** Соседние контейнеры с общими томами
5. **Hot patches:** Горячее обновление библиотек без пересборки образа
6. **Инъекции кода:** Внедрение вредоносного кода (attack vector)

### Стратегии обнаружения drift

| Стратегия | Инструмент | Принцип | Плюсы | Минусы |
| :--- | :--- | :--- | :--- | :--- |
| **eBPF syscall мониторинг** | Falco, Tetragon | Отслеживание `open`, `mmap`, `dlopen` | Мгновенное обнаружение, низкий overhead | Требует root/eBPF-доступ |
| **Сравнение fs с SBOM** | trivy diff | Сравнение файловой системы контейнера с SBOM | Простота | Не ловит динамические загрузки |
| **Process memory scan** | syft runtime | Анализ загруженных библиотек в памяти | Точность | Требует доступа к процессу |
| **Network monitoring** | Cilium, Tetragon | Обнаружение загрузки из внешних источников | Ловит download-атаки | Не ловит локальные инъекции |

## Практические сценарии

### Сценарий 1: Falco-правило для обнаружения dlopen

```yaml
# falco-rules.yaml: обнаружение загрузки незнакомых библиотек
- rule: Unexpected Library Load
  desc: >
    Обнаружена загрузка библиотеки, отсутствующей в SBOM.
    Может указывать на динамическую загрузку (legitimate) или инъекцию кода (attack).
  condition: >
    evt.type in (open, mmap) and
    evt.arg.flags contains PROT_EXEC and
    container and
    not proc.name in (expected_libraries)
  output: >
    Unexpected library loaded (user=%user.name container=%container.name
    image=%container.image.repository library=%fd.name)
  priority: WARNING
  tags: [supply_chain, drift, dlopen]
```

```bash
# Установка Falco
helm repo add falcosecurity https://falcosecurity.github.io/charts
helm install falco falcosecurity/falco \
  --namespace falco --create-namespace \
  --set driver.kind=ebpf \
  --set falcosidekick.enabled=true

# Проверка: загрузка библиотеки в контейнере
kubectl exec -it my-pod -- ldconfig -p | grep libssl
# → Falco алерт: Unexpected library load: libssl.so.3
```

### Сценарий 2: Tetragon для отслеживания загрузки файлов

```yaml
# tracing-policy.yaml: мониторинг открытия файлов .so в контейнерах
apiVersion: cilium.io/v1alpha1
kind: TracingPolicy
metadata:
  name: monitor-library-loading
spec:
  kprobes:
    - call: fd_install
      syscall: false
      args:
        - index: 1
          type: file
      selectors:
        - matchArgs:
            - index: 1
              operator: Prefix
              values:
                - /usr/lib/
                - /lib/
                - /app/lib/
          matchOps:
            - operator: In
              values:
                - fd_install
```

```bash
# Установка Tetragon
helm repo add cilium https://helm.cilium.io
helm install tetragon cilium/tetragon -n kube-system

# Просмотр событий загрузки библиотек
kubectl logs -n kube-system ds/tetragon -c export-stdout -f | \
  jq 'select(.process_kprobe.function == "fd_install") | {pod: .process.pod, file: .process_kprobe.args[0]}'
# → {"pod":"my-app-xyz","file":"/usr/lib/libssl.so.3"}
# → {"pod":"my-app-xyz","file":"/tmp/evil.so"}  ← DRIFT ALERT
```

### Сценарий 3: Сравнение runtime-SBOM с build-time SBOM

```bash
# 1. Генерация SBOM из запущенного контейнера (crictl)
# Требует доступ к узлу или debug-контейнер
crictl ps | grep my-app
# → CONTAINER ID   IMAGE          ...
# → abc123         harbor.internal/my-app:v1.2.3

# 2. Runtime SBOM через syft (с доступом к PID namespaces)
syft "containerd://abc123" -o cyclonedx-json > runtime-sbom.json

# 3. Build-time SBOM (эталонный)
syft harbor.internal/my-app:v1.2.3 -o cyclonedx-json > build-sbom.json

# 4. Сравнение
trivy diff sbom:./build-sbom.json sbom:./runtime-sbom.json
# → Total: 2 dependencies added, 0 removed, 1 changed.
#   + libD@1.5.0  (DRIFT: не было в build-time)
#   + libE@2.0.0  (DRIFT: не было в build-time)
#   ~ libA@1.0.0 → libA@1.1.0  (DRIFT: горячий патч)
```

### Сценарий 4: Автоматический drift detection в Kubernetes

```yaml
# CronJob: ежечасная проверка drift
apiVersion: batch/v1
kind: CronJob
metadata:
  name: sbom-drift-check
  namespace: security
spec:
  schedule: "0 * * * *"
  jobTemplate:
    spec:
      template:
        spec:
          serviceAccountName: sbom-checker
          containers:
            - name: drift-checker
              image: aquasec/trivy:0.55.0
              command:
                - /bin/sh
                - -c
                - |
                  # Получение списка всех подов в production
                  kubectl get pods -n production -o json | \
                  jq -r '.items[] | select(.status.phase == "Running") | "\(.metadata.name) \(.spec.containers[0].image)"' | \
                  while read pod image; do
                    echo "Checking $pod ($image)..."
                    
                    # Runtime SBOM
                    crictl ps --name $pod -q | xargs -I{} syft "containerd://{}" -o cyclonedx-json > /tmp/runtime-sbom.json
                    
                    # Build-time SBOM (из реестра)
                    syft $image -o cyclonedx-json > /tmp/build-sbom.json
                    
                    # Сравнение
                    drift=$(trivy diff sbom:/tmp/build-sbom.json sbom:/tmp/runtime-sbom.json -o json | jq '.total')
                    
                    if [ "$drift" -gt 0 ]; then
                      echo "DRIFT DETECTED in $pod: $drift changes"
                      # Алерт в Prometheus/Alertmanager
                      curl -X POST http://alertmanager:9093/api/v1/alerts -d '[{
                        "labels": {"alertname": "SBOMDrift", "pod": "'$pod'", "severity": "warning"},
                        "annotations": {"summary": "SBOM drift detected in '$pod'"}
                      }]'
                    fi
                  done
              volumeMounts:
                - name: docker-sock
                  mountPath: /var/run/docker.sock
          volumes:
            - name: docker-sock
              hostPath:
                path: /var/run/containerd/containerd.sock
          restartPolicy: OnFailure
```

### Сценарий 5: Правило для обнаружения монтирования подозрительных томов

```yaml
# Tetragon: мониторинг mount syscall
apiVersion: cilium.io/v1alpha1
kind: TracingPolicy
metadata:
  name: monitor-volume-mounts
spec:
  kprobes:
    - call: do_mount
      syscall: false
      args:
        - index: 0
          type: string
      selectors:
        - matchArgs:
            - index: 0
              operator: Prefix
              values:
                - /tmp/
                - /dev/shm/
```

## Лучшие практики

1. **Baseline SBOM:** Генерируйте SBOM при каждой сборке и храните как аттестацию. Это эталон для сравнения.
2. **eBPF-мониторинг в production:** Falco/Tetragon как DaemonSet — обязательный элемент observability.
3. **Автоматические алерты:** При обнаружении drift — алерт в Slack/PagerDuty с указанием pod, контейнера и типа drift.
4. **Блокировка подозрительных загрузок:** В Tetragon/MountOpts: block load from `/tmp/`, `/dev/shm/`, non-standard paths.
5. **Регулярное сравнение:** Ежечасное или ежедневное сравнение runtime-SBOM с build-time SBOM.
6. **Интеграция с admission control:** Kyverno может блокировать поды с volume mounts из неожиданных источников.

## Устранение неполадок

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| Falco не генерирует алерты | eBPF не поддерживается на узле | Проверьте: `ls /sys/kernel/tracing` и версию ядра >= 5.2 |
| syft не может прочитать контейнер | Нет доступа к PID namespaces | Используйте `crictl inspect` или debug-контейнер |
| trivy diff показывает false positives | Версии пакетов незначительно отличаются | Используйте `--ignore-unfixed` или расширенный матчинг |
| Tetragon: слишком много шума | Правило слишком широко | Сузьте `matchArgs.values` до конкретных путей |

## Граничные случаи и ограничения

* **Windows-контейнеры:** eBPF не работает в Windows. Для Windows-контейнеров используйте Process Monitor и Sysmon.
* **Безопасность eBPF:** eBPF-программы требуют `CAP_BPF` или root. В production ограничьте доступ через RBAC.
* **DinD (Docker-in-Docker):** В DinD-контейнерах мониторинг затруднён из-за изолированных namespace'ов. Используйте outer Docker socket.
* **Ресурсоёмкость:** Tetragon/Falco добавляют 2–5% overhead на CPU. Для высоконагруженных узлов — профилирование.

## Дополнительная информация

### Связанные документы

* [SBOM в продакшене](./sbom_in_production.md) — чтение SBOM, blast radius, VEX.
* [Анализ зависимостей и SBOM](./dependency_and_sbom_analysis.md) — генерация SBOM, SCA.
* [Целостность сборки](./build_integrity.md) — SLSA и воспроизводимость.
* [Реагирование на инциденты supply chain](./supply_chain_incident_response.md) — DFIR-процесс.
