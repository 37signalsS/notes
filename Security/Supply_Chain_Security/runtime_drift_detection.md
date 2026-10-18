# Runtime SBOM drift detection

**Актуально для:** Trivy ≥ 0.71.0, Syft v1.54+, CycloneDX CLI 2.0+, Falco (eBPF driver), Tetragon (Cilium)

## Определения

* **SBOM Drift (Дрейф SBOM):** Расхождение между составом ПО, зафиксированным в SBOM на этапе сборки, и фактическим составом запущенного контейнера в рантайме. Возникает из-за динамической загрузки библиотек (`dlopen`), горячих патчей, монтирования томов или инъекций кода.
* **Runtime SBOM:** Снимок состава выполнения (loaded libraries, loaded modules) в работающем контейнере. Сравнивается с build-time SBOM для обнаружения аномалий.
* **eBPF (Extended Berkeley Packet Filter):** Технология ядра Linux, позволяющая безопасно выполнять пользовательский код в пространстве ядра для мониторинга syscall, загрузки библиотек и сетевых соединений.
* **Falco:** Open-source система обнаружения рантайм-угроз, использующая eBPF для мониторинга syscall и файловой системы.
* **Tetragon:** eBPF-инструмент от Cilium для отслеживания процессов, сетевых соединений и файловых операций на уровне ядра.
* **CycloneDX CLI:** Инструмент командной строки для анализа SBOM: сравнение (`diff`), конвертация форматов, валидация. Доступен на GitHub: `CycloneDX/cyclonedx-cli`.
* **crictl:** CLI-интерфейс для CRI-совместимых runtime (containerd, CRI-O). Используется для получения метаданных о работающих контейнерах и их корневых файловых систем.

## Предпосылки

Перед внедрением runtime drift detection необходимо:

1. **Контроллерный узел с eBPF:** ядро Linux ≥ 5.2, поддержка eBPF (проверить: `ls /sys/kernel/btf/vmlinux`).
2. **Доступ к runtime:** `crictl` или `containerd` CLI с правами на чтение метаданных контейнеров (обычно через `hostPath` монтирование сокета runtime или через service account с нужными RBAC).
3. **Build-time SBOM:** SBOM в формате CycloneDX или SPDX, сгенерированный при сборке (Syft, Trivy, или другим генератором) и сохранённый в артефакт-реестр (Harbor, GitLab Package Registry, Artifactory).
4. **Сервисный аккаунт:** `ServiceAccount` с `ClusterRole` для чтения pods, `pods/exec`, и `nodes` (для доступа к `/proc` или runtime socket).
5. **Сканер образов:** Trivy ≥ 0.71.0 и Syft v1.54+ установлены на управляющем узле или доступны через контейнерные образы.

## Установка и настройка

### Falco

```bash
# Установка через Helm
helm repo add falcosecurity https://falcosecurity.github.io/charts
helm install falco falcosecurity/falco \
  --namespace falco --create-namespace \
  --set driver.kind=ebpf \
  --set falcosidekick.enabled=true

# Проверка статуса
kubectl -n falco get pods
# → NAME                          READY   STATUS    RESTARTS   AGE
# → falco-5d4b8f7c9d-xk2m4        2/2     Running   0          1m
```

### Tetragon

```bash
# Установка через Helm
helm repo add cilium https://helm.cilium.io
helm install tetragon cilium/tetragon -n kube-system

# Проверка: Tetragon требует Cilium/CNI или standalone режим
kubectl -n kube-system get ds tetragon
# → NAME       DESIRED   CURRENT   READY   AGE
# → tetragon   1         1         1       1m
```

### CycloneDX CLI

```bash
# Установка через Homebrew (macOS)
brew install cyclonedx/cyclonedx-cli/cyclonedx-cli

# Установка через curl (Linux/macOS)
curl -sSfL https://raw.githubusercontent.com/CycloneDX/cyclonedx-cli/master/scripts/baseline.sh | bash

# Проверка
cyclonedx-cli version
# → CycloneDX CLI version 2.0.0
```

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
| **Сравнение SBOM** | cyclonedx-cli, jq | Сравнение runtime-SBOM с build-time SBOM | Простота, нетребуем доп. зависимостей | Не ловит динамические загрузки в памяти |
| **Process memory scan** | syft runtime | Анализ загруженных библиотек в памяти | Точность | Требует доступа к процессу |
| **Network monitoring** | Cilium, Tetragon | Обнаружение загрузки из внешних источников | Ловит download-атаки | Не ловит локальные инъекции |

