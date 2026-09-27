# Недоступность узла: Проблемы SELinux и AppArmor

Профили Mandatory Access Control (MAC) — SELinux и AppArmor — являются слоями безопасности ОС, которые ограничивают права контейнеров на доступ к файлам, сетевым ресурсам и системным вызовам. Некорректная настройка или повреждение профилей приводит к невозможности запуска подов, блокировке exec и тайм-аутам, что маскируется как проблемы рантайма или сети.

## Основные определения

**SELinux (Security-Enhanced Linux)** — модуль ядра Linux, реализующий Mandatory Access Control через контексты безопасности (security contexts). В RHEL/CentOS/Fedora является основной системой MAC. Каждый процесс и файл имеет метку `user:role:type:level`. Контейнеры получают уникальный type (`container_t`), который ограничивает их доступ к файловым системам хоста.

**AppArmor** — модуль MAC, работающий через профили доступа (profiles), привязанные к путям файлов. Используется в Ubuntu/Debian. Профили определяют, какие файлы, сетевые порты и системные вызовы доступны контейнеру. В Kubernetes AppArmor профили задаются через аннотации пода.

**Kubernetes Integration (Security Context)** — поле `securityContext` в спецификации пода, позволяющее указать SELinux-метки (`seLinuxOptions`) или AppArmor-профиль (`container.apparmor.security.beta.kubernetes.io/<container>`). Начиная с K8s 1.30+, AppArmor поддерживается нативно через поле `appArmorProfile` в `securityContext`.

**SELinux Volume Context** — пометка файловой системы (PV/PVC) контекстом безопасности, необходимым для доступа контейнера. При монтировании PersistentVolume с `ReadWriteOnce` SELinux-контекст должен совпадать с контекстом пода. Несовпадение приводит к `Permission denied` на уровне ядра.

## Основные концепции

### Как SELinux/AppArmor влияют на доступность узла

| Сценарий | Симптом | Маскируется как |
| :--- | :--- | :--- |
| SELinux блокирует чтение rootfs контейнера | `CrashLoopBackOff`, `OCI runtime create failed` | Проблемы рантайма, повреждение образа |
| AppArmor запрещает exec в контейнер | `kubectl exec` падает с `exec failed` | Проблемы с CRI |
| SELinux блокирует монтирование PV | `MountVolume.SetUp failed`, `permission denied` | Проблемы с storage/CSI |
| SELinux relabeling при первом монтировании | Долгий запуск пода (30-60 сек), тайм-аут | Проблемы с производительностью диска |
| Конфликт между CNI и SELinux | `NetworkUnavailable`, поды без сети | Проблемы CNI |
| AppArmor блокирует сетевые операции | DNS не работает, Pod-to-Pod недоступен | Проблемы сети/CoreDNS |

### SELinux в контексте Kubernetes

**Контекст по умолчанию для контейнеров:**
```
system_u:system_r:container_t:s0:c100,c200
```
- `container_t` — тип процесса контейнера
- `s0:c100,c200` — MCS (Multi-Category Security) метка, уникальная для каждого пода

**Критические проблемы:**

1. **Mismatched SELinux context на PV**: Если PV содержит данные, созданные с одним SELinux-контекстом, а под запускается с другим — доступ будет запрещён. Решение: `seLinuxOptions` в `securityContext` или `chcon` на хосте.

2. **SELinux relabeling**: При монтировании PV с `seLinuxMount: true` kubelet выполняет `restorecon` на всей файловой системе. Для больших томов ( hundreds of GB) это занимает минуты и блокирует запуск пода.

3. **NFS и SELinux**: NFS не поддерживает SELinux labels по умолчанию. Требуется `context=` опция в mount или `fsuid`/`fsgid` настройки.

### AppArmor в контексте Kubernetes

**Способы назначения профиля (K8s 1.30+):**

| Метод | Пример | Статус |
| :--- | :--- | :--- |
| Аннотация (устаревший) | `container.apparmor.security.beta.kubernetes.io/app: runtime/default` | Работает, deprecated |
| Поле securityContext | `appArmorProfile: { type: RuntimeDefault }` | GA с 1.30 |
| Custom profile | `appArmorProfile: { type: Localhost, localhostProfile: my-profile }` | GA с 1.30 |

**Типы профилей:**
- `RuntimeDefault` — профиль по умолчанию рантайма (containerd/CRI-O). Наиболее безопасный.
- `Unconfined` — отключает AppArmor. Использовать только для отладки.
- `Localhost` — кастомный профиль из файла `/var/lib/kubelet/seccomp/profiles/` или `/etc/apparmor.d/`.

## Практические сценарии

### Сценарий 1: CrashLoopBackOut из-за SELinux