## Практические сценарии

### Сценарий 1: Falco-правило для обнаружения загрузки библиотек через mmap

```yaml
# falco-rules.yaml: обнаружение загрузки незнакомых библиотек
# Определяем список ожидаемых путей к библиотекам
- list: expected_library_paths
  items: ["/usr/lib/", "/usr/lib64/", "/lib/", "/lib64/", "/usr/local/lib/"]

- rule: Unexpected Library Load
  desc: >
    Обнаружено mmap с PROT_EXEC для файла, не входящего в ожидаемые пути.
    Может указывать на динамическую загрузку библиотек (legitimate)
    или инъекцию кода (attack).
  condition: >
    container and
    evt.type in (mmap, mmap2) and
    evt.arg.flags contains PROT_EXEC and
    not fd.name pmresolution in (expected_library_paths)
  output: >
    Unexpected executable memory mapping (user=%user.name container=%container.name
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
# → Falco алерт: Unexpected executable memory mapping: /usr/lib/x86_64-linux-gnu/libssl.so.3
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
        - index: 0
          type: int
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
```

```bash
# Установка Tetragon
helm repo add cilium https://helm.cilium.io
helm install tetragon cilium/tetragon -n kube-system

# Просмотр событий загрузки библиотек
kubectl logs -n kube-system ds/tetragon -c export-stdout -f | \
  jq 'select(.process_kprobe.function == "fd_install") | {pod: .process.pod, file: .process_kprobe.args[1].file_arg.path}'
# → {"pod":"my-app-xyz","file":"/usr/lib/libssl.so.3"}
# → {"pod":"my-app-xyz","file":"/tmp/evil.so"}  ← DRIFT ALERT
```

### Сценарий 3: Сравнение runtime-SBOM с build-time SBOM

```bash
# 1. Получение CONTAINER ID и IMAGE из crictl
# Требует доступ к узлу или debug-контейнер с правами crictl
crictl ps --name my-app -q
# → abc1234567890abcdef

# Получение IMAGE_NAME для запущенного контейнера
IMAGE=$(crictl inspect abc1234567890abcdef | jq -r '.info.imageRef')
# → harbor.internal/my-app:v1.2.3

# 2. Runtime SBOM через syft (сканируем образ из containerd)
syft --from containerd "$IMAGE" -o cyclonedx-json > runtime-sbom.json

# 3. Build-time SBOM (эталонный) — извлекаем из реестра
syft "registry:$IMAGE" -o cyclonedx-json > build-sbom.json

# 4. Сравнение SBOM через cyclonedx-cli (рекомендуемый способ)
cyclonedx-cli diff ./build-sbom.json ./runtime-sbom.json --component-versions
# → Components only in runtime: libD:1.5.0, libE:2.0.0
# → Components with version changes: libA:1.0.0 → libA:1.1.0

# 5. Быстрая сверка через jq (без дополнительных тулов)
diff <(jq -r '.components[].purl' build-sbom.json | sort) \
     <(jq -r '.components[].purl' runtime-sbom.json | sort)
# → 7a8
# → +pkg:library/libD@1.5.0  ← DRIFT: не было в build-time
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
              image: ghcr.io/sykygirls/sbom-drift-checker:latest
                # кастомный образ с: trivy 0.71.0, syft 1.54.0, jq, crictl, cyclonedx-cli
              command:
                - /bin/sh
                - -c
                - |
                  set -e
                  
                  # Получение списка всех подов в production
                  kubectl get pods -n production -o json | \
                  jq -r '.items[] | select(.status.phase == "Running") | "\(.metadata.name)\t\(.spec.containers[0].image)"' | \
                  while IFS=$'\t' read -r pod image; do
                    echo "Checking $pod ($image)..."
                    
                    # Runtime SBOM — сканируем образ из containerd (отражает текущее состояние образа в реестре)
                    syft --from containerd "$image" -o cyclonedx-json > /tmp/runtime-sbom.json
                    
                    # Build-time SBOM (эталонный) — извлекаем из артефакт-реестра или генерируем заново
                    syft "registry:$image" -o cyclonedx-json > /tmp/build-sbom.json
                    
                    # Сравнение через cyclonedx-cli
                    changes=$(cyclonedx-cli diff /tmp/build-sbom.json /tmp/runtime-sbom.json \
                      --component-versions 2>/dev/null | grep -c "DRIFT\|changed\|only in")
                    
                    if [ "$changes" -gt 0 ]; then
                      echo "DRIFT DETECTED in $pod: $changes component differences"
                      # Алерт в Alertmanager/Prometheus
                      curl -s -X POST http://alertmanager:9093/api/v1/alerts -d '[{
                        "labels": {"alertname": "SBOMDrift", "pod": "'$pod'", "severity": "warning"},
                        "annotations": {"summary": "SBOM drift detected in '$pod'", "description": "'$changes' component differences found"}
                      }]'
                    fi
                  done
              volumeMounts:
                - name: containerd-sock
                  mountPath: /var/run/containerd
          volumes:
            - name: containerd-sock
              hostPath:
                path: /var/run/containerd
          restartPolicy: OnFailure
```

**Примечание:** Если образы в containerd отличаются от сборки (например, после `docker load`), используйте `syft <rootfs-path>` для сканирования файловой системы контейнера напрямую. Для этого получите путь через `crictl inspect <container-id> | jq -r '.info.rootfsPath'` и смонтируйте его в контейнере CronJob.

### Сценарий 5: Правило для обнаружения монтирования подозрительных томов

```yaml
# Tetragon: мониторинг volume mount syscall
# Используем sys_mount (syscall) вместо do_mount (kernel function)
# sys_mount(const char *source, const char *target, ...)
# target (точка монтирования) — arg index 1
apiVersion: cilium.io/v1alpha1
kind: TracingPolicy
metadata:
  name: monitor-volume-mounts
spec:
  kprobes:
    - call: sys_mount
      syscall: true
      args:
        - index: 0
          type: string
        - index: 1
          type: string
      selectors:
        - matchArgs:
            - index: 1
              operator: Prefix
              values:
                - /tmp/
                - /dev/shm/
```

## Лучшие практики

1. **Baseline SBOM:** Генерируйте SBOM при каждой сборке и храните как аттестацию. Это эталон для сравнения.
2. **eBPF-мониторинг в production:** Falco/Tetragon как DaemonSet — обязательный элемент observability.
3. **Автоматические алерты:** При обнаружении drift — алерт в Slack/PagerDuty с указанием pod, контейнера и типа drift.
4. **Блокировка подозрительных загрузок:** В Tetragon: используйте `matchActions: [{action: Sigkill}]` для блокировки загрузки из `/tmp/`, `/dev/shm/`.
5. **Регулярное сравнение:** Ежечасное или ежедневное сравнение runtime-SBOM с build-time SBOM через CronJob или systemd timer.
6. **Интеграция с admission control:** Kyverno может блокировать поды с volume mounts из неожиданных источников (см. [PolicyReporter](https://kyverno.io/)).
7. **Least privilege:** ServiceAccount для drift-checker должен иметь минимум RBAC: `get`, `list`, `watch` на `pods`; `create`/`get` на `jobs`/`pods/log`.
8. **Сокращение false positives:** Исключайте системные библиотеки (`/usr/lib`, `/lib`) из правил Falco, используйте исключения для init-контейнеров и sidecar.

## Валидация

```bash
# 1. Проверка eBPF поддержки на узле
ls /sys/kernel/btf/vmlinux && uname -r
# → /sys/kernel/btf/vmlinux  (есть)
# → 6.8.0-31-generic         (kernel >= 5.2)

# 2. Проверка работы Falco
kubectl -n falco logs -l app.kubernetes.io/name=falco --tail=20 | grep "Unexpected"
# → Нет алертов для штатных загрузок

# 3. Проверка работы Tetragon
kubectl -n kube-system logs ds/tetragon -c export-stdout -f | jq 'select(.process_kprobe.function == "sys_mount") | .result.process.podID'
# → (пустой вывод для штатных монтирований)

# 4. Проверка cron-задачи drift detection
kubectl -n security get cronjob sbom-drift-check
# → NAME                SCHEDULE      SUSPEND   ACTIVE   LAST SCHEDULE   AGE
#   sbom-drift-check    0 * * * *     False     1        5m              1h

# 5. Проверка отсутствия drift на healthy поде
kubectl -n security logs job/sbom-drift-check-20240615-0000 --tail=5
# → Checking my-app-7d5b8c9f4d-xk2m4 (harbor.internal/my-app:v1.2.3)
# → Checking my-app-7d5b8c9f4d-xk2m4... DRIFT: 0
```

## Устранение неполадок

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| Falco не генерирует алерты | eBPF не поддерживается на узле | Проверьте: `ls /sys/kernel/btf/vmlinux` и версию ядра ≥ 5.2; включите `--set driver.kind=classic` как fallback |
| Falco: false positives на `mmap` | Динамические загрузчики (ld.so) | Добавьте `proc.name in (ld-linux, ld-linux-x86-64)` в исключения правила |
| Tetragon не видит события | CRD не загружен | `kubectl apply -f https://raw.githubusercontent.com/cilium/tetragon/main/install/tetragon-operator.yaml` |
| syft не может прочитать образ | Нет доступа к containerd/CRI | Смонтируйте `/var/run/containerd` через hostPath; или используйте `--from registry` для прямого pull |
| cyclonedx-cli diff: 0 результатов | SBOM в разных форматах или без purl | Убедитесь, что оба SBOM содержат `purl` для компонентов; синхронизируйте `components[].purl` |
| Tetragon: слишком много шума | Правило слишком широко | Сузьте `matchArgs.values` до конкретных путей или используйте `matchBinaries` для исключения sh/systemd |
| CronJob падает с ошибкой `containerd: connection refused` | Сокет не смонтирован | Проверьте `hostPath: /var/run/containerd` и permissions; используйте `CONTAINERD_ADDRESS=unix:///host/containerd/containerd.sock` |

## Граничные случаи и ограничения

* **Windows-контейнеры:** eBPF не работает в Windows. Для Windows-контейнеров используйте Process Monitor и Sysmon.
* **Безопасность eBPF:** eBPF-программы требуют `CAP_BPF` или root. В production ограничьте доступ через RBAC и используйте `Cilium Enterprise` для enterprise-фич.
* **DinD (Docker-in-Docker):** В DinD-контейнерах мониторинг затруднён из-за изолированных namespace'ов. Используйте outer Docker socket или host-режим.
* **Ресурсоёмкость:** Tetragon/Falco добавляют 2–5% overhead на CPU. Для высоконагруженных узелов — профилирование и `sampling` в Tetragon.
* **Образы с динамическими загрузчиками:** Приложения на Java, Python (importlib), Go (plugin) часто загружают библиотеки динамически — добавляйте их в whitelist `expected_library_paths`, иначе будут false positives.
* **init-контейнеры:** Falco генерирует алерты на установку пакетов init-контейнерами. Добавляйте `container.name in (init-*)` в исключения.
* **Sidecar-паттерн:** Sidecar-контейнеры могут законно использовать `/tmp/`. Добавляйте `container.image.repository in (known-sidecars)` в whitelist.
* **eBPF на облаке:** Некоторые cloud-провайдеры (AWS EKS, GKE) ограничивают eBPF. Проверяйте поддержку перед установкой.

## Дополнительная информация

### Связанные документы

* [SBOM в продакшене](./sbom_in_production.md) — чтение SBOM, blast radius, VEX.
* [Анализ зависимостей и SBOM](./dependency_and_sbom_analysis.md) — генерация SBOM, SCA.
* [Целостность сборки](./build_integrity.md) — SLSA и воспроизводимость.
* [Реагирование на инциденты supply chain](./supply_chain_incident_response.md) — DFIR-процесс.