**Симптом**: Под падает сразу после запуска. `kubectl describe pod` показывает `OCI runtime create failed` или `ContainerSecurityContext`. Логи контейнера пусты.

**Диагностика:**
```bash
# 1. Проверка SELinux на узле
getenforce
# → Enforcing

# 2. Проверка audit логов на SELinux denial
sudo ausearch -m avc -ts recent | grep container
# → type=AVC msg=audit(1725456789.123:456): avc: denied { read } for pid=12345 comm="containerd-shim"
# →   name="passwd" dev="sda1" ino=12345 scontext=system_u:system_r:container_t:s0
# →   tcontext=system_u:object_r:passwd_file_t:s0 tclass=file permissive=0

# 3. Проверка контекста файловой системы
ls -Z /var/lib/kubelet/pods/
# → system_u:object_r:var_lib_kubelet_t:s0

# 4. Проверка контекста в поде
kubectl exec <pod> -- id -Z
# → system_u:system_r:container_t:s0:c100,c200

# 5. Проверка, блокирует ли SELinux exec
kubectl exec <pod> -- cat /etc/passwd
# → cat: /etc/passwd: Permission denied
```

**Решение:**
```bash
# Вариант 1: Добавить SELinux-контекст в под
# apiVersion: v1
# kind: Pod
# spec:
#   securityContext:
#     seLinuxOptions:
#       user: "system_u"
#       role: "system_r"
#       type: "container_t"
#       level: "s0:c100,c200"

# Вариант 2: Временно перевести SELinux в Permissive (для отладки)
sudo setenforce 0
# → SELinux перестает блокировать, но логирует все denial

# Вариант 3: Добавить custom SELinux module
sudo semanage fcontext -a -t container_file_t "/data(/.*)?"
sudo restorecon -Rv /data

# Вариант 4: Использовать fsGroup для NFS
# securityContext:
#   fsGroup: 1000
#   fsGroupChangePolicy: OnRootMismatch
```

---

### Сценарий 2: AppArmor блокирует exec и сетевые операции

**Симптом**: `kubectl exec` падает с ошибкой. Под работает, но DNS не резолвится или Pod-to-Pod трафик заблокирован.

**Диагностика:**
```bash
# 1. Проверка AppArmor профиля пода
kubectl get pod <pod> -o jsonpath='{.metadata.annotations}'
# → {"container.apparmor.security.beta.kubernetes.io/app":"localhost/my-custom-profile"}

# 2. Проверка профиля на узле
sudo cat /etc/apparmor.d/localhost_my-custom-profile
# → profile localhost/my-custom-profile flags=(attach_disconnected) {
# →   # Deny all network access
# →   deny network raw,
# →   deny network tcp,
# → }

# 3. Проверка audit логов AppArmor
sudo dmesg | grep "apparmor" | tail -10
# → [Sep  4 17:30:00] audit: type=1400 audit(1725456789.123:456): apparmor="DENIED"
# →   operation="exec" profile="localhost/my-custom-profile" name="/bin/sh" pid=12345

# 4. Проверка status AppArmor
sudo aa-status
# → apparmor module is loaded.
# → 256 profiles are loaded.
# → 128 profiles are in enforce mode.

# 5. Проверка, какие профили в enforce mode
sudo aa-status | grep enforce | head -5
```

**Решение:**
```yaml
# Вариант 1: Переключить под на RuntimeDefault (безопасный профиль)
apiVersion: v1
kind: Pod
spec:
  securityContext:
    appArmorProfile:
      type: RuntimeDefault

# Вариант 2: Временно отключить AppArmor для пода (отладка)
# metadata:
#   annotations:
#     container.apparmor.security.beta.kubernetes.io/app: unconfined

# Вариант 3: Исправить кастомный профиль
# Разрешить exec и сетевые операции:
# profile localhost/my-custom-profile flags=(attach_disconnected) {
#   # Allow basic operations
#   file,
#   network inet stream,
#   network inet dgram,
#   capability sys_admin,
# }
```

```bash
# Применение нового профиля на узле
sudo apparmor_parser -r /etc/apparmor.d/localhost_my-custom-profile
```

---

### Сценарий 3: SELinux блокирует монтирование PersistentVolume

**Симптом**: Под с PVC остаётся в `ContainerCreating`. Ошибка: `MountVolume.SetUp failed for volume "pvc-xxx": mount failed: exit status 32` или `permission denied`.

**Диагностика:**
```bash
# 1. Проверка ошибок в логах kubelet
journalctl -u kubelet -n 50 --no-pager | grep -i "selinux\|avc\|denied"
# → E0904 17:35:00 mount_linux.go:207] mount: /var/lib/kubelet/pods/xxx/volumes/kubernetes.io~csi/pvc-xxx/mount:
# →   mount(2) system call failed: Permission denied

# 2. Проверка SELinux-метки на PV
kubectl get pv <pv-name> -o jsonpath='{.spec.csi.volumeAttributes}'
# → {"storage.openshift.io/fsGroupChangePolicy":"OnRootMismatch"}

# 3. Проверка контекста на точке монтирования
ls -Z /var/lib/kubelet/pods/xxx/volumes/kubernetes.io~csi/
# → system_u:object_r:container_file_t:s0  ← должно совпадать с контекстом пода

# 4. Проверка audit log
sudo ausearch -m avc -ts recent | grep "csi\|mount\|kubelet"
# → type=AVC msg=audit(...): avc: denied { mount } for pid=12345 comm="mount"
# →   scontext=system_u:system_r:container_t:s0 tcontext=system_u:object_r:nfs_t:s0

# 5. Проверка seLinuxMount в StorageClass
kubectl get sc <sc-name> -o yaml | grep -i selinux
# → mountOptions:
# →   - seLinuxMount: true
```

**Решение:**
```bash
# Вариант 1: Установить SELinux-контекст на PV через CSI volumeAttributes
#apiVersion: storage.k8s.io/v1
#kind: StorageClass
#parameters:
#  csi.storage.k8s.io/node-stage-secret-namespace: default
#  seLinuxMount: "true"

# Вариант 2: Ручная установка контекста на хосте (если PV доступен)
sudo semanage fcontext -a -t container_file_t "/mnt/data(/.*)?"
sudo restorecon -Rv /mnt/data

# Вариант 3: Использовать fsGroup для автоматического chown
# spec:
#   securityContext:
#     fsGroup: 1000
#     fsGroupChangePolicy: OnRootMismatch

# Вариант 4: Для NFS — использовать context= в mount options
# mountOptions:
#   - "context=system_u:object_r:nfs_t:s0"
```

---

### Сценарий 4: Долгий запуск пода из-за SELinux Relabeling

**Симптом**: Под запускается 30-60 секунд дольше обычного. Нет ошибок, но `kubectl get pods` показывает长时间 `ContainerCreating` перед `Running`.

**Причина**: При монтировании PV с `seLinuxMount: true` kubelet выполняет `restorecon -R` на всей файловой системе. Для больших томов (100GB+) это занимает минуты.

**Диагностика:**
```bash
# 1. Проверка времени запуска пода
kubectl get pod <pod> -o jsonpath='{.status.conditions[?(@.type=="Ready")].lastTransitionTime}'
# → Compare with .status.startTime

# 2. Проверка, выполняется ли relabeling
journalctl -u kubelet -n 100 --no-pager | grep -i "selinux\|restorecon\|relabel"
# → I0904 17:35:00 operation_executor.go:1045] MountVolume.SetUp volume
# →   running SELinux relabeling for volume pvc-xxx (size: 50Gi)

# 3. Проверка процесса restorecon на узле
ps aux | grep restorecon
# → root  12345  0.0  0.0  123456  7890 ?  S  17:35  0:05 restorecon -R /var/lib/kubelet/pods/xxx/volumes/...
```

**Решение:**
```bash
# Вариант 1: Отключить SELinux relabeling для конкретного PV
# В StorageClass:
# parameters:
#   seLinuxMount: "false"

# Вариант 2: Предварительная подготовка данных на PV с правильным контекстом
sudo chcon -R -t container_file_t /mnt/data

# Вариант 3: Использовать HostPath с правильным контекстом до запуска подов
```

---

### Сценарий 5: Конфликт SELinux и CNI (NetworkUnavailable)

**Симптом**: Узел `NotReady` с `NetworkUnavailable=True`. CNI (Calico/Flannel) падает при попытке настроить правила iptables/nftables.

**Диагностика:**
```bash
# 1. Проверка CNI пода
kubectl get pods -n kube-system -l k8s-app=calico-node -o wide | grep <node>
# → calico-node-xyz  0/1  Error  5  10m

# 2. Проверка логов CNI на SELinux denial
kubectl logs -n kube-system calico-node-xyz | grep -i "selinux\|avc\|denied" | tail -5
# → [ERROR] felix/iptables.go:426 Failed to update iptables:
# →   exit status 4: Another app is currently holding the xtables lock.

# 3. Проверка audit log на узле
sudo ausearch -m avc -ts recent | grep "iptables\|calico\|network"
# → type=AVC msg=audit(...): avc: denied { write } for pid=12345 comm="iptables"
# →   path="/proc/net/ip_tables_names" scontext=system_u:system_r:container_t:s0

# 4. Проверка SELinux-политики для CNI
sudo semanage boolean -l | grep -i "container\|network"
# → container_manage_cgroup    (off  ,  off)  Allow containers to manage cgroups
```

**Решение:**
```bash
# Вариант 1: Включить необходимые boolean для CNI
sudo setsebool -P container_manage_cgroup on
sudo setsebool -P container_use_cephfs on

# Вариант 2: Добавить custom SELinux policy для CNI
cat <<EOF | sudo tee /tmp/cni.te
module cni 1.0;
require {
    type container_t;
    type unconfined_t;
    class capability { net_admin net_raw };
    class file { read write open };
}
allow container_t self:capability { net_admin net_raw };
allow container_t unconfined_t:file { read write open };
EOF
sudo checkmodule -M -m -o /tmp/cni.mod /tmp/cni.te
sudo semodule_package -o /tmp/cni.pp -m /tmp/cni.mod
sudo semodule -i /tmp/cni.pp

# Вариант 3: Переключить CNI на nftables backend (обходит SELinux)
# Calico: FelixConfiguration с vxlanEnabled: true вместо iptables
```

---

### Сценарий 6: AppArmor профиль блокирует PIDPressure диагностику

**Симптом**: Узел в `PIDPressure=True`, но `kubectl exec` в поды не работает — AppArmor блокирует чтение `/proc` и выполнение диагностики.

**Диагностика:**
```bash
# 1. Попытка exec в под
kubectl exec <pod> -- ps aux
# → exec failed: unable to start container process: unable to mount proc

# 2. Проверка AppArmor профиля
kubectl get pod <pod> -o jsonpath='{.metadata.annotations.container.apparmor.security.beta.kubernetes.io/app}'
# → localhost/restricted-profile

# 3. Проверкаdeny rules в профиле
sudo cat /etc/apparmor.d/localhost_restricted-profile | grep -i proc
# → deny /proc/** w,
# → deny /sys/** w,
```

**Решение:**
```yaml
# Создать отдельный под с RuntimeDefault для диагностики
apiVersion: v1
kind: Pod
metadata:
  name: debug-node
spec:
  nodeName: <problem-node>
  hostPID: true
  hostNetwork: true
  securityContext:
    appArmorProfile:
      type: Unconfined
  containers:
  - name: debug
    image: busybox:1.36
    command: ["sleep", "3600"]
    securityContext:
      privileged: true
```

## Мониторинг и алертинг

### Метрики SELinux/AppArmor

| Метрика | Описание | Типичный порог алерта |
| :--- | :--- | :--- |
| `node_selinux_enforcement` | SELinux mode (1=Enforcing, 0=Permissive) | == 0持续 5 минут |
| `node_apparmor_profiles_loaded` | Количество загруженных AppArmor профилей | Уменьшение > 10 за 5 минут |
| `audit AVC denial rate rate` | Частота SELinux denial в audit log | > 10/sec持续 5 минут |

### Примеры алертов (PrometheusRule)

```yaml
groups:
  - name: mac-security
    rules:
      - alert: SELinuxPermissive
        expr: node_selinux_enforcement == 0
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "SELinux в Permissive на {{ $labels.instance }}"
          description: "SELinux переведен в Permissive — безопасность снижена"

      - alert: SELinuxDenialsHigh
        expr: rate(audit_deny_total{type="AVC"}[5m]) > 10
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Высокий уровень SELinux denial на {{ $labels.instance }}"
          description: "Более 10 AVC denial в секунду — возможны проблемы с контейнерами"
```

## Дополнительная информация

### Полезные команды

```bash
# SELinux
getenforce                          # Текущий режим
sudo setenforce 0                   # Permissive (временно)
sudo setenforce 1                   # Enforcing
seinfo                              # Информация о SELinux policy
sesearch -A -s container_t          # Поиск правил для container_t
sudo ausearch -m avc -ts recent     # Последние AVC denial
sudo aureport -a                    # Отчет по audit

# AppArmor
sudo aa-status                      # Статус профилей
sudo aa-enforce /etc/apparmor.d/profile  # Переключить в enforce
sudo aa-complain /etc/apparmor.d/profile  # Переключить в complain
sudo apparmor_parser -r /etc/apparmor.d/profile  # Перезагрузить профиль
```

### Связанные разделы

- **[Проблемы рантайма](./runtime_issues.md)** — SELinux/AppArmor ошибки маскируются как проблемы CRI
- **[Диагностика узла](./diagnostics.md)** — проверка SELinux/AppArmor как часть диагностики
- **[Давление ресурсов](./resource_pressure.md)** — AppArmor может блокировать диагностику PIDPressure
- **[Обслуживание узлов](./maintenance.md)** — SELinux context при drain/restore
- **[Docker Security](../../../Docker/Docker_security/container_hardening.md)** — SELinux/AppArmor на уровне Docker
- **[Pod Security Standards](../../../Kubernetes/Security/pod_security_context.md)** — взаимодействие с MAC
